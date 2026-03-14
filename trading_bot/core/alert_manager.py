"""
Alert Manager – Custom Configurable Alerts.

Watches the trading system and fires user-defined alerts for:
  • BUY  – a trade entry was executed
  • SELL – a trade exit was executed
  • WIN  – closed trade in profit
  • LOSS – closed trade at a loss
  • NEW_TOKEN  – new token detected on exchange
  • NEW_HIGH   – price hits a new N-day high
  • NEW_LOW    – price hits a new N-day low
  • VOLUME_SPIKE – sudden volume surge detected
  • EARLY_PUMP   – price + volume surging together
  • WASH  – trade closed within 30 s (wash / false entry)

Alert delivery channels:
  • Toast overlay (always)
  • Intel Log (always)
  • Sound (optional, system bell)
  • Desktop notification (optional)

Usage:
    mgr = AlertManager()
    mgr.enable(AlertType.LOSS)
    mgr.enable(AlertType.NEW_HIGH)
    mgr.register_callback(my_handler)
    # Then wire to AutoTrader / MarketPulse callbacks
    auto_trader.on_cycle_result(mgr.on_cycle_result)
    pulse.on_alert(mgr.on_pulse_alert)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

from loguru import logger
from utils.logger import get_intel_logger


class AlertType(str, Enum):
    BUY           = "BUY"
    SELL          = "SELL"
    WIN           = "WIN"
    LOSS          = "LOSS"
    NEW_TOKEN     = "NEW_TOKEN"
    NEW_HIGH      = "NEW_HIGH"
    NEW_LOW       = "NEW_LOW"
    VOLUME_SPIKE  = "VOLUME_SPIKE"
    EARLY_PUMP    = "EARLY_PUMP"
    WASH          = "WASH"
    CIRCUIT_BREAK = "CIRCUIT_BREAK"
    # ── New market-watch alert types ──────────────────────────────────
    FUNDING_RATE  = "FUNDING_RATE"   # extreme perpetual funding rate
    CASCADE       = "CASCADE"        # liquidation cascade (price + vol spike)
    LEAD_LAG      = "LEAD_LAG"       # correlated pair hasn't reacted yet
    AGGRESSOR     = "AGGRESSOR"      # smart-money buy/sell pressure (OFI)


ALERT_EMOJIS: dict[AlertType, str] = {
    AlertType.BUY:           "🟢",
    AlertType.SELL:          "🔴",
    AlertType.WIN:           "✅",
    AlertType.LOSS:          "❌",
    AlertType.NEW_TOKEN:     "🆕",
    AlertType.NEW_HIGH:      "🏔️",
    AlertType.NEW_LOW:       "🕳️",
    AlertType.VOLUME_SPIKE:  "🔊",
    AlertType.EARLY_PUMP:    "🚀",
    AlertType.WASH:          "🫧",
    AlertType.CIRCUIT_BREAK: "⛔",
    AlertType.FUNDING_RATE:  "💸",
    AlertType.CASCADE:       "🌊",
    AlertType.LEAD_LAG:      "🔗",
    AlertType.AGGRESSOR:     "🦈",
}

# Minimum seconds between repeated alerts for the same (type, symbol)
ALERT_THROTTLE_SEC = 60


@dataclass
class Alert:
    alert_type: AlertType
    symbol: str
    message: str
    price: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    data: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def emoji(self) -> str:
        return ALERT_EMOJIS.get(self.alert_type, "🔔")

    @property
    def full_message(self) -> str:
        return f"{self.emoji} [{self.alert_type.value}] {self.message}"


class AlertManager:
    """
    Configurable alert dispatcher.
    Thread-safe; can be driven by AutoTrader callbacks, MarketPulse callbacks,
    or called directly.
    """

    def __init__(self) -> None:
        self._intel    = get_intel_logger()
        self._lock     = threading.Lock()
        self._enabled: set[AlertType] = set(AlertType)   # All enabled by default
        self._callbacks: list[Callable[[Alert], None]] = []
        self._throttle: dict[tuple, float] = {}   # (type, symbol) → last fired ts
        self._history:  list[Alert] = []

    # ── Configuration ─────────────────────────────────────────────────────────

    def enable(self, alert_type: AlertType) -> None:
        with self._lock:
            self._enabled.add(alert_type)

    def disable(self, alert_type: AlertType) -> None:
        with self._lock:
            self._enabled.discard(alert_type)

    def is_enabled(self, alert_type: AlertType) -> bool:
        with self._lock:
            return alert_type in self._enabled

    def set_enabled_set(self, types: set[AlertType]) -> None:
        with self._lock:
            self._enabled = set(types)

    def register_callback(self, cb: Callable[[Alert], None]) -> None:
        """Register a UI or notification callback."""
        with self._lock:
            self._callbacks.append(cb)

    def unregister_callback(self, cb: Callable) -> None:
        with self._lock:
            self._callbacks = [c for c in self._callbacks if c != cb]

    # ── Manual fire ───────────────────────────────────────────────────────────

    def fire(
        self,
        alert_type: AlertType,
        symbol: str,
        message: str,
        price: float = 0.0,
        pnl: float = 0.0,
        pnl_pct: float = 0.0,
        data: dict = None,
    ) -> None:
        with self._lock:
            if alert_type not in self._enabled:
                return
            key = (alert_type, symbol)
            now = time.time()
            if now - self._throttle.get(key, 0.0) < ALERT_THROTTLE_SEC:
                return
            self._throttle[key] = now

        alert = Alert(
            alert_type=alert_type,
            symbol=symbol,
            message=message,
            price=price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            data=data or {},
        )
        with self._lock:
            self._history.insert(0, alert)
            if len(self._history) > 500:
                self._history.pop()
            cbs = list(self._callbacks)

        self._intel.signal("AlertManager", alert.full_message)

        for cb in cbs:
            try:
                cb(alert)
            except Exception as exc:
                logger.debug(f"AlertManager callback error: {exc}")

    # ── AutoTrader integration ─────────────────────────────────────────────────

    def on_cycle_result(self, result) -> None:
        """Wire directly to AutoTrader.on_cycle_result."""
        try:
            def _get(attr, default=None):
                if hasattr(result, attr):
                    return getattr(result, attr)
                if isinstance(result, dict):
                    return result.get(attr, default)
                return default

            symbol     = _get("symbol", "UNKNOWN")
            side       = _get("side",   "BUY")
            entry      = _get("entry_price", 0.0)
            exit_p     = _get("exit_price", 0.0)
            pnl        = _get("pnl", 0.0)
            pnl_pct    = _get("pnl_pct", 0.0)
            reason     = _get("exit_reason", "")
            dur_sec    = _get("duration_sec", 999)

            # BUY / SELL entry always
            if side == "BUY":
                self.fire(AlertType.BUY, symbol,
                          f"BUY {symbol} @ {entry:.4f}", price=entry)
            else:
                self.fire(AlertType.SELL, symbol,
                          f"SELL {symbol} @ {entry:.4f}", price=entry)

            # WIN / LOSS on close
            if pnl >= 0:
                self.fire(AlertType.WIN, symbol,
                          f"WIN {symbol}: +{pnl:.4f} USDT (+{pnl_pct:.2f}%) | {reason}",
                          price=exit_p, pnl=pnl, pnl_pct=pnl_pct)
            else:
                self.fire(AlertType.LOSS, symbol,
                          f"LOSS {symbol}: {pnl:.4f} USDT ({pnl_pct:.2f}%) | {reason}",
                          price=exit_p, pnl=pnl, pnl_pct=pnl_pct)

            # WASH: closed within 30 s
            if dur_sec < 30:
                self.fire(AlertType.WASH, symbol,
                          f"WASH trade {symbol}: closed in {dur_sec:.0f}s – review entry logic",
                          price=exit_p)

        except Exception as exc:
            logger.debug(f"AlertManager.on_cycle_result error: {exc}")

    # ── MarketPulse integration ────────────────────────────────────────────────

    def on_pulse_alert(self, pulse_alert) -> None:
        """Wire directly to MarketPulse.on_alert."""
        try:
            from ml.market_pulse import (
                ALERT_VOLUME_SPIKE, ALERT_EARLY_PUMP,
                ALERT_NEW_INTEREST, ALERT_EXHAUSTION,
            )
            type_map = {
                ALERT_VOLUME_SPIKE: AlertType.VOLUME_SPIKE,
                ALERT_EARLY_PUMP:   AlertType.EARLY_PUMP,
            }
            atype = type_map.get(pulse_alert.alert_type)
            if atype:
                self.fire(atype, pulse_alert.symbol, pulse_alert.message,
                          price=pulse_alert.price,
                          data={"volume_ratio": pulse_alert.volume_ratio,
                                "rsi": pulse_alert.rsi})
        except Exception as exc:
            logger.debug(f"AlertManager.on_pulse_alert error: {exc}")

    # ── NewTokenWatcher integration ────────────────────────────────────────────

    def on_new_token(self, symbol: str, price: float = 0.0, data: dict = None) -> None:
        self.fire(AlertType.NEW_TOKEN, symbol,
                  f"🆕 New token listed: {symbol} @ {price:.6f}",
                  price=price, data=data or {})

    # ── Price level alerts ─────────────────────────────────────────────────────

    def check_price_levels(
        self, symbol: str, price: float,
        high_n_day: float = 0.0, low_n_day: float = 0.0, n: int = 30,
    ) -> None:
        """
        Call periodically with the current price and rolling high/low.
        Fires NEW_HIGH / NEW_LOW alerts if levels are breached.
        """
        if high_n_day > 0 and price >= high_n_day:
            self.fire(AlertType.NEW_HIGH, symbol,
                      f"{symbol} hit new {n}-day HIGH: {price:.4f}",
                      price=price)
        elif low_n_day > 0 and price <= low_n_day:
            self.fire(AlertType.NEW_LOW, symbol,
                      f"{symbol} hit new {n}-day LOW: {price:.4f}",
                      price=price)

    # ── Circuit breaker ────────────────────────────────────────────────────────

    def on_circuit_break(self, reason: str) -> None:
        self.fire(AlertType.CIRCUIT_BREAK, "SYSTEM",
                  f"⛔ Circuit breaker ACTIVE: {reason}")

    # ── History ───────────────────────────────────────────────────────────────

    @property
    def recent_alerts(self) -> list[Alert]:
        with self._lock:
            return list(self._history[:100])


# ── Singleton ─────────────────────────────────────────────────────────────────

_mgr: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    global _mgr
    if _mgr is None:
        _mgr = AlertManager()
    return _mgr
