"""
CorrelationEngine – Lead/lag divergence detector for correlated crypto pairs.

Tracks rolling price returns for each configured pair.  When a leader moves
more than its learned "typical" move (adaptive threshold using Welford's online
algorithm) but its correlated follower hasn't reacted within LAG_WINDOW_SEC,
fires a LeadLagEvent + AlertType.LEAD_LAG.

Adaptive thresholds:
  Each (leader, follower) pair maintains a rolling mean and standard deviation
  of the leader's absolute move size.  An alert fires only when the current
  move exceeds  max(MOVE_MIN, mean + SIGMA_TRIGGER * std).  This prevents
  false positives during normally volatile conditions and auto-adjusts as the
  market regime shifts.

Default monitored pairs (leader → follower):
    BTC → ETH, BNB, SOL, XRP
    ETH → BNB
"""

from __future__ import annotations

import math
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from loguru import logger

from utils.logger import get_intel_logger

MOVE_MIN       = 0.004      # absolute floor: never alert for < 0.4 % move
SIGMA_TRIGGER  = 1.5        # alert when move > mean + 1.5 × std of learned moves
LAG_WINDOW_SEC = 45         # follower must react within this window
REACTION_RATIO = 0.5        # follower needs ≥ 50% of leader's move to "count"
CORR_MIN       = 0.50       # min Pearson r to treat pair as correlated
THROTTLE_SEC   = 300        # min gap between same-pair alerts
MAX_PRICE_HIST = 300
MIN_SAMPLES    = 20         # minimum samples before adaptive threshold is used


class _WelfordStats:
    """Online mean + variance via Welford's algorithm."""

    def __init__(self) -> None:
        self.n    = 0
        self.mean = 0.0
        self._M2  = 0.0    # sum of squared deviations

    def update(self, value: float) -> None:
        self.n    += 1
        delta      = value - self.mean
        self.mean += delta / self.n
        self._M2  += delta * (value - self.mean)

    @property
    def std(self) -> float:
        if self.n < 2:
            return 0.0
        return math.sqrt(self._M2 / (self.n - 1))

    @property
    def threshold(self) -> float:
        """Returns learned adaptive threshold, or MOVE_MIN if not enough data."""
        if self.n < MIN_SAMPLES:
            return 0.008   # fall back to original 0.8 % hard-coded threshold
        return max(MOVE_MIN, self.mean + SIGMA_TRIGGER * self.std)


