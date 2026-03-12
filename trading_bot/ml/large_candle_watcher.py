"""
Large Candle Watcher ML — Detects candles expanding rapidly in size and issues alerts.

A "large candle" event occurs when the current candle's body or range grows
significantly faster than recent history, signalling an abnormal burst of
momentum — often the early signal of a breakout, a panic sell, or a whale-driven move.

Alert Levels:
  WATCH  — candle range expanding ≥ 2.5× recent average  (early warning)
  ALERT  — candle range expanding ≥ 4.0× recent average  (strong signal)
  STRONG — candle range expanding ≥ 6.0× recent average  (extreme event)

Directional Tags:
  BULL   — close > open (bullish expansion)
  BEAR   — close < open (bearish expansion)
  MIXED  — doji-style but large wick (indecision with force)

Algorithm (per symbol, per timeframe):
  candle_range_pct[i]  = (high[i] - low[i]) / close[i-1] × 100
  avg_range_pct        = mean(candle_range_pct[-BASELINE_BARS:])
  expansion_ratio      = candle_range_pct[-1] / avg_range_pct
  body_ratio           = |close - open| / (high - low)    (0=doji, 1=full body)
  volume_ratio         = volume[-1] / mean(volume[-BASELINE_BARS:])
  candle_score         = 0.50 × expansion_sub + 0.30 × volume_sub + 0.20 × body_sub

  expansion_sub = min(1.0, (expansion_ratio - 1.0) / 9.0)
  volume_sub    = min(1.0, (volume_ratio    - 1.0) / 7.0)
  body_sub      = body_ratio

  label = "STRONG" if expansion_ratio ≥ 6.0
        | "ALERT"  if expansion_ratio ≥ 4.0
        | "WATCH"  if expansion_ratio ≥ 2.5
        | "NONE"

Timeframes scanned: 1m, 5m, 15m
Scan interval: SCAN_INTERVAL_SEC (default 60 s)
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
SCAN_INTERVAL_SEC = 60        # scan every minute
LOOKBACK_BARS     = 60        # how many bars to pull
BASELINE_BARS     = 20        # bars used to compute average candle range
MIN_BARS          = 10        # minimum bars needed for a signal

# Expansion ratio thresholds
WATCH_RATIO  = 2.5
ALERT_RATIO  = 4.0
STRONG_RATIO = 6.0

# Timeframes to scan (short intraday only — candle expansion is a short-TF concept)
TIMEFRAMES = ["1m", "5m", "15m"]

CACHE_TTL = {"1m": 30, "5m": 120, "15m": 300}


@dataclass
class LargeCandleResult:
    """A single large-candle detection for one symbol on one timeframe."""
    symbol:           str
    timeframe:        str            # "1m" | "5m" | "15m"
    label:            str            # "NONE" | "WATCH" | "ALERT" | "STRONG"
    direction:        str            # "BULL" | "BEAR" | "MIXED"

    expansion_ratio:  float          # current range / avg range
    candle_range_pct: float          # current candle range as % of prev close
    avg_range_pct:    float          # baseline average candle range %
    body_ratio:       float          # body / range  (0 = doji, 1 = full body)
    volume_ratio:     float          # current volume / baseline average volume
    candle_score:     float          # overall signal score 0–1

    open_price:       float = 0.0
    high_price:       float = 0.0
    low_price:        float = 0.0
    close_price:      float = 0.0
    last_price:       float = 0.0
    price_change_pct: float = 0.0    # % change from open → close of this candle

    note:       str = ""
    result_id:  str = ""
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def label_emoji(self) -> str:
        return {
            "STRONG": "🚨",
            "ALERT":  "🔶",
            "WATCH":  "👁",
            "NONE":   "⬛",
        }.get(self.label, "?")

    @property
    def direction_emoji(self) -> str:
        return {"BULL": "↑", "BEAR": "↓", "MIXED": "↔"}.get(self.direction, "?")


class LargeCandleWatcher:
    """
    ML-powered large candle watcher.

    Monitors all HIGH + MEDIUM pairs on 1m / 5m / 15m timeframes and fires
    alerts when a candle's size expands rapidly relative to recent history.

    Usage::

        watcher = LargeCandleWatcher(binance_client=client, pair_scanner=scanner)
        watcher.on_alert(my_callback)   # called with [LargeCandleResult, …]
        watcher.start()
        alerts = watcher.get_alerts()   # WATCH + ALERT + STRONG
    """

    def __init__(
        self,
        binance_client=None,
        pair_scanner=None,
    ) -> None:
        self._client = binance_client
        self._pairs  = pair_scanner
        self._intel  = get_intel_logger()
        self._lock   = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Results keyed by result_id (symbol+tf)
        self._results: dict[str, LargeCandleResult] = {}

        # Callbacks
        self._alert_callbacks: list[Callable[[list[LargeCandleResult]], None]] = []

        # Kline cache: (symbol, interval) → {"data": list, "ts": float}
        self._cache: dict[tuple[str, str], dict] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_alert(self, cb: Callable[[list[LargeCandleResult]], None]) -> None:
        """Register callback — called with new WATCH/ALERT/STRONG results."""
        self._alert_callbacks.append(cb)

    def get_alerts(self, min_label: str = "WATCH") -> list[LargeCandleResult]:
        """Return results at or above min_label sorted by score descending."""
        order = {"NONE": 0, "WATCH": 1, "ALERT": 2, "STRONG": 3}
        min_rank = order.get(min_label, 1)
        with self._lock:
            return sorted(
                [r for r in self._results.values() if order.get(r.label, 0) >= min_rank],
                key=lambda r: -r.candle_score,
            )

    def get_all(self) -> list[LargeCandleResult]:
        """Return all results sorted by score descending."""
        with self._lock:
            return sorted(self._results.values(), key=lambda r: -r.candle_score)

    def get_strong(self) -> list[LargeCandleResult]:
        """Return only STRONG results."""
        return self.get_alerts(min_label="STRONG")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="large-candle-watcher"
        )
        self._thread.start()
        self._intel.ml("LargeCandleWatcher",
                       "Started — scanning for rapidly expanding candles on 1m/5m/15m")

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(10)  # brief startup delay
        while self._running:
            t0 = time.monotonic()
            try:
                self._scan()
            except Exception as exc:
                logger.warning(f"LargeCandleWatcher error: {exc!r}")
            elapsed = time.monotonic() - t0
            time.sleep(max(1.0, SCAN_INTERVAL_SEC - elapsed))

    def _scan(self) -> None:
        """Scan all pairs on all configured timeframes."""
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

        new_results: dict[str, LargeCandleResult] = {}
        new_alerts:  list[LargeCandleResult] = []

        for sym in candidates:
            if not self._running:
                break
            for tf in TIMEFRAMES:
                try:
                    result = self._analyze(sym, tf)
                    if result:
                        new_results[result.result_id] = result
                        if result.label != "NONE":
                            new_alerts.append(result)
                except Exception as exc:
                    logger.debug(f"LargeCandleWatcher: {sym}/{tf} failed: {exc!r}")

        with self._lock:
            self._results.clear()
            self._results.update(new_results)

        strong = sum(1 for r in new_alerts if r.label == "STRONG")
        alert  = sum(1 for r in new_alerts if r.label == "ALERT")
        watch  = sum(1 for r in new_alerts if r.label == "WATCH")

        if new_alerts:
            self._intel.ml(
                "LargeCandleWatcher",
                f"Scan — STRONG={strong}  ALERT={alert}  WATCH={watch}",
            )

        # Fire callbacks
        if new_alerts:
            sorted_alerts = sorted(new_alerts, key=lambda r: -r.candle_score)
            for cb in self._alert_callbacks:
                try:
                    cb(sorted_alerts)
                except Exception as exc:
                    logger.warning(f"LargeCandleWatcher callback error: {exc!r}")

    # ── Per-symbol analysis ────────────────────────────────────────────────────

    def _analyze(self, symbol: str, timeframe: str) -> Optional[LargeCandleResult]:
        klines = self._fetch_klines(symbol, timeframe, LOOKBACK_BARS + 5)
        if not klines or len(klines) < MIN_BARS + 2:
            return None

        opens   = np.array([float(k[1]) for k in klines], dtype=float)
        highs   = np.array([float(k[2]) for k in klines], dtype=float)
        lows    = np.array([float(k[3]) for k in klines], dtype=float)
        closes  = np.array([float(k[4]) for k in klines], dtype=float)
        volumes = np.array([float(k[5]) for k in klines], dtype=float)

        n = len(closes)

        # Current (last complete) candle
        o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
        prev_close  = closes[-2] if n >= 2 else c

        # ── Candle range as % of prev close ───────────────────────────────────
        if prev_close < 1e-12:
            return None

        current_range_pct = (h - l) / prev_close * 100.0

        # ── Baseline: average range of last BASELINE_BARS candles (excl. current) ──
        baseline_slice = slice(max(0, n - 1 - BASELINE_BARS), n - 1)
        baseline_ranges = (highs[baseline_slice] - lows[baseline_slice])
        baseline_closes = closes[baseline_slice]
        if len(baseline_ranges) < 3 or np.any(baseline_closes < 1e-12):
            return None
        avg_range_arr = baseline_ranges / baseline_closes * 100.0
        avg_range_pct = float(np.mean(avg_range_arr))
        if avg_range_pct < 1e-6:
            return None

        expansion_ratio = current_range_pct / avg_range_pct

        # ── Body ratio ────────────────────────────────────────────────────────
        candle_span = h - l
        if candle_span < 1e-12:
            body_ratio = 0.0
        else:
            body_ratio = abs(c - o) / candle_span

        # ── Direction ─────────────────────────────────────────────────────────
        if c > o * 1.0001:
            direction = "BULL"
        elif c < o * 0.9999:
            direction = "BEAR"
        else:
            direction = "MIXED"

        # ── Volume ratio ──────────────────────────────────────────────────────
        baseline_vols = volumes[baseline_slice]
        avg_vol = float(np.mean(baseline_vols)) if len(baseline_vols) > 0 else 1.0
        if avg_vol < 1e-12:
            avg_vol = 1.0
        volume_ratio = float(volumes[-1]) / avg_vol

        # ── Label ─────────────────────────────────────────────────────────────
        if expansion_ratio >= STRONG_RATIO:
            label = "STRONG"
        elif expansion_ratio >= ALERT_RATIO:
            label = "ALERT"
        elif expansion_ratio >= WATCH_RATIO:
            label = "WATCH"
        else:
            label = "NONE"

        # ── Score ─────────────────────────────────────────────────────────────
        expansion_sub = min(1.0, max(0.0, (expansion_ratio - 1.0) / 9.0))
        volume_sub    = min(1.0, max(0.0, (volume_ratio    - 1.0) / 7.0))
        body_sub      = float(np.clip(body_ratio, 0.0, 1.0))
        candle_score  = round(0.50 * expansion_sub + 0.30 * volume_sub + 0.20 * body_sub, 4)

        # ── Price change (candle body %) ──────────────────────────────────────
        price_chg = (c - o) / o * 100.0 if o > 1e-12 else 0.0

        result_id = f"{symbol}_{timeframe}"

        return LargeCandleResult(
            symbol           = symbol,
            timeframe        = timeframe,
            label            = label,
            direction        = direction,
            expansion_ratio  = round(expansion_ratio, 2),
            candle_range_pct = round(current_range_pct, 4),
            avg_range_pct    = round(avg_range_pct, 4),
            body_ratio       = round(body_ratio, 3),
            volume_ratio     = round(volume_ratio, 3),
            candle_score     = candle_score,
            open_price       = round(float(o), 8),
            high_price       = round(float(h), 8),
            low_price        = round(float(l), 8),
            close_price      = round(float(c), 8),
            last_price       = round(float(c), 8),
            price_change_pct = round(price_chg, 4),
            note             = (
                f"Range {current_range_pct:.3f}%  ×{expansion_ratio:.1f} avg  "
                f"Vol×{volume_ratio:.1f}  Body={body_ratio:.2f}"
            ),
            result_id        = result_id,
        )

    # ── Kline cache ────────────────────────────────────────────────────────────

    def _fetch_klines(self, symbol: str, interval: str, limit: int) -> list:
        key = (symbol, interval)
        now = time.monotonic()
        ttl = CACHE_TTL.get(interval, 60)
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
            logger.debug(f"LargeCandleWatcher: fetch failed {symbol}/{interval}: {exc!r}")
            return self._synthetic_klines(symbol, interval, limit)

    @staticmethod
    def _synthetic_klines(symbol: str, interval: str, limit: int) -> list:
        """Synthetic klines with occasional large candle events for demo/offline mode."""
        rng = np.random.default_rng(hash(symbol + interval + "lcw") % (2 ** 31))
        price = 100.0
        now_ms = int(time.time() * 1000)

        bar_ms_map = {
            "1m":  60_000,
            "5m":  300_000,
            "15m": 900_000,
            "1h":  3_600_000,
        }
        bar_ms = bar_ms_map.get(interval, 60_000)

        klines = []
        for i in range(limit):
            ts = now_ms - (limit - i) * bar_ms

            price_chg = rng.normal(0, 0.008) * price
            price = max(0.001, price + price_chg)

            open_p = price * (1 + rng.normal(0, 0.002))

            # Inject a large candle every ~20 bars
            is_large = (i > 5) and (i % (18 + rng.integers(0, 8)) == 0)
            if is_large:
                multiplier = rng.uniform(3.0, 8.0)
                direction  = rng.choice([-1, 1])
                body_size  = price * rng.uniform(0.015, 0.04) * multiplier
                close_p    = open_p + direction * body_size
                high_p     = max(open_p, close_p) * (1 + abs(rng.normal(0, 0.003)))
                low_p      = min(open_p, close_p) * (1 - abs(rng.normal(0, 0.003)))
                vol        = max(0.0, rng.normal(200_000, 50_000))
            else:
                close_p    = price
                high_p     = max(open_p, close_p) * (1 + abs(rng.normal(0, 0.003)))
                low_p      = min(open_p, close_p) * (1 - abs(rng.normal(0, 0.003)))
                vol        = max(0.0, rng.normal(50_000, 15_000))

            buy_v = vol * rng.uniform(0.45, 0.65)
            klines.append([
                ts,
                str(open_p),
                str(high_p),
                str(low_p),
                str(close_p),
                str(vol),
                ts + bar_ms - 1,
                str(vol * price),
                100,
                str(buy_v),
                str(buy_v * price),
                "0",
            ])
            price = float(close_p)

        return klines
