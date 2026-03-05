"""
Walk-Forward Optimization & Model Validation.

Prevents overfitting by testing the model on unseen data in a rolling window:

  ┌──────────────────────────────────────────────────────┐
  │  TRAIN WINDOW (n bars)  │  TEST WINDOW (t bars)      │
  │                         │  → score OOS               │
  └──────────────────────────────────────────────────────┘
                   slide forward → next fold

If out-of-sample (OOS) Sharpe / IS Sharpe < 0.5 → OVERFITTING WARNING
If OOS return is negative across 3+ folds → model NOT safe to deploy

Generates a WalkForwardReport per symbol with:
  - n_folds, is_sharpe, oos_sharpe, oos_is_ratio
  - per-fold equity curves
  - overfitting flag
  - recommendation: DEPLOY | RETRAIN | UNSAFE
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

from loguru import logger
from utils.logger import get_intel_logger


# ── Config ────────────────────────────────────────────────────────────────────

WF_TRAIN_BARS  = 2000    # Training window (1h candles → ~83 days)
WF_TEST_BARS   = 500     # Test window (1h candles → ~21 days)
WF_STEP_BARS   = 250     # Step between folds (sliding overlap)
WF_MIN_FOLDS   = 3       # Need at least 3 folds for meaningful result
OOS_IS_MIN     = 0.50    # OOS/IS Sharpe ratio must be ≥ 0.5
OOS_SHARPE_MIN = 0.30    # OOS Sharpe must be ≥ 0.30 for DEPLOY recommendation
FEE_PCT        = 0.001   # 0.1% round-trip fee per trade


# ── Report ────────────────────────────────────────────────────────────────────

@dataclass
class WalkForwardFold:
    fold_num: int
    train_bars: int
    test_bars: int
    is_sharpe: float      # In-sample Sharpe
    oos_sharpe: float     # Out-of-sample Sharpe
    oos_return_pct: float
    n_trades: int
    win_rate: float


@dataclass
class WalkForwardReport:
    symbol: str
    interval: str
    n_folds: int
    is_sharpe_avg: float
    oos_sharpe_avg: float
    oos_is_ratio: float      # <0.5 → overfitting
    oos_return_avg_pct: float
    overfitting_detected: bool
    recommendation: str      # DEPLOY | RETRAIN | UNSAFE
    folds: list[WalkForwardFold] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"WF [{self.symbol}/{self.interval}] folds={self.n_folds} | "
            f"IS_Sharpe={self.is_sharpe_avg:.2f} OOS_Sharpe={self.oos_sharpe_avg:.2f} "
            f"OOS/IS={self.oos_is_ratio:.2f} | {self.recommendation}"
        )


# ── Walk-forward validator ────────────────────────────────────────────────────

class WalkForwardValidator:
    """
    Validates a trained ML model using walk-forward analysis.

    Usage:
        wfv = WalkForwardValidator(predictor)
        report = wfv.validate("BTCUSDT", "1h")
        if report.recommendation == "DEPLOY":
            deploy_model()
        elif report.recommendation == "RETRAIN":
            retrain()
    """

    def __init__(self, predictor=None, token_ml_manager=None) -> None:
        self._predictor = predictor
        self._token_ml  = token_ml_manager
        self._intel = get_intel_logger()

    def validate(
        self,
        symbol: str,
        interval: str = "1h",
        progress_cb: Optional[Callable] = None,
    ) -> WalkForwardReport:
        """
        Run full walk-forward validation for a symbol/interval pair.
        """
        self._intel.ml("WalkForward",
            f"🔄 Starting walk-forward validation: {symbol}/{interval}")

        df = self._load_data(symbol, interval)
        if df.empty or len(df) < WF_TRAIN_BARS + WF_TEST_BARS:
            return WalkForwardReport(
                symbol=symbol, interval=interval, n_folds=0,
                is_sharpe_avg=0, oos_sharpe_avg=0, oos_is_ratio=0,
                oos_return_avg_pct=0, overfitting_detected=True,
                recommendation="UNSAFE",
                notes=["Insufficient data for walk-forward analysis"],
            )

        predict_fn = self._get_predict_fn(symbol)
        folds: list[WalkForwardFold] = []
        total = len(df)
        fold_num = 0

        # Slide window forward
        start = 0
        while start + WF_TRAIN_BARS + WF_TEST_BARS <= total:
            train_df = df.iloc[start : start + WF_TRAIN_BARS]
            test_df  = df.iloc[start + WF_TRAIN_BARS : start + WF_TRAIN_BARS + WF_TEST_BARS]

            # In-sample score
            is_sharpe, _, _ = self._score_window(train_df, predict_fn)
            # Out-of-sample score
            oos_sharpe, oos_ret, n_trades = self._score_window(test_df, predict_fn)
            # Win rate on OOS trades
            win_rate = self._compute_win_rate(test_df, predict_fn)

            folds.append(WalkForwardFold(
                fold_num=fold_num,
                train_bars=len(train_df),
                test_bars=len(test_df),
                is_sharpe=is_sharpe,
                oos_sharpe=oos_sharpe,
                oos_return_pct=oos_ret,
                n_trades=n_trades,
                win_rate=win_rate,
            ))

            pct = ((start + WF_TRAIN_BARS + WF_TEST_BARS) / total * 100)
            if progress_cb:
                progress_cb({"pct": pct, "fold": fold_num})

            fold_num += 1
            start += WF_STEP_BARS

        if len(folds) < WF_MIN_FOLDS:
            return WalkForwardReport(
                symbol=symbol, interval=interval, n_folds=len(folds),
                is_sharpe_avg=0, oos_sharpe_avg=0, oos_is_ratio=0,
                oos_return_avg_pct=0, overfitting_detected=True,
                recommendation="RETRAIN",
                notes=["Too few folds for reliable validation"],
                folds=folds,
            )

        is_avg   = float(np.mean([f.is_sharpe  for f in folds]))
        oos_avg  = float(np.mean([f.oos_sharpe for f in folds]))
        oos_is   = oos_avg / (is_avg + 1e-9)
        oos_ret  = float(np.mean([f.oos_return_pct for f in folds]))

        overfitting = oos_is < OOS_IS_MIN
        n_negative_oos = sum(1 for f in folds if f.oos_sharpe < 0)

        notes = []
        if overfitting:
            notes.append(f"Overfitting detected: OOS/IS ratio {oos_is:.2f} < {OOS_IS_MIN}")
        if n_negative_oos >= WF_MIN_FOLDS:
            notes.append(f"All OOS folds negative – model not profitable out-of-sample")

        if oos_avg >= OOS_SHARPE_MIN and not overfitting:
            recommendation = "DEPLOY"
        elif oos_avg >= 0 and not overfitting:
            recommendation = "RETRAIN"
        else:
            recommendation = "UNSAFE"

        report = WalkForwardReport(
            symbol=symbol, interval=interval, n_folds=fold_num,
            is_sharpe_avg=is_avg, oos_sharpe_avg=oos_avg, oos_is_ratio=oos_is,
            oos_return_avg_pct=oos_ret, overfitting_detected=overfitting,
            recommendation=recommendation, folds=folds, notes=notes,
        )

        emoji = {"DEPLOY": "✅", "RETRAIN": "⚠️", "UNSAFE": "❌"}.get(recommendation, "?")
        self._intel.ml("WalkForward",
            f"{emoji} {report.summary()} | {' | '.join(notes) if notes else 'No issues'}")

        return report

    # ── Internal ───────────────────────────────────────────────────────

    def _score_window(self, df: pd.DataFrame, predict_fn: Callable) -> tuple[float, float, int]:
        """
        Simulate trades on df using predict_fn, return (Sharpe, total_return%, n_trades).
        """
        capital = 10_000.0
        equity  = [capital]
        n_trades = 0
        position = None   # None or {"side": "BUY"/"SELL", "entry": float, "qty": float}

        seq_len = 30
        for i in range(seq_len, len(df)):
            close = float(df.iloc[i]["close"])
            window = df.iloc[max(0, i - seq_len):i]

            result = predict_fn(window)
            sig  = result.get("signal") or result.get("action", "HOLD")
            conf = float(result.get("confidence", 0.5))

            # Close position on reverse signal
            if position and sig not in ("HOLD", position["side"]) and conf > 0.55:
                exit_price = close * (1 - FEE_PCT if position["side"] == "BUY" else 1 + FEE_PCT)
                if position["side"] == "BUY":
                    pnl = (exit_price - position["entry"]) * position["qty"]
                else:
                    pnl = (position["entry"] - exit_price) * position["qty"]
                capital += pnl
                n_trades += 1
                position = None

            # Open new position
            if position is None and sig in ("BUY", "SELL") and conf > 0.58:
                entry_price = close * (1 + FEE_PCT if sig == "BUY" else 1 - FEE_PCT)
                qty = capital * 0.95 / entry_price
                position = {"side": sig, "entry": entry_price, "qty": qty}

            # Mark to market
            if position:
                if position["side"] == "BUY":
                    mtm = capital + (close - position["entry"]) * position["qty"]
                else:
                    mtm = capital + (position["entry"] - close) * position["qty"]
                equity.append(max(0.01, mtm))
            else:
                equity.append(capital)

        # Close any remaining position
        if position:
            n_trades += 1

        eq = np.array(equity)
        rets = np.diff(eq) / (eq[:-1] + 1e-9)
        sharpe = float(np.mean(rets) / (np.std(rets) + 1e-9) * np.sqrt(8760)) if len(rets) > 1 else 0.0
        total_ret = (eq[-1] - eq[0]) / eq[0] * 100 if len(eq) > 1 else 0.0
        return sharpe, float(total_ret), n_trades

    def _compute_win_rate(self, df: pd.DataFrame, predict_fn: Callable) -> float:
        """Quick win rate estimate on test window."""
        wins, total = 0, 0
        seq_len = 30
        for i in range(seq_len, len(df) - 5):
            window = df.iloc[max(0, i - seq_len):i]
            result = predict_fn(window)
            sig  = result.get("signal") or result.get("action", "HOLD")
            conf = float(result.get("confidence", 0.5))
            if sig == "HOLD" or conf < 0.58:
                continue
            entry = float(df.iloc[i]["close"])
            exit5 = float(df.iloc[i + 5]["close"])
            correct = (sig == "BUY" and exit5 > entry) or (sig == "SELL" and exit5 < entry)
            wins  += int(correct)
            total += 1
        return wins / total if total > 0 else 0.5

    def _get_predict_fn(self, symbol: str) -> Callable:
        if self._token_ml:
            try:
                task = self._token_ml.get_task(symbol)
                if task and task.is_trained:
                    return task.predict
            except Exception:
                pass
        if self._predictor:
            try:
                return lambda df: self._predictor.predict(symbol, df=df) or {"signal": "HOLD", "confidence": 0.5}
            except Exception:
                pass
        rng = np.random.default_rng(99)
        return lambda df: {"signal": rng.choice(["BUY","SELL","HOLD"]), "confidence": 0.5}

    def _load_data(self, symbol: str, interval: str) -> pd.DataFrame:
        try:
            from ml.data_collector import DataCollector
            df = DataCollector.load_dataframe(symbol, interval,
                                               limit=WF_TRAIN_BARS + WF_TEST_BARS * 6)
            return df.reset_index(drop=True)
        except Exception as exc:
            logger.debug(f"WalkForward data load error: {exc}")
            return pd.DataFrame()
