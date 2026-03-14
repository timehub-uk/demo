"""
OrderFlowMonitor – Rolling aggressor ratio + Order Flow Imbalance (OFI).

Consumes aggTrade WebSocket streams per symbol via BinanceClient.subscribe_trade().
Maintains per-symbol 1-min and 5-min rolling windows.

  OFI       = cumulative (buy_vol_usd - sell_vol_usd)
  Aggressor = buy_vol_usd / (buy_vol_usd + sell_vol_usd)

Fires callbacks + AlertType.AGGRESSOR when the 1-min aggressor ratio
exceeds AGGRESSOR_HIGH (≥ 72 % buys) or AGGRESSOR_LOW (≤ 28 % buys),
indicating smart-money accumulation or distribution.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from loguru import logger

from utils.logger import get_intel_logger

AGGRESSOR_HIGH = 0.72
AGGRESSOR_LOW  = 0.28
WINDOW_SEC_1M  = 60
WINDOW_SEC_5M  = 300
BROADCAST_INTERVAL = 30      # seconds between UI snapshot broadcasts

# Internal: (price, qty_usd, is_buyer_aggressor, ts_epoch)
_Trade = tuple[float, float, bool, float]


@dataclass
class OFISnapshot:
    symbol:       str
    ts:           datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    buy_vol_1m:   float = 0.0
    sell_vol_1m:  float = 0.0
    buy_vol_5m:   float = 0.0
    sell_vol_5m:  float = 0.0
    ofi_1m:       float = 0.0
    ofi_5m:       float = 0.0
    aggressor_1m: float = 0.5
    aggressor_5m: float = 0.5

    @property
    def signal_1m(self) -> str:
        if self.aggressor_1m >= AGGRESSOR_HIGH:
            return "BUY_PRESSURE"
        if self.aggressor_1m <= AGGRESSOR_LOW:
            return "SELL_PRESSURE"
        return "NEUTRAL"

    @property
    def total_vol_1m(self) -> float:
        return self.buy_vol_1m + self.sell_vol_1m


class _SymbolFlow:
    """Per-symbol rolling trade accumulator."""

    def __init__(self) -> None:
        self._trades: deque[_Trade] = deque()

    def add_trade(
        self, price: float, qty: float, is_buyer_maker: bool, ts: float
    ) -> None:
        usd = price * qty
        # is_buyer_maker=True → buyer is passive → seller was aggressor
        is_buyer_aggressor = not is_buyer_maker
        self._trades.append((price, usd, is_buyer_aggressor, ts))

    def snapshot(self, symbol: str) -> OFISnapshot:
        now   = time.time()
        cut1  = now - WINDOW_SEC_1M
        cut5  = now - WINDOW_SEC_5M

        # Purge trades older than 5 min
        while self._trades and self._trades[0][3] < cut5:
            self._trades.popleft()

        bv1 = sv1 = bv5 = sv5 = 0.0
        for _, usd, is_buy, ts in self._trades:
            if is_buy:
                bv5 += usd
                if ts >= cut1:
                    bv1 += usd
            else:
                sv5 += usd
                if ts >= cut1:
                    sv1 += usd

        t1 = bv1 + sv1 or 1.0
        t5 = bv5 + sv5 or 1.0
        return OFISnapshot(
            symbol       = symbol,
            buy_vol_1m   = bv1,
            sell_vol_1m  = sv1,
            buy_vol_5m   = bv5,
            sell_vol_5m  = sv5,
            ofi_1m       = bv1 - sv1,
            ofi_5m       = bv5 - sv5,
            aggressor_1m = bv1 / t1,
            aggressor_5m = bv5 / t5,
        )


class OrderFlowMonitor:
    """Subscribe to aggTrade streams and compute rolling OFI + aggressor ratio."""

    def __init__(self, binance_client=None) -> None:
        self._client     = binance_client
        self._flows:     dict[str, _SymbolFlow] = {}
        self._callbacks: list[Callable[[OFISnapshot], None]] = []
        self._lock       = threading.Lock()
        self._stop_evt   = threading.Event()
        self._intel      = get_intel_logger()
        self._thread:    Optional[threading.Thread] = None
        self._enabled:   bool = True
        # Alert throttle: (symbol, signal) → last fired ts
        self._alert_ts:  dict[tuple, float] = {}

    # ── Configuration ───────────────────────────────────────────────────────

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

    def on_snapshot(self, cb: Callable[[OFISnapshot], None]) -> None:
        with self._lock:
            self._callbacks.append(cb)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self, symbols: list[str]) -> None:
        for sym in symbols:
            self._subscribe(sym)
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._broadcast_loop, name="OFIBroadcast", daemon=True
        )
        self._thread.start()
        logger.debug(f"OrderFlowMonitor started for {len(symbols)} symbols")

    def stop(self) -> None:
        self._stop_evt.set()

    # ── Feed (can be called directly if no WS client) ────────────────────────

    def feed_trade(
        self,
        symbol: str,
        price: float,
        qty: float,
        is_buyer_maker: bool,
        ts: float | None = None,
    ) -> None:
        with self._lock:
            if symbol not in self._flows:
                self._flows[symbol] = _SymbolFlow()
            self._flows[symbol].add_trade(price, qty, is_buyer_maker, ts or time.time())

    # ── Queries ──────────────────────────────────────────────────────────────

    def get_snapshot(self, symbol: str) -> Optional[OFISnapshot]:
        with self._lock:
            flow = self._flows.get(symbol)
        if flow is None:
            return None
        return flow.snapshot(symbol)

    def get_all_snapshots(self) -> list[OFISnapshot]:
        with self._lock:
            items = list(self._flows.items())
        return [f.snapshot(sym) for sym, f in items]

    # ── Internal ─────────────────────────────────────────────────────────────

    def _subscribe(self, symbol: str) -> None:
        with self._lock:
            if symbol not in self._flows:
                self._flows[symbol] = _SymbolFlow()

        if not self._client:
            return

        def _on_trade(msg):
            try:
                price = float(msg.get("p", 0))
                qty   = float(msg.get("q", 0))
                ibm   = bool(msg.get("m", False))
                ts    = float(msg.get("T", time.time() * 1000)) / 1000
                self.feed_trade(symbol, price, qty, ibm, ts)
            except Exception:
                pass

        try:
            self._client.subscribe_trade(symbol, _on_trade)
        except Exception as exc:
            logger.debug(f"OrderFlowMonitor subscribe_trade {symbol}: {exc}")

    def _broadcast_loop(self) -> None:
        """Every BROADCAST_INTERVAL s: snapshot all symbols, dispatch, alert."""
        while not self._stop_evt.is_set():
            if not self.is_enabled:
                self._stop_evt.wait(BROADCAST_INTERVAL)
                continue
            try:
                snaps = self.get_all_snapshots()
                with self._lock:
                    cbs = list(self._callbacks)

                for snap in snaps:
                    for cb in cbs:
                        try:
                            cb(snap)
                        except Exception:
                            pass

                    sig = snap.signal_1m
                    if sig != "NEUTRAL":
                        key = (snap.symbol, sig)
                        now = time.time()
                        if now - self._alert_ts.get(key, 0) >= 300:
                            self._alert_ts[key] = now
                            direction = "buying" if sig == "BUY_PRESSURE" else "selling"
                            try:
                                from core.alert_manager import get_alert_manager, AlertType
                                get_alert_manager().fire(
                                    AlertType.AGGRESSOR,
                                    snap.symbol,
                                    f"Smart money {direction}: "
                                    f"{snap.aggressor_1m:.0%} aggressor (1m) "
                                    f"OFI={snap.ofi_1m:+,.0f} USD",
                                    data={
                                        "aggressor_1m": snap.aggressor_1m,
                                        "ofi_1m": snap.ofi_1m,
                                        "total_vol_1m": snap.total_vol_1m,
                                    },
                                )
                            except Exception:
                                pass

            except Exception as exc:
                logger.debug(f"OFI broadcast error: {exc}")
            self._stop_evt.wait(BROADCAST_INTERVAL)