@dataclass
class LeadLagEvent:
    leader:        str
    follower:      str
    leader_move:   float    # e.g. +0.012 = +1.2 %
    expected_move: str      # "UP" or "DOWN"
    correlation:   float
    timestamp:     datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class CorrelationEngine:
    """Detect lead/lag opportunities across correlated crypto pairs."""

    DEFAULT_PAIRS: list[tuple[str, str]] = [
        ("BTCUSDT", "ETHUSDT"),
        ("BTCUSDT", "BNBUSDT"),
        ("BTCUSDT", "SOLUSDT"),
        ("BTCUSDT", "XRPUSDT"),
        ("ETHUSDT", "BNBUSDT"),
    ]

    def __init__(self, pairs: list[tuple[str, str]] | None = None) -> None:
        self._pairs:      list[tuple[str, str]] = list(pairs or self.DEFAULT_PAIRS)
        self._prices:     dict[str, deque]       = {}   # symbol → deque[(price, ts)]
        self._callbacks:  list[Callable[[LeadLagEvent], None]] = []
        self._lock        = threading.Lock()
        self._last_alert: dict[tuple, float] = {}
        self._intel       = get_intel_logger()
        self._enabled:    bool = True
        # Per-pair adaptive stats: (leader, follower) → _WelfordStats
        self._move_stats: dict[tuple, _WelfordStats] = {}

    # ── Configuration ───────────────────────────────────────────────────────

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def add_pair(self, leader: str, follower: str) -> None:
        with self._lock:
            pair = (leader, follower)
            if pair not in self._pairs:
                self._pairs.append(pair)

    def on_event(self, cb: Callable[[LeadLagEvent], None]) -> None:
        with self._lock:
            self._callbacks.append(cb)

    # ── Feed ─────────────────────────────────────────────────────────────────

    def feed_price(self, symbol: str, price: float, ts: float | None = None) -> None:
        if not self._enabled:
            return
        ts = ts or time.time()
        with self._lock:
            if symbol not in self._prices:
                self._prices[symbol] = deque(maxlen=MAX_PRICE_HIST)
            self._prices[symbol].append((price, ts))
            pairs_to_check = [(l, f) for l, f in self._pairs if l == symbol]

        for leader, follower in pairs_to_check:
            self._check_pair(leader, follower)

    # ── Queries ──────────────────────────────────────────────────────────────

    def get_correlation(self, sym_a: str, sym_b: str) -> float:
        with self._lock:
            ha = list(self._prices.get(sym_a, []))
            hb = list(self._prices.get(sym_b, []))
        return self._pearson(ha, hb)

    def get_all_correlations(self) -> dict[tuple, float]:
        result = {}
        for leader, follower in self._pairs:
            result[(leader, follower)] = self.get_correlation(leader, follower)
        return result

    # ── Internal ─────────────────────────────────────────────────────────────

    def _check_pair(self, leader: str, follower: str) -> None:
        with self._lock:
            lh = list(self._prices.get(leader, []))
            fh = list(self._prices.get(follower, []))

        if len(lh) < 5 or len(fh) < 5:
            return

        now = time.time()
        cut = now - LAG_WINDOW_SEC

        recent_l = [p for p, t in lh if t >= cut]
        if len(recent_l) < 2:
            return

        leader_move = (recent_l[-1] - recent_l[0]) / recent_l[0]

        # Update adaptive statistics for this pair
        pair = (leader, follower)
        with self._lock:
            if pair not in self._move_stats:
                self._move_stats[pair] = _WelfordStats()
            stats = self._move_stats[pair]
        # Always record the observed move magnitude (for learning)
        stats.update(abs(leader_move))

        # Alert only when move exceeds learned threshold
        if abs(leader_move) < stats.threshold:
            return

        # Has the follower already reacted?
        recent_f = [p for p, t in fh if t >= cut]
        if len(recent_f) >= 2:
            follower_move = (recent_f[-1] - recent_f[0]) / recent_f[0]
            if abs(follower_move) >= abs(leader_move) * REACTION_RATIO:
                return   # Already reacted — no opportunity

        # Throttle
        key = (leader, follower)
        if now - self._last_alert.get(key, 0) < THROTTLE_SEC:
            return
        self._last_alert[key] = now

        corr = self._pearson(lh, fh)
        if corr < CORR_MIN:
            return

        direction = "UP" if leader_move > 0 else "DOWN"
        ev = LeadLagEvent(
            leader       = leader,
            follower     = follower,
            leader_move  = leader_move,
            expected_move= direction,
            correlation  = corr,
        )
        self._intel.signal(
            "CorrelationEngine",
            f"Lead/Lag: {leader} {leader_move:+.2%} → expect {follower} {direction}  "
            f"(r={corr:.2f})",
            {"leader_move": leader_move, "direction": direction, "corr": corr},
        )
        try:
            from core.alert_manager import get_alert_manager, AlertType
            get_alert_manager().fire(
                AlertType.LEAD_LAG,
                follower,
                f"Lead/Lag: {leader} moved {leader_move:+.2%}, "
                f"{follower} not yet reacted  →  expect {direction}  (r={corr:.2f})",
                data={
                    "leader":       leader,
                    "leader_move":  leader_move,
                    "correlation":  corr,
                    "direction":    direction,
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

    @staticmethod
    def _pearson(hist_a: list, hist_b: list) -> float:
        """Pearson r on up to 30 aligned (price, ts) pairs."""
        try:
            n = min(30, len(hist_a), len(hist_b))
            if n < 5:
                return 0.0
            pa = [p for p, _ in hist_a[-n:]]
            pb = [p for p, _ in hist_b[-n:]]
            ra = [(pa[i] - pa[i - 1]) / pa[i - 1] for i in range(1, len(pa))]
            rb = [(pb[i] - pb[i - 1]) / pb[i - 1] for i in range(1, len(pb))]
            n2 = min(len(ra), len(rb))
            if n2 < 4:
                return 0.0
            ra, rb = ra[-n2:], rb[-n2:]
            mean_a = sum(ra) / n2
            mean_b = sum(rb) / n2
            cov = sum((ra[i] - mean_a) * (rb[i] - mean_b) for i in range(n2)) / n2
            std_a = statistics.stdev(ra) or 1e-10
            std_b = statistics.stdev(rb) or 1e-10
            return max(-1.0, min(1.0, cov / (std_a * std_b)))
        except Exception:
            return 0.0
