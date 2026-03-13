"""
Gap Detector ML — Discovers price gaps in OHLC charts and generates trading signals.

A "gap" occurs when a candle's open price is significantly different from the
prior candle's close price, creating a visible gap on the chart.

Gap Types and Trading Logic:
  GAP DOWN — Current open < prior close by ≥ gap_threshold %
             → Action: BUY (mean-reversion fill trade)
             → Entry: current market price (discounted open)
             → Target: prior close price (the gap fill level — ABOVE entry)
             → Stop-loss: ATR-based below the gap open
             → Edge: buying cheap, target is above entry → positive R:R

  GAP UP   — Current open > prior close by ≥ gap_threshold %
             → Action: WATCH (monitor only — gap fill requires a short)
             → No buy entry on spot platform
             → Alert only: gap up detected, watch for reversal/fill

Algorithm (computed on 1d and 4h klines, last 90 bars):

  gap_pct          : (open[i] - close[i-1]) / close[i-1] × 100
  gap_size_score   : min(1.0, |gap_pct| / (gap_threshold × 5))
  fill_probability : weighted score 0–1 based on:
      • Historical fill rate for this symbol (from prior gaps in window)
      • Volume ratio: low gap-day volume → higher fill probability
      • Trend alignment: gap against trend → higher fill probability
      • Gap age: fresh gaps (0–3 bars old) score highest
      • Gap size: smaller gaps fill more often
  gap_score        : fill_probability × gap_size_score × recency_weight

Gap States:
  OPEN    — gap detected, not yet filled
  FILLED  — price has returned to fill the gap level
  PARTIAL — price moved ≥ 50% toward the gap fill
  STALE   — gap is > max_age_bars old without filling

Scan Timeframes:
  • 1d  (daily)  — major institutional gaps, scanned every 60 min
  • 4h           — intraday gaps, scanned every 15 min

Results:
  - Stored in _results keyed by (symbol, timeframe, gap_bar_index)
  - Exposed via get_gap_ups(), get_gap_downs(), get_all_open()
  - Callbacks fired for new GAP DOWN signals (BUY action)
  - Callbacks fired for new GAP UP signals (WATCH action) — broadcast to ML pipeline
  - get_gap_up_watch_symbols() returns current set of symbols with open gap-up events
  - Intel log entries for all notable gaps

Refresh: SCAN_INTERVAL_SEC (default 900 s / 15 min).
Scans HIGH + MEDIUM priority pairs.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import numpy as np
from loguru import logger
from utils.logger import get_intel_logger


# ── Configuration ──────────────────────────────────────────────────────────────
SCAN_INTERVAL_SEC  = 900      # 15-minute scan cycle
LOOKBACK_BARS      = 90       # How many bars to scan for gaps
MIN_BARS           = 10       # Minimum bars needed
GAP_THRESHOLD_PCT  = 0.5      # Minimum gap size to register (%)
MAX_AGE_BARS       = 30       # Maximum bar age before marking STALE
FILL_SCORE_MIN     = 0.35     # Minimum fill probability to show in results

# Timeframes to scan
TIMEFRAMES = ["1d", "4h"]

# Cache TTL per timeframe (seconds)
CACHE_TTL = {"1d": 3600, "4h": 900, "1h": 300, "15m": 120}


@dataclass
class GapResult:
    """
    A single detected price gap for one symbol on one timeframe.
    """
    symbol:           str
    timeframe:        str            # "1d" | "4h"
    gap_type:         str            # "UP" | "DOWN"
    state:            str            # "OPEN" | "FILLED" | "PARTIAL" | "STALE"
    action:           str            # "BUY" | "WATCH"

    gap_pct:          float          # Gap magnitude % (signed: positive=up, negative=down)
    gap_open:         float          # Open price of the gap candle
    gap_close_prev:   float          # Close price of the candle before the gap

    fill_target:      float          # Price level that would fill the gap (= prior close)
    fill_probability: float          # ML-estimated probability of fill 0–1
    gap_score:        float          # Overall signal confidence 0–1

    last_price:       float = 0.0
    distance_to_fill_pct: float = 0.0   # % move needed to fill gap from current price
    fill_progress_pct: float = 0.0      # How much of the gap has been filled (%)

    age_bars:         int   = 0       # How many bars ago the gap occurred
    volume_ratio:     float = 0.0     # Gap-bar volume / 20-bar avg volume
    rsi:              float = 50.0

    bars_analysed:    int   = 0
    note:             str   = ""
    gap_id:           str   = ""      # Unique identifier: symbol+tf+index
    updated_at:       str   = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def type_emoji(self) -> str:
        if self.gap_type == "UP":
            return "↑"
        return "↓"

    @property
    def state_emoji(self) -> str:
        return {
            "OPEN":    "⬤",
            "FILLED":  "✓",
            "PARTIAL": "◑",
            "STALE":   "✗",
        }.get(self.state, "?")

    @property
    def action_color(self) -> str:
        """CSS color for action badge."""
        if self.action == "BUY":
            return "#00CC66"
        return "#FFD700"  # WATCH = gold


class GapDetector:
    """
    ML-powered price gap detector.

    Scans all HIGH + MEDIUM priority pairs on daily and 4h timeframes.
    For each gap found:
      - GAP UP  → BUY signal (buy current price, target = gap fill level)
      - GAP DOWN → WATCH signal (no trade, monitor for reversal)

    Usage::

        detector = GapDetector(binance_client=client, pair_scanner=pair_scanner)
        detector.on_gap_up(my_callback)   # called for new BUY signals
        detector.start()
        buys = detector.get_gap_ups()
    """

    def __init__(
        self,
        binance_client=None,
        pair_scanner=None,
    ) -> None:
        self._client  = binance_client
        self._pairs   = pair_scanner
        self._intel   = get_intel_logger()
        self._lock    = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Results keyed by gap_id (symbol+tf+bar_index)
        self._results: dict[str, GapResult] = {}

        # Callbacks for gap-up (BUY) signals
        self._gap_up_callbacks:   list[Callable[[list[GapResult]], None]] = []
        self._gap_down_callbacks: list[Callable[[list[GapResult]], None]] = []

        # Dedicated callbacks for GAP UP / WATCH signals — broadcast to ML pipeline
        self._watch_callbacks: list[Callable[[list[GapResult]], None]] = []

        # Set of symbols currently carrying an OPEN gap-up event (queried by other tools)
        self._gap_up_watch_symbols: set[str] = set()

        # Kline cache: (symbol, interval) → {"data": list, "ts": float}
        self._cache: dict[tuple[str, str], dict] = {}

        # Track last seen gaps per symbol+tf to detect new ones
        self._prev_gap_ids: set[str] = set()

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_gap_up(self, cb: Callable[[list[GapResult]], None]) -> None:
        """Register callback — called with new GAP UP (BUY) results after each scan."""
        self._gap_up_callbacks.append(cb)

    def on_gap_down(self, cb: Callable[[list[GapResult]], None]) -> None:
        """Register callback — called with new GAP DOWN (WATCH) results after each scan."""
        self._gap_down_callbacks.append(cb)

    def on_gap_up_watch(self, cb: Callable[[list[GapResult]], None]) -> None:
        """
        Register callback — called with new GAP UP (WATCH) results after each scan.

        Use this to broadcast gap-up symbols to other ML tools so they increase
        their attention on those symbols (elevated monitoring mode).

        Callback receives a list of GapResult with gap_type=="UP", action=="WATCH".
        """
        self._watch_callbacks.append(cb)

    def get_gap_up_watch_symbols(self) -> set[str]:
        """
        Return the set of symbols that currently have an OPEN gap-up event.
        Other ML tools can query this to decide whether to apply elevated attention.
        """
        with self._lock:
            return set(self._gap_up_watch_symbols)

    def get_all_open(self) -> list[GapResult]:
        """Return all OPEN gaps sorted by score descending."""
        with self._lock:
            return sorted(
                [r for r in self._results.values() if r.state == "OPEN"],
                key=lambda r: -r.gap_score,
            )

    def get_gap_ups(self, state: str = "OPEN") -> list[GapResult]:
        """Return GAP UP results (BUY signals), optionally filtered by state."""
        with self._lock:
            results = [r for r in self._results.values() if r.gap_type == "UP"]
            if state:
                results = [r for r in results if r.state == state]
            return sorted(results, key=lambda r: -r.gap_score)

    def get_gap_downs(self, state: str = "OPEN") -> list[GapResult]:
        """Return GAP DOWN results (WATCH signals), optionally filtered by state."""
        with self._lock:
            results = [r for r in self._results.values() if r.gap_type == "DOWN"]
            if state:
                results = [r for r in results if r.state == state]
            return sorted(results, key=lambda r: -r.gap_score)

    def get_all(self) -> list[GapResult]:
        """Return all gap results sorted by score descending."""
        with self._lock:
            return sorted(self._results.values(), key=lambda r: -r.gap_score)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="gap-detector"
        )
        self._thread.start()
        self._intel.ml("GapDetector",
                       "Started — scanning for gap up / gap down patterns on 1d + 4h")

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(15)  # brief startup delay for pair scanner to warm up
        while self._running:
            t0 = time.monotonic()
            try:
                self._scan()
            except Exception as exc:
                logger.warning(f"GapDetector error: {exc!r}")
            elapsed = time.monotonic() - t0
            time.sleep(max(1.0, SCAN_INTERVAL_SEC - elapsed))

    def _scan(self) -> None:
        """Scan HIGH + MEDIUM pairs on all configured timeframes."""
        candidates: list[str] = []

        if self._pairs:
            high   = self._pairs.get_pairs_by_priority("HIGH")
            medium = self._pairs.get_pairs_by_priority("MEDIUM")
            candidates = [p.symbol for p in (high + medium)]
        else:
            candidates = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
                "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
                "MATICUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "NEARUSDT",
            ]

        new_results: dict[str, GapResult] = {}
        new_gap_ups:   list[GapResult] = []
        new_gap_downs: list[GapResult] = []
        new_ids: set[str] = set()

        for sym in candidates:
            if not self._running:
                break
            for tf in TIMEFRAMES:
                try:
                    gaps = self._analyze(sym, tf)
                    for gap in gaps:
                        new_results[gap.gap_id] = gap
                        new_ids.add(gap.gap_id)
                        # Detect newly discovered gaps (not seen last scan)
                        if gap.gap_id not in self._prev_gap_ids and gap.state == "OPEN":
                            if gap.gap_type == "UP":
                                new_gap_ups.append(gap)    # UP = WATCH signal
                            else:
                                new_gap_downs.append(gap)  # DOWN = BUY signal
                except Exception as exc:
                    logger.debug(f"GapDetector: {sym}/{tf} failed: {exc!r}")

        # Refresh the gap-up watch symbol set (all OPEN gap-up symbols)
        watch_syms = {r.symbol for r in new_results.values()
                      if r.gap_type == "UP" and r.state == "OPEN"}

        with self._lock:
            self._results.clear()
            self._results.update(new_results)
            self._gap_up_watch_symbols = watch_syms

        self._prev_gap_ids = new_ids

        up_open   = sum(1 for r in new_results.values() if r.gap_type == "UP"   and r.state == "OPEN")
        down_open = sum(1 for r in new_results.values() if r.gap_type == "DOWN" and r.state == "OPEN")
        self._intel.ml(
            "GapDetector",
            f"Scan complete — {len(new_results)} gaps found  "
            f"GAP_DOWN(BUY)={down_open}  GAP_UP(WATCH)={up_open}"
        )

        # Fire callbacks for new signals
        if new_gap_ups:
            sorted_ups = sorted(new_gap_ups, key=lambda r: -r.gap_score)
            for cb in self._gap_up_callbacks:
                try:
                    cb(sorted_ups)
                except Exception as exc:
                    logger.warning(f"GapDetector gap_up callback error: {exc!r}")

        if new_gap_downs:
            sorted_downs = sorted(new_gap_downs, key=lambda r: -r.gap_score)
            for cb in self._gap_down_callbacks:
                try:
                    cb(sorted_downs)
                except Exception as exc:
                    logger.warning(f"GapDetector gap_down callback error: {exc!r}")

            # Fire dedicated watch callbacks so other ML tools can elevate attention
            for cb in self._watch_callbacks:
                try:
                    cb(sorted_downs)
                except Exception as exc:
                    logger.warning(f"GapDetector watch callback error: {exc!r}")

    # ── Per-symbol / per-timeframe analysis ────────────────────────────────────

    def _analyze(self, symbol: str, timeframe: str) -> list[GapResult]:
        """Detect all significant gaps in the kline series for one symbol/timeframe."""
        klines = self._fetch_klines(symbol, timeframe, LOOKBACK_BARS + 5)
        if not klines or len(klines) < MIN_BARS:
            return []

        opens   = np.array([float(k[1]) for k in klines], dtype=float)
        highs   = np.array([float(k[2]) for k in klines], dtype=float)
        lows    = np.array([float(k[3]) for k in klines], dtype=float)
        closes  = np.array([float(k[4]) for k in klines], dtype=float)
        volumes = np.array([float(k[5]) for k in klines], dtype=float)

        n = len(closes)
        last_price = float(closes[-1])

        # ── Volume baseline ────────────────────────────────────────────────────
        vol_baseline = float(np.mean(volumes[:-1])) if n > 1 else 1.0
        if vol_baseline < 1e-12:
            vol_baseline = 1.0

        # ── RSI (14) on closes ─────────────────────────────────────────────────
        rsi_val = self._rsi(closes, 14)

        # ── Historical gap fill rate (used in fill_probability) ────────────────
        hist_fill_rate = self._compute_historical_fill_rate(
            opens, highs, lows, closes, GAP_THRESHOLD_PCT
        )

        # ── Trend: simple linear slope of last 20 closes (normalised) ─────────
        trend_slope = self._trend_slope(closes[-20:])   # +ve = uptrend, -ve = downtrend

        results: list[GapResult] = []

        # Scan from the most recent bar backward; stop at MAX_AGE_BARS
        for i in range(n - 1, 0, -1):
            age = (n - 1) - i    # 0 = current bar, 1 = 1 bar ago, …
            if age > MAX_AGE_BARS:
                break

            prev_close = closes[i - 1]
            curr_open  = opens[i]

            if prev_close < 1e-12:
                continue

            gap_pct = (curr_open - prev_close) / prev_close * 100.0

            if abs(gap_pct) < GAP_THRESHOLD_PCT:
                continue   # not a significant gap

            # ── Gap type ──────────────────────────────────────────────────────
            gap_type   = "UP" if gap_pct > 0 else "DOWN"
            action     = "BUY" if gap_type == "DOWN" else "WATCH"
            fill_target = prev_close   # gap fills when price returns to prev_close

            # ── Gap state (has it filled?) ─────────────────────────────────────
            # Look at all candles AFTER the gap candle
            post_lows  = lows[i:]    # includes gap candle itself
            post_highs = highs[i:]

            if gap_type == "UP":
                # Gap up fills when any post-gap candle low ≤ fill_target
                filled    = bool(np.any(post_lows <= fill_target))
                # Partial: low came within 50% of the gap distance
                gap_dist  = curr_open - prev_close
                closest   = float(np.min(post_lows)) if len(post_lows) else curr_open
                fill_prog = max(0.0, min(1.0, (curr_open - closest) / gap_dist)) if gap_dist > 1e-12 else 0.0
                partial   = fill_prog >= 0.5 and not filled
            else:
                # Gap down fills when any post-gap candle high ≥ fill_target
                filled    = bool(np.any(post_highs >= fill_target))
                gap_dist  = prev_close - curr_open   # positive
                highest   = float(np.max(post_highs)) if len(post_highs) else curr_open
                fill_prog = max(0.0, min(1.0, (highest - curr_open) / gap_dist)) if gap_dist > 1e-12 else 0.0
                partial   = fill_prog >= 0.5 and not filled

            if filled:
                state = "FILLED"
            elif partial:
                state = "PARTIAL"
            elif age >= MAX_AGE_BARS:
                state = "STALE"
            else:
                state = "OPEN"

            # ── Volume ratio on gap bar ────────────────────────────────────────
            vol_ratio = float(volumes[i]) / vol_baseline

            # ── Fill probability (ML score) ────────────────────────────────────
            fill_prob = self._fill_probability(
                gap_pct        = gap_pct,
                gap_type       = gap_type,
                age_bars       = age,
                vol_ratio      = vol_ratio,
                trend_slope    = trend_slope,
                hist_fill_rate = hist_fill_rate,
                rsi            = rsi_val,
            )

            # ── Gap size score ─────────────────────────────────────────────────
            gap_size_score = min(1.0, abs(gap_pct) / (GAP_THRESHOLD_PCT * 5))

            # ── Recency weight (fresher = higher) ─────────────────────────────
            recency = max(0.1, 1.0 - (age / MAX_AGE_BARS) * 0.7)

            # ── Overall gap score ──────────────────────────────────────────────
            gap_score = round(fill_prob * 0.55 + gap_size_score * 0.30 + recency * 0.15, 4)

            # Skip low-quality stale/filled gaps
            if state in ("FILLED", "STALE") and gap_score < FILL_SCORE_MIN:
                continue

            # ── Distance to fill from current price ───────────────────────────
            if last_price > 1e-12:
                dist_to_fill = (fill_target - last_price) / last_price * 100.0
            else:
                dist_to_fill = 0.0

            gap_id = f"{symbol}_{timeframe}_{i}"

            result = GapResult(
                symbol            = symbol,
                timeframe         = timeframe,
                gap_type          = gap_type,
                state             = state,
                action            = action,
                gap_pct           = round(gap_pct, 4),
                gap_open          = round(float(curr_open), 8),
                gap_close_prev    = round(float(prev_close), 8),
                fill_target       = round(float(fill_target), 8),
                fill_probability  = round(fill_prob, 4),
                gap_score         = gap_score,
                last_price        = round(last_price, 8),
                distance_to_fill_pct = round(dist_to_fill, 4),
                fill_progress_pct = round(fill_prog * 100.0, 2),
                age_bars          = age,
                volume_ratio      = round(vol_ratio, 3),
                rsi               = round(rsi_val, 1),
                bars_analysed     = n,
                note              = (
                    f"Gap {'+' if gap_pct >= 0 else ''}{gap_pct:.2f}%  "
                    f"Age={age}bars  VolX={vol_ratio:.1f}  "
                    f"FillPct={fill_prog * 100:.0f}%"
                ),
                gap_id            = gap_id,
            )
            results.append(result)

        return results

    # ── Fill probability estimator ─────────────────────────────────────────────

    @staticmethod
    def _fill_probability(
        gap_pct:        float,
        gap_type:       str,
        age_bars:       int,
        vol_ratio:      float,
        trend_slope:    float,
        hist_fill_rate: float,
        rsi:            float,
    ) -> float:
        """
        Estimate the probability that this gap will fill, using a weighted
        combination of sub-scores.

        Weights:
          0.35 — historical fill rate for this symbol
          0.25 — gap size (smaller = more likely to fill)
          0.20 — counter-trend (gap against prevailing trend fills more often)
          0.10 — volume (low volume gap = more likely to fill)
          0.10 — RSI extremes (overbought after gap up → likely to reverse)
        """
        # 1. Historical fill rate (direct evidence)
        hist_score = float(np.clip(hist_fill_rate, 0.0, 1.0))

        # 2. Gap size — smaller gaps fill more reliably
        # Gaps < 1% → high fill prob; gaps > 5% → lower
        abs_gap = abs(gap_pct)
        size_score = max(0.0, min(1.0, 1.0 - (abs_gap - GAP_THRESHOLD_PCT) / 5.0))

        # 3. Counter-trend: gap against trend = more likely to fill
        if gap_type == "UP" and trend_slope < 0:
            # Gap up but downtrend → fill likely
            counter_score = min(1.0, 0.5 + abs(trend_slope) * 10)
        elif gap_type == "DOWN" and trend_slope > 0:
            # Gap down but uptrend → fill likely
            counter_score = min(1.0, 0.5 + abs(trend_slope) * 10)
        else:
            # Gap in direction of trend → less likely to fill
            counter_score = max(0.0, 0.5 - abs(trend_slope) * 5)

        # 4. Volume — high volume gap tends to hold (continuation); low volume → fill
        vol_score = max(0.0, min(1.0, 1.0 - (vol_ratio - 1.0) / 4.0))

        # 5. RSI extremes → mean reversion likely
        if gap_type == "UP":
            # RSI > 70 after gap up = overbought → likely to reverse and fill
            rsi_score = max(0.0, min(1.0, (rsi - 50.0) / 40.0))
        else:
            # RSI < 30 after gap down = oversold → likely to reverse and fill
            rsi_score = max(0.0, min(1.0, (50.0 - rsi) / 40.0))

        fill_prob = (
            0.35 * hist_score
            + 0.25 * size_score
            + 0.20 * counter_score
            + 0.10 * vol_score
            + 0.10 * rsi_score
        )
        return float(np.clip(fill_prob, 0.0, 1.0))

    # ── Historical fill rate ───────────────────────────────────────────────────

    @staticmethod
    def _compute_historical_fill_rate(
        opens:   np.ndarray,
        highs:   np.ndarray,
        lows:    np.ndarray,
        closes:  np.ndarray,
        threshold: float,
    ) -> float:
        """
        Compute the fraction of past gaps (in the given series) that eventually
        filled within the remaining bars.  Uses the full window so both old
        filled gaps and recent open gaps inform the estimate.
        """
        n = len(closes)
        total = 0
        filled = 0

        for i in range(1, n):
            gap = (opens[i] - closes[i - 1]) / closes[i - 1] * 100.0
            if abs(gap) < threshold:
                continue
            total += 1
            fill_target = closes[i - 1]
            gap_up = gap > 0

            # Check if any subsequent bar fills the gap
            for j in range(i, n):
                if gap_up and lows[j] <= fill_target:
                    filled += 1
                    break
                if not gap_up and highs[j] >= fill_target:
                    filled += 1
                    break

        if total == 0:
            return 0.65   # default: crypto gaps fill ~65% of the time historically
        return filled / total

    # ── Trend slope ───────────────────────────────────────────────────────────

    @staticmethod
    def _trend_slope(closes: np.ndarray) -> float:
        """
        Compute the normalised OLS slope of closes.
        Returns a value roughly in [-0.1, +0.1] where:
          > 0 = uptrend, < 0 = downtrend.
        """
        n = len(closes)
        if n < 2:
            return 0.0
        mean_price = float(closes.mean())
        if mean_price < 1e-12:
            return 0.0
        x  = np.arange(n, dtype=float)
        xm = x.mean()
        ym = closes.mean()
        ssxy = float(np.sum((x - xm) * (closes - ym)))
        ssxx = float(np.sum((x - xm) ** 2))
        if ssxx < 1e-12:
            return 0.0
        slope = ssxy / ssxx
        # Normalise by mean price to make scale-invariant
        return slope / mean_price

    # ── RSI ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _rsi(closes: np.ndarray, period: int = 14) -> float:
        """Wilder RSI."""
        if len(closes) < period + 1:
            return 50.0
        deltas   = np.diff(closes)
        gains    = np.where(deltas > 0, deltas, 0.0)
        losses   = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))
        for g, l in zip(gains[period:], losses[period:]):
            avg_gain = (avg_gain * (period - 1) + g) / period
            avg_loss = (avg_loss * (period - 1) + l) / period
        if avg_loss < 1e-12:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    # ── Kline cache ────────────────────────────────────────────────────────────

    def _fetch_klines(self, symbol: str, interval: str, limit: int) -> list:
        key = (symbol, interval)
        now = time.monotonic()
        ttl = CACHE_TTL.get(interval, 900)
        cached = self._cache.get(key)
        if cached and (now - cached["ts"]) < ttl:
            return cached["data"]

        data = self._fetch_api(symbol, interval, limit)
        if data:
            self._cache[key] = {"data": data, "ts": now}
        return data or (cached or {}).get("data", [])

    def _fetch_api(self, symbol: str, interval: str, limit: int) -> list:
        if not self._client:
            return self._synthetic_klines(symbol, interval, limit)
        try:
            return self._client.get_klines(symbol=symbol, interval=interval, limit=limit)
        except Exception as exc:
            logger.debug(f"GapDetector: fetch failed {symbol}/{interval}: {exc!r}")
            return self._synthetic_klines(symbol, interval, limit)

    @staticmethod
    def _synthetic_klines(symbol: str, interval: str, limit: int) -> list:
        """Generate synthetic klines with realistic gaps for demo/offline mode."""
        rng = np.random.default_rng(hash(symbol + interval) % (2 ** 31))
        price = 100.0
        now_ms = int(time.time() * 1000)

        bar_ms_map = {
            "1d": 86_400_000,
            "4h":  14_400_000,
            "1h":   3_600_000,
            "15m":    900_000,
        }
        bar_ms = bar_ms_map.get(interval, 3_600_000)

        klines = []
        for i in range(limit):
            ts = now_ms - (limit - i) * bar_ms

            # Simulate normal price movement
            price_chg = rng.normal(0, 0.012) * price
            price = max(0.001, price + price_chg)

            # Randomly inject a gap every ~15 bars
            open_price = price
            if i > 0 and i % (13 + rng.integers(0, 6)) == 0:
                gap_dir  = rng.choice([-1, 1])
                gap_size = rng.uniform(0.5, 3.5) / 100.0
                open_price = price * (1 + gap_dir * gap_size)

            high  = max(open_price, price) * (1 + abs(rng.normal(0, 0.005)))
            low   = min(open_price, price) * (1 - abs(rng.normal(0, 0.005)))
            vol   = max(0.0, rng.normal(50_000, 15_000))
            buy_v = vol * rng.uniform(0.45, 0.65)

            klines.append([
                ts,
                str(open_price),  # open
                str(high),
                str(low),
                str(price),       # close
                str(vol),
                ts + bar_ms - 1,
                str(vol * price),
                100,
                str(buy_v),
                str(buy_v * price),
                "0",
            ])
        return klines
