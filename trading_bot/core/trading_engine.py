"""
Main trading engine – orchestrates auto / manual trading,
integrates ML signals, risk management, and order execution.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from enum import Enum
from typing import Callable, Optional

from loguru import logger

from config import get_settings
from .binance_client import BinanceClient
from .order_manager import OrderManager
from .portfolio import PortfolioManager
from .risk_manager import RiskManager, RiskMetrics, TradeProposal
from db.redis_client import RedisClient


class EngineMode(str, Enum):
    MANUAL = "manual"
    AUTO = "auto"
    HYBRID = "hybrid"
    PAUSED = "paused"
    PAPER = "paper"     # Simulated trading – no real orders sent


class TradingEngine:
    """
    Central trading orchestrator.

    Responsibilities:
    - Subscribe to real-time market data
    - Receive ML signals and evaluate them through risk manager
    - Execute approved orders via OrderManager
    - Maintain engine state (mode, heartbeat, metrics)
    - Emit events to UI via callbacks
    """

    def __init__(
        self,
        binance_client: BinanceClient,
        order_manager: OrderManager,
        portfolio_manager: PortfolioManager,
        risk_manager: RiskManager,
        user_id: str,
    ) -> None:
        self._client = binance_client
        self._orders = order_manager
        self._portfolio = portfolio_manager
        self._risk = risk_manager
        self._redis = RedisClient()
        self._settings = get_settings()
        self._user_id = user_id

        self._mode = EngineMode(self._settings.trading.mode)
        self._running = False
        self._heartbeat_thread: threading.Thread | None = None
        self._sync_thread: threading.Thread | None = None
        self._active_symbols: set[str] = set()
        self._callbacks: dict[str, list[Callable]] = {
            "trade": [], "signal": [], "mode_change": [],
            "error": [], "heartbeat": [], "whale": [], "token_signal": [],
        }
        self._metrics: dict = {
            "trades_today": 0, "wins_today": 0, "losses_today": 0,
            "pnl_today": 0.0, "signals_processed": 0, "orders_rejected": 0,
        }

        # Paper trading state
        self._paper_capital: float = 10_000.0
        self._paper_positions: dict[str, dict] = {}   # symbol → {qty, entry_price, side}
        self._paper_trades: list[dict] = []

        # Pluggable signal sources
        self._whale_watcher = None       # Set via set_whale_watcher()
        self._token_ml_manager = None    # Set via set_token_ml_manager()
        self._sentiment_analyser = None  # Set via set_sentiment_analyser()

    # ── Lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="engine-heartbeat"
        )
        self._heartbeat_thread.start()
        self._sync_thread = threading.Thread(
            target=self._sync_loop, daemon=True, name="engine-sync"
        )
        self._sync_thread.start()
        logger.info(f"TradingEngine started – mode: {self._mode}")

    def stop(self) -> None:
        self._running = False
        logger.info("TradingEngine stopped.")

    # ── Mode management ────────────────────────────────────────────────
    @property
    def mode(self) -> EngineMode:
        return self._mode

    def set_mode(self, mode: EngineMode) -> None:
        old = self._mode
        self._mode = mode
        logger.info(f"Engine mode changed: {old} → {mode}")
        self._emit("mode_change", {"old": old, "new": mode})

    def pause(self) -> None:
        self.set_mode(EngineMode.PAUSED)

    def resume(self) -> None:
        self.set_mode(EngineMode(self._settings.trading.mode))

    # ── Symbol management ──────────────────────────────────────────────
    def add_symbol(self, symbol: str) -> None:
        if symbol in self._active_symbols:
            return
        self._active_symbols.add(symbol)
        self._client.subscribe_kline(symbol, "1m", self._on_kline)
        self._client.subscribe_depth(symbol, self._on_depth)
        self._client.subscribe_ticker(symbol, self._on_ticker)
        logger.debug(f"Subscribed to {symbol}")

    def remove_symbol(self, symbol: str) -> None:
        self._active_symbols.discard(symbol)

    # ── Pluggable service injection ────────────────────────────────────
    def set_whale_watcher(self, watcher) -> None:
        self._whale_watcher = watcher
        watcher.on_event(self._on_whale_event)

    def set_token_ml_manager(self, manager) -> None:
        self._token_ml_manager = manager
        manager.on_signal(self._on_token_signal)

    def set_sentiment_analyser(self, analyser) -> None:
        self._sentiment_analyser = analyser

    # ── Paper trading ──────────────────────────────────────────────────
    def enable_paper_trading(self, initial_capital: float = 10_000.0) -> None:
        self._paper_capital = initial_capital
        self._paper_positions.clear()
        self._paper_trades.clear()
        self.set_mode(EngineMode.PAPER)
        logger.info(f"Paper trading enabled – virtual capital: ${initial_capital:,.2f}")

    def paper_buy(self, symbol: str, price: float, qty: float, confidence: float) -> dict:
        cost = price * qty
        if cost > self._paper_capital:
            qty = self._paper_capital * 0.95 / price
            cost = price * qty
        self._paper_capital -= cost * 1.001  # fee simulation
        self._paper_positions[symbol] = {"qty": qty, "entry_price": price, "side": "BUY"}
        trade = {"symbol": symbol, "side": "BUY", "price": price, "qty": qty,
                 "time": time.time(), "paper": True, "confidence": confidence}
        self._paper_trades.append(trade)
        logger.info(f"[PAPER] BUY {symbol} {qty:.6f} @ {price:.4f} | capital: ${self._paper_capital:,.2f}")
        self._emit("trade", trade)
        return trade

    def paper_sell(self, symbol: str, price: float) -> dict:
        pos = self._paper_positions.pop(symbol, None)
        if not pos:
            return {}
        qty = pos["qty"]
        proceeds = price * qty * 0.999  # fee simulation
        pnl = proceeds - pos["entry_price"] * qty
        self._paper_capital += proceeds
        trade = {"symbol": symbol, "side": "SELL", "price": price, "qty": qty,
                 "pnl": pnl, "time": time.time(), "paper": True}
        self._paper_trades.append(trade)
        self._metrics["pnl_today"] += pnl
        logger.info(f"[PAPER] SELL {symbol} @ {price:.4f} | PnL: {pnl:+.4f} | capital: ${self._paper_capital:,.2f}")
        self._emit("trade", trade)
        return trade

    @property
    def paper_capital(self) -> float:
        return self._paper_capital

    @property
    def paper_positions(self) -> dict:
        return dict(self._paper_positions)

    @property
    def paper_trades(self) -> list:
        return list(self._paper_trades)

    # ── Whale + token signal handlers ─────────────────────────────────
    def _on_whale_event(self, event) -> None:
        """Receive whale event and optionally act on it."""
        self._emit("whale", event)
        if self._mode not in (EngineMode.AUTO, EngineMode.PAPER):
            return
        try:
            signal = None
            if hasattr(self._whale_watcher, "get_whale_signal") and event.whale_id:
                sig = self._whale_watcher.get_whale_signal(
                    event.symbol, event.event_type, event.whale_id
                )
                if sig.get("signal") in ("BUY", "SELL") and sig.get("confidence", 0) >= 0.6:
                    signal = sig
            if signal:
                logger.info(f"Whale signal: {signal} for {event.symbol}")
                self.on_ml_signal({
                    "symbol": event.symbol,
                    "action": signal["signal"],
                    "confidence": signal["confidence"],
                    "source": "whale",
                })
        except Exception as exc:
            logger.debug(f"Whale signal processing error: {exc}")

    def _on_token_signal(self, signal: dict) -> None:
        """Receive per-token model signal."""
        self._emit("token_signal", signal)
        if self._mode not in (EngineMode.AUTO, EngineMode.PAPER):
            return
        if signal.get("confidence", 0) >= 0.65 and signal.get("signal") in ("BUY", "SELL"):
            self.on_ml_signal({
                "symbol": signal.get("symbol", ""),
                "action": signal["signal"],
                "confidence": signal["confidence"],
                "source": "token_model",
            })

    # ── ML Signal handling ─────────────────────────────────────────────
    def on_ml_signal(self, signal: dict) -> None:
        """Called by ML predictor with a new signal dict."""
        self._metrics["signals_processed"] += 1
        self._emit("signal", signal)

        if self._mode == EngineMode.PAPER:
            # Route to paper trading simulation
            symbol = signal.get("symbol", "")
            side   = signal.get("action", "")
            price  = float(signal.get("price", 0))
            conf   = signal.get("confidence", 0.0)
            if side == "BUY" and symbol not in self._paper_positions and price > 0:
                qty = self._paper_capital * 0.95 / price
                self.paper_buy(symbol, price, qty, conf)
            elif side == "SELL" and symbol in self._paper_positions and price > 0:
                self.paper_sell(symbol, price)
            return

        if self._mode not in (EngineMode.AUTO, EngineMode.HYBRID):
            return

        symbol = signal.get("symbol", "")
        side = signal.get("action", "")
        confidence = signal.get("confidence", 0.0)
        price = Decimal(str(signal.get("price", 0)))

        if side not in ("BUY", "SELL") or price <= 0:
            return

        portfolio = self._portfolio.get_snapshot()
        portfolio_value = portfolio.get("total_usdt", 0) if isinstance(portfolio, dict) else float(portfolio.total_usdt)
        portfolio_value = Decimal(str(portfolio_value))

        stop_loss = self._risk.calculate_stop_loss(price, side)
        take_profit = self._risk.calculate_take_profit(price, side)
        qty = self._risk.calculate_position_size(portfolio_value, price, stop_loss)

        proposal = TradeProposal(
            symbol=symbol,
            side=side,
            entry_price=price,
            quantity=qty,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
        )

        metrics = RiskMetrics(
            portfolio_value=portfolio_value,
            open_trades=len(self._orders.get_open_orders()),
        )
        proposal = self._risk.evaluate(proposal, metrics)

        if not proposal.approved:
            self._metrics["orders_rejected"] += 1
            logger.debug(f"Signal rejected [{symbol}]: {proposal.reject_reason}")
            return

        order = self._orders.place_limit_order(
            symbol=symbol,
            side=side,
            quantity=qty,
            price=price,
            user_id=self._user_id,
            stop_price=stop_loss,
            is_automated=True,
            ml_signal=side,
            ml_confidence=confidence,
        )
        if order:
            self._metrics["trades_today"] += 1
            self._emit("trade", order)

    # ── Manual trading ─────────────────────────────────────────────────
    def manual_buy(self, symbol: str, quantity: Decimal, price: Decimal) -> Optional[dict]:
        return self._orders.place_limit_order(
            symbol=symbol, side="BUY", quantity=quantity, price=price,
            user_id=self._user_id, is_automated=False,
        )

    def manual_sell(self, symbol: str, quantity: Decimal, price: Decimal) -> Optional[dict]:
        return self._orders.place_limit_order(
            symbol=symbol, side="SELL", quantity=quantity, price=price,
            user_id=self._user_id, is_automated=False,
        )

    def manual_cancel(self, symbol: str, order_id: str) -> bool:
        return self._orders.cancel_order(symbol, order_id)

    # ── WebSocket handlers ─────────────────────────────────────────────
    def _on_kline(self, data: dict) -> None:
        k = data.get("k", {})
        if k.get("x"):   # candle closed
            symbol = k.get("s", "")
            self._emit("signal", {
                "type": "candle_close",
                "symbol": symbol,
                "data": k,
            })

    def _on_depth(self, data: dict) -> None:
        symbol = data.get("s", "")
        if symbol:
            self._redis.cache_orderbook(symbol, data)

    def _on_ticker(self, data: dict) -> None:
        symbol = data.get("s", "")
        if symbol:
            self._redis.cache_ticker(symbol, {
                "price": data.get("c", 0),
                "change_pct": data.get("P", 0),
                "volume": data.get("v", 0),
            })

    # ── Background loops ───────────────────────────────────────────────
    def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                self._portfolio.refresh()
                self._emit("heartbeat", {
                    "mode": self._mode,
                    "metrics": self._metrics,
                    "active_symbols": list(self._active_symbols),
                })
            except Exception as exc:
                logger.error(f"Heartbeat error: {exc}")
            time.sleep(10)

    def _sync_loop(self) -> None:
        while self._running:
            try:
                self._orders.sync_orders()
            except Exception as exc:
                logger.error(f"Sync error: {exc}")
            time.sleep(30)

    # ── Event emission ─────────────────────────────────────────────────
    def on(self, event: str, callback: Callable) -> None:
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _emit(self, event: str, data) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception as exc:
                logger.error(f"Callback error [{event}]: {exc}")

    @property
    def metrics(self) -> dict:
        return self._metrics.copy()
