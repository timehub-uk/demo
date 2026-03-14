"""
ML Backtesting Engine.

Replays historical data through trained ML models to evaluate strategy performance.
Supports both the universal LSTM/Transformer model and per-token models.

Metrics produced:
  - Total return, CAGR
  - Sharpe ratio, Sortino ratio
  - Max drawdown, Calmar ratio
  - Win rate, profit factor, avg win/loss
  - Trade-by-trade log
  - Equity curve (time series)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import pandas as pd

from loguru import logger
from utils.logger import get_intel_logger


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    symbol: str
    interval: str = "1h"
    start_date: Optional[str] = None     # ISO date string or None for all data
    end_date:   Optional[str] = None
    initial_capital: float = 10_000.0
    fee_pct: float = 0.001               # 0.1% Binance taker fee each side
    slippage_pct: float = 0.0005         # 0.05% slippage
    position_size_pct: float = 0.95      # % of available capital per trade
    stop_loss_pct: float = 0.02          # 2% SL
    take_profit_pct: float = 0.04        # 4% TP (1:2 R:R)
    confidence_threshold: float = 0.60   # Min confidence to act on signal
    use_per_token_model: bool = True      # Use TokenMLNet if available, else universal
    max_open_trades: int = 1             # Max concurrent positions per symbol


@dataclass
class BacktestTrade:
    symbol: str
    direction: str           # BUY or SELL
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    exit_reason: str         # SL | TP | SIGNAL | EOD
    confidence: float


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    equity_timestamps: list[str] = field(default_factory=list)

    # Performance metrics
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_trade_duration_hours: float = 0.0
    best_trade_pct: float = 0.0
    worst_trade_pct: float = 0.0
    final_capital: float = 0.0

    def summary(self) -> str:
        return (
            f"Return: {self.total_return_pct:+.1f}% | "
            f"Sharpe: {self.sharpe_ratio:.2f} | "
            f"MaxDD: {self.max_drawdown_pct:.1f}% | "
            f"WinRate: {self.win_rate:.0%} | "
            f"Trades: {self.total_trades} | "
            f"PF: {self.profit_factor:.2f}"
        )


# ── Backtester ────────────────────────────────────────────────────────────────

class Backtester:
    """
    Replays historical OHLCV data through an ML model to simulate trading.
    Generates a complete BacktestResult with equity curve and metrics.
    """

    def __init__(self, predictor=None) -> None:
        self._predictor = predictor    # Universal MLPredictor (optional)
        self._intel = get_intel_logger()
        self._running = False
        self._progress_callbacks: list[Callable] = []

    def on_progress(self, cb: Callable) -> None:
        self._progress_callbacks.append(cb)

    def stop(self) -> None:
        self._running = False

    def run(self, config: BacktestConfig, progress_cb: Callable | None = None) -> BacktestResult:
        """
        Run a full backtest for config.symbol on config.interval.
        Returns a BacktestResult with all metrics populated.
        """
        self._running = True
        self._intel.ml("Backtester", f"🔄 Starting backtest: {config.symbol} / {config.interval} | ${config.initial_capital:,.0f}")

        # Load data
        df = self._load_data(config)
        if df.empty or len(df) < 50:
            self._intel.warning("Backtester", f"Insufficient data for {config.symbol}/{config.interval}")
            return BacktestResult(config=config)

        total_rows = len(df)
        self._emit_progress(0, f"Loaded {total_rows} rows for {config.symbol}")

        # Load model
        model_fn = self._get_predict_fn(config)

        # Simulation state
        capital = config.initial_capital
        position: Optional[BacktestTrade] = None
        equity_curve: list[float] = []
        equity_timestamps: list[str] = []
        trades: list[BacktestTrade] = []
        seq_len = 30   # Match TokenMLNet / universal model seq length

        for i in range(seq_len, len(df)):
            if not self._running:
                break

            row = df.iloc[i]
            close = float(row["close"])
            ts_str = str(row.get("open_time", i))

            # Check if open position hits SL/TP
            if position is not None:
                exit_reason = self._check_exit(position, row, config)
                if exit_reason:
                    position = self._close_position(position, close, exit_reason, capital)
                    trades.append(position)
                    capital += position.pnl
                    position = None

            # Generate signal from model
            window = df.iloc[max(0, i - seq_len):i]
            signal_result = model_fn(window)
            signal = signal_result.get("signal", "HOLD")
            confidence = signal_result.get("confidence", 0.0)

            # Enter new position
            if position is None and confidence >= config.confidence_threshold:
                if signal == "BUY":
                    entry_cost = capital * config.position_size_pct
                    qty = (entry_cost / close) * (1 - config.fee_pct - config.slippage_pct)
                    position = BacktestTrade(
                        symbol=config.symbol, direction="BUY",
                        entry_time=datetime.now(timezone.utc),
                        exit_time=None,
                        entry_price=close * (1 + config.slippage_pct),
                        exit_price=0, quantity=qty,
                        pnl=0, pnl_pct=0,
                        exit_reason="", confidence=confidence,
                    )
                elif signal == "SELL":
                    entry_cost = capital * config.position_size_pct
                    qty = (entry_cost / close) * (1 - config.fee_pct - config.slippage_pct)
                    position = BacktestTrade(
                        symbol=config.symbol, direction="SELL",
                        entry_time=datetime.now(timezone.utc),
                        exit_time=None,
                        entry_price=close * (1 - config.slippage_pct),
                        exit_price=0, quantity=qty,
                        pnl=0, pnl_pct=0,
                        exit_reason="", confidence=confidence,
                    )

            # Mark-to-market equity
            position_value = 0.0
            if position is not None:
                if position.direction == "BUY":
                    position_value = position.quantity * close - position.quantity * position.entry_price
                else:
                    position_value = position.quantity * position.entry_price - position.quantity * close
            equity_curve.append(capital + position_value)
            equity_timestamps.append(ts_str)

            if i % 200 == 0:
                pct = (i / total_rows) * 100
                self._emit_progress(pct, f"Backtesting {config.symbol} – bar {i}/{total_rows}")
                if progress_cb:
                    progress_cb({"pct": pct, "symbol": config.symbol, "capital": capital + position_value})

        # Close any open position at end
        if position is not None and len(df) > 0:
            last_close = float(df.iloc[-1]["close"])
            position = self._close_position(position, last_close, "EOD", capital)
            trades.append(position)
            capital += position.pnl

        result = BacktestResult(config=config, trades=trades,
                                equity_curve=equity_curve,
                                equity_timestamps=equity_timestamps)
        self._compute_metrics(result, config.initial_capital)

        self._emit_progress(100, f"✅ Backtest complete: {result.summary()}")
        self._intel.ml("Backtester", f"✅ Backtest done | {result.summary()}")
        self._running = False
        return result

    # ── Internal helpers ───────────────────────────────────────────────

    def _load_data(self, config: BacktestConfig) -> pd.DataFrame:
        try:
            from ml.data_collector import DataCollector
            df = DataCollector.load_dataframe(config.symbol, config.interval, limit=50000)
            if df.empty:
                return df
            if config.start_date:
                df = df[df["open_time"] >= pd.Timestamp(config.start_date, tz="UTC")]
            if config.end_date:
                df = df[df["open_time"] <= pd.Timestamp(config.end_date, tz="UTC")]
            return df.reset_index(drop=True)
        except Exception as exc:
            logger.warning(f"Backtester data load error: {exc}")
            return pd.DataFrame()

    def _get_predict_fn(self, config: BacktestConfig) -> Callable:
        """Return a predict function: (df_window) → {signal, confidence}"""
        # Try per-token model first
        if config.use_per_token_model:
            try:
                from ml.token_ml_task import TokenMLTask
                task = TokenMLTask(config.symbol)
                if task.is_trained:
                    logger.debug(f"Backtester: using per-token model for {config.symbol}")
                    return task.predict
            except Exception:
                pass

        # Fall back to universal predictor
        if self._predictor:
            try:
                return lambda df: self._predictor.predict(config.symbol, df=df)
            except Exception:
                pass

        # Fallback: random walk (demo mode)
        rng = np.random.default_rng(42)
        def _demo(df):
            r = rng.random()
            if r < 0.33:
                return {"signal": "BUY",  "confidence": 0.5 + r}
            elif r < 0.66:
                return {"signal": "SELL", "confidence": 0.5 + (r - 0.33)}
            return {"signal": "HOLD", "confidence": 0.5}
        return _demo

    def _check_exit(self, pos: BacktestTrade, row, config: BacktestConfig) -> Optional[str]:
        close = float(row["close"])
        high  = float(row.get("high", close))
        low   = float(row.get("low", close))

        if pos.direction == "BUY":
            sl_price = pos.entry_price * (1 - config.stop_loss_pct)
            tp_price = pos.entry_price * (1 + config.take_profit_pct)
            if low <= sl_price:
                return "SL"
            if high >= tp_price:
                return "TP"
        else:  # SELL
            sl_price = pos.entry_price * (1 + config.stop_loss_pct)
            tp_price = pos.entry_price * (1 - config.take_profit_pct)
            if high >= sl_price:
                return "SL"
            if low <= tp_price:
                return "TP"
        return None

    def _close_position(self, pos: BacktestTrade, exit_price: float,
                        reason: str, capital: float) -> BacktestTrade:
        fee = exit_price * pos.quantity * 0.001  # 0.1% taker fee per side
        if pos.direction == "BUY":
            gross = (exit_price - pos.entry_price) * pos.quantity
        else:
            gross = (pos.entry_price - exit_price) * pos.quantity
        net_pnl = gross - abs(fee)
        denominator = pos.entry_price * pos.quantity
        pnl_pct = net_pnl / denominator * 100 if denominator else 0.0

        return BacktestTrade(
            symbol=pos.symbol, direction=pos.direction,
            entry_time=pos.entry_time,
            exit_time=datetime.now(timezone.utc),
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            pnl=net_pnl, pnl_pct=pnl_pct,
            exit_reason=reason,
            confidence=pos.confidence,
        )

    def _compute_metrics(self, result: BacktestResult, initial_capital: float) -> None:
        eq = np.array(result.equity_curve) if result.equity_curve else np.array([initial_capital])
        trades = result.trades

        result.final_capital = float(eq[-1]) if len(eq) > 0 else initial_capital
        result.total_return_pct = (result.final_capital - initial_capital) / initial_capital * 100
        result.total_trades = len(trades)

        # CAGR
        if len(eq) > 1:
            years = len(eq) / (365 * 24)   # Assuming 1h bars → bars/year
            if years > 0 and result.final_capital > 0:
                result.cagr_pct = ((result.final_capital / initial_capital) ** (1 / max(years, 0.01)) - 1) * 100

        # Returns series
        if len(eq) > 1:
            rets = np.diff(eq) / eq[:-1]
            mean_ret = np.mean(rets)
            std_ret  = np.std(rets)
            downside = rets[rets < 0]
            downside_std = np.std(downside) if len(downside) > 0 else std_ret

            result.sharpe_ratio  = float(mean_ret / (std_ret + 1e-9) * np.sqrt(8760))
            result.sortino_ratio = float(mean_ret / (downside_std + 1e-9) * np.sqrt(8760))

        # Max drawdown
        peak = np.maximum.accumulate(eq)
        drawdowns = (eq - peak) / (peak + 1e-9) * 100
        result.max_drawdown_pct = float(abs(np.min(drawdowns)))
        if result.max_drawdown_pct > 0:
            result.calmar_ratio = result.cagr_pct / result.max_drawdown_pct

        # Trade stats
        if trades:
            wins  = [t for t in trades if t.pnl > 0]
            losses = [t for t in trades if t.pnl <= 0]
            result.winning_trades = len(wins)
            result.losing_trades  = len(losses)
            result.win_rate = len(wins) / len(trades) if trades else 0.0
            result.avg_win_pct  = float(np.mean([t.pnl_pct for t in wins])) if wins else 0.0
            result.avg_loss_pct = float(np.mean([t.pnl_pct for t in losses])) if losses else 0.0
            gross_profit = sum(t.pnl for t in wins)
            gross_loss   = abs(sum(t.pnl for t in losses))
            result.profit_factor = gross_profit / (gross_loss + 1e-9)
            all_pnl_pcts = [t.pnl_pct for t in trades]
            result.best_trade_pct  = float(max(all_pnl_pcts))
            result.worst_trade_pct = float(min(all_pnl_pcts))

    def _emit_progress(self, pct: float, msg: str) -> None:
        for cb in self._progress_callbacks:
            try:
                cb({"pct": pct, "message": msg})
            except Exception:
                pass
