"""
CascadeDetector – Compound liquidation cascade detector (with adaptive thresholds).

Learns per-symbol "normal" price volatility and volume-spike distributions
using Welford's online algorithm.  Thresholds self-adjust as market conditions
change so the detector stays calibrated without manual tuning.

Triggers when ALL of the following are true within PRICE_WINDOW_SEC:
  1. Price move ≥ PRICE_MOVE_PCT in absolute terms (up or down)
  2. Volume in the window ≥ VOL_SPIKE_MULTIPLIER × recent baseline

Fires CascadeEvent + AlertType.CASCADE.  One alert per symbol per 5 min.
Can be fed price + volume data either manually (via feed_*) or wired to
ticker callbacks from BinanceClient.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from loguru import logger

from utils.logger import get_intel_logger

PRICE_WINDOW_SEC      = 120     # 2-min rolling window for move
BASELINE_WINDOW_SEC   = 300     # baseline volume = preceding 3 min
THROTTLE_SEC          = 300     # one alert per symbol per 5 min
# Adaptive sigma triggers (fires when observed value > mean + N×std)
PRICE_SIGMA           = 2.0     # 2-sigma price move
VOL_SIGMA             = 2.5     # 2.5-sigma volume spike
# Hard floors (used until enough samples are collected)
PRICE_FLOOR           = 0.012   # 1.2 %
VOL_FLOOR             = 2.5     # 2.5× baseline
MIN_SAMPLES           = 30      # samples needed before adaptive kicks in


class _Welford:
    """Welford's online mean + variance."""
    def __init__(self) -> None:
        self.n = 0; self.mean = 0.0; self._M2 = 0.0

    def update(self, x: float) -> None:
        self.n += 1
        d = x - self.mean; self.mean += d / self.n
        self._M2 += d * (x - self.mean)

    @property
    def std(self) -> float:
        return math.sqrt(self._M2 / (self.n - 1)) if self.n >= 2 else 0.0

    def threshold(self, sigma: float, floor: float) -> float:
        if self.n < MIN_SAMPLES:
            return floor
        return max(floor, self.mean + sigma * self.std)


@dataclass
class CascadeEvent:
    symbol:       str
    price_change: float     # e.g. -0.025 = -2.5 %
    vol_ratio:    float     # e.g. 5.0 = 5× average
    direction:    str       # "DOWN" or "UP"
    timestamp:    datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def severity(self) -> str:
        if abs(self.price_change) >= 0.03 and self.vol_ratio >= 5:
            return "EXTREME"
        if abs(self.price_change) >= 0.02 and self.vol_ratio >= 4:
            return "HIGH"
        return "MEDIUM"


class _SymbolState:
    def __init__(self) -> None:
        self.prices:  deque = deque(maxlen=600)   # (price, ts)
        self.volumes: deque = deque(maxlen=600)   # (vol_usd, ts)

    def add_price(self, price: float, ts: float) -> None:
        self.prices.append((price, ts))

    def add_volume(self, vol_usd: float, ts: float) -> None:
        self.volumes.append((vol_usd, ts))

    def check_raw(self) -> Optional[tuple[float, float]]:
        """
        Returns (price_change_fraction, vol_ratio) if cascade conditions are
        met, otherwise None.
        """
        now  = time.time()
        cut2 = now - PRICE_WINDOW_SEC            # 2-min window start
        cut5 = now - (PRICE_WINDOW_SEC + BASELINE_WINDOW_SEC)  # baseline start

        # Prune very old data
        while self.prices and self.prices[0][1] < cut5:
            self.prices.popleft()
        while self.volumes and self.volumes[0][1] < cut5:
            self.volumes.popleft()

        recent_p = [(p, t) for p, t in self.prices if t >= cut2]
        if len(recent_p) < 5:
            return None

        if recent_p[0][0] == 0:
            return None
        pchange = (recent_p[-1][0] - recent_p[0][0]) / recent_p[0][0]
        if abs(pchange) < PRICE_MOVE_PCT:
            return None

        # Volume: recent 2-min rate vs preceding 3-min baseline rate
        recent_v   = sum(v for v, t in self.volumes if t >= cut2)
        baseline_v = sum(v for v, t in self.volumes if cut5 <= t < cut2) or 1.0
        # Normalise to per-minute rates then compare
        recent_rate   = recent_v / (PRICE_WINDOW_SEC / 60)
        baseline_rate = baseline_v / (BASELINE_WINDOW_SEC / 60)
        vol_ratio = recent_rate / (baseline_rate + 1e-10)

        if vol_ratio < VOL_SPIKE_MULTIPLIER:
            return None

        return pchange, vol_ratio


