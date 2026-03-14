"""
FundingRateMonitor – Polls Binance perpetual futures funding rates.

Fires AlertType.FUNDING_RATE when any symbol's predicted funding rate
exceeds EXTREME_THRESHOLD (default ±0.10 %).  Maintains rolling history
so the UI can plot the rate over time.

Refresh: every 5 min (Binance funding rates settle every 8 h, but the
predicted next rate changes continuously).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import requests
from loguru import logger

from utils.logger import get_intel_logger

EXTREME_THRESHOLD = 0.0010      # ±0.10 %  (absolute)
POLL_INTERVAL_SEC = 300         # 5 min
MAX_HISTORY       = 72          # ~6 h of 5-min data-points per symbol

FAPI_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"


@dataclass
class FundingRateEvent:
    symbol:    str
    rate:      float            # e.g. 0.0015 = +0.15 %
    price:     float
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def rate_pct(self) -> float:
        return self.rate * 100

    @property
    def direction(self) -> str:
        """LONG_PAIN (longs pay shorts) or SHORT_PAIN (shorts pay longs)."""
        return "LONG_PAIN" if self.rate > 0 else "SHORT_PAIN"


class FundingRateMonitor:
    """
    Periodically fetches Binance perpetual funding rates and fires callbacks
    for extreme readings.  Also maintains a per-symbol deque for UI charting.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        threshold: float = EXTREME_THRESHOLD,
    ) -> None:
        self._symbols:   list[str]  = list(symbols or [])
        self._threshold: float      = threshold
        self._history:   dict[str, deque] = {}
        self._latest:    dict[str, FundingRateEvent] = {}
        self._callbacks: list[Callable[[FundingRateEvent], None]] = []
        self._lock       = threading.Lock()
        self._stop_evt   = threading.Event()
        self._thread:    Optional[threading.Thread] = None
        self._intel      = get_intel_logger()
        self._enabled:   bool = True

    # ── Configuration ───────────────────────────────────────────────────────

    # ── Enable / disable ────────────────────────────────────────────────────

    def enable(self) -> None:
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False

    @property
    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def add_symbol(self, symbol: str) -> None:
        with self._lock:
            if symbol not in self._symbols:
                self._symbols.append(symbol)

    def on_event(self, cb: Callable[[FundingRateEvent], None]) -> None:
        with self._lock:
            self._callbacks.append(cb)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self, symbols: list[str] | None = None) -> None:
        if symbols:
            for s in symbols:
                self.add_symbol(s)
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="FundingRateMon", daemon=True
        )
        self._thread.start()
        logger.debug("FundingRateMonitor started")

    def stop(self) -> None:
        self._stop_evt.set()

    # ── Public queries ───────────────────────────────────────────────────────

    def get_latest(self, symbol: str) -> Optional[FundingRateEvent]:
        return self._latest.get(symbol)

    def get_history(self, symbol: str) -> list[FundingRateEvent]:
        with self._lock:
            return list(self._history.get(symbol, []))

    def get_all_latest(self) -> dict[str, FundingRateEvent]:
        return dict(self._latest)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while not self._stop_evt.is_set():
            if self.is_enabled:
                try:
                    self._fetch_and_process()
                except Exception as exc:
                    logger.debug(f"FundingRateMonitor poll error: {exc}")
            self._stop_evt.wait(POLL_INTERVAL_SEC)

    def _fetch_and_process(self) -> None:
        with self._lock:
            syms = set(s.upper() for s in self._symbols)

        try:
            resp = requests.get(FAPI_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug(f"FundingRateMonitor fetch error: {exc}")
            return

        results: list[FundingRateEvent] = []
        for item in data:
            sym = item.get("symbol", "")
            if sym in syms:
                rate  = float(item.get("lastFundingRate", 0))
                price = float(item.get("markPrice", 0))
                results.append(FundingRateEvent(symbol=sym, rate=rate, price=price))

        for ev in results:
            with self._lock:
                if ev.symbol not in self._history:
                    self._history[ev.symbol] = deque(maxlen=MAX_HISTORY)
                self._history[ev.symbol].append(ev)
                self._latest[ev.symbol] = ev
                cbs = list(self._callbacks)

            if abs(ev.rate) >= self._threshold:
                self._intel.signal(
                    "FundingRate",
                    f"{ev.symbol} extreme funding: {ev.rate_pct:+.4f}% ({ev.direction})",
                    {"symbol": ev.symbol, "rate": ev.rate, "price": ev.price},
                )
                try:
                    from core.alert_manager import get_alert_manager, AlertType
                    get_alert_manager().fire(
                        AlertType.FUNDING_RATE,
                        ev.symbol,
                        f"Extreme funding: {ev.rate_pct:+.4f}% ({ev.direction})",
                        price=ev.price,
                        data={"rate": ev.rate},
                    )
                except Exception:
                    pass
                for cb in cbs:
                    try:
                        cb(ev)
                    except Exception:
                        pass