class CascadeDetector:
    """Detect liquidation cascades from live price + volume feeds."""

    def __init__(self) -> None:
        self._states:      dict[str, _SymbolState] = {}
        self._callbacks:   list[Callable[[CascadeEvent], None]] = []
        self._lock         = threading.Lock()
        self._last_alert:  dict[str, float] = {}
        self._intel        = get_intel_logger()
        self._enabled:     bool = True
        # Per-symbol adaptive learning: symbol → (_Welford price, _Welford vol)
        self._price_stats: dict[str, _Welford] = {}
        self._vol_stats:   dict[str, _Welford] = {}

    # ── Configuration ───────────────────────────────────────────────────────

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def on_event(self, cb: Callable[[CascadeEvent], None]) -> None:
        with self._lock:
            self._callbacks.append(cb)

    # ── Feeds ────────────────────────────────────────────────────────────────

    def feed_price(self, symbol: str, price: float, ts: float | None = None) -> None:
        if not self._enabled:
            return
        ts = ts or time.time()
        with self._lock:
            if symbol not in self._states:
                self._states[symbol] = _SymbolState()
            state = self._states[symbol]
        state.add_price(price, ts)
        self._evaluate(symbol, state)

    def feed_volume(self, symbol: str, vol_usd: float, ts: float | None = None) -> None:
        ts = ts or time.time()
        with self._lock:
            if symbol not in self._states:
                self._states[symbol] = _SymbolState()
            self._states[symbol].add_volume(vol_usd, ts)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _evaluate(self, symbol: str, state: _SymbolState) -> None:
        result = state.check_raw()
        if not result:
            return

        pchange, vol_ratio = result

        # Update per-symbol adaptive stats (always, even if no alert)
        with self._lock:
            if symbol not in self._price_stats:
                self._price_stats[symbol] = _Welford()
                self._vol_stats[symbol]   = _Welford()
            ps = self._price_stats[symbol]
            vs = self._vol_stats[symbol]
        ps.update(abs(pchange))
        vs.update(vol_ratio)

        # Apply adaptive thresholds
        p_thresh = ps.threshold(PRICE_SIGMA, PRICE_FLOOR)
        v_thresh = vs.threshold(VOL_SIGMA,   VOL_FLOOR)
        if abs(pchange) < p_thresh or vol_ratio < v_thresh:
            return
        now = time.time()
        if now - self._last_alert.get(symbol, 0) < THROTTLE_SEC:
            return
        self._last_alert[symbol] = now

        direction = "DOWN" if pchange < 0 else "UP"
        ev = CascadeEvent(
            symbol       = symbol,
            price_change = pchange,
            vol_ratio    = vol_ratio,
            direction    = direction,
        )
        self._intel.signal(
            "CascadeDetector",
            f"CASCADE {direction} {symbol}: {pchange:+.2%} | "
            f"{vol_ratio:.1f}× vol [{ev.severity}]",
            {"pchange": pchange, "vol_ratio": vol_ratio, "severity": ev.severity},
        )
        try:
            from core.alert_manager import get_alert_manager, AlertType
            get_alert_manager().fire(
                AlertType.CASCADE,
                symbol,
                f"Liquidation cascade {direction}: {pchange:+.2%} price  "
                f"{vol_ratio:.1f}× volume [{ev.severity}]",
                data={
                    "price_change": pchange,
                    "vol_ratio":    vol_ratio,
                    "severity":     ev.severity,
                },
            )
        except Exception:
            pass

        with self._lock:
            cbs = list(self._callbacks)
        for cb in cbs:
            try:
                cb(ev)
            except Exception:
                pass
