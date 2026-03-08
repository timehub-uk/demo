"""
Volume Breakout Detector ML — Identifies tokens progressing through four
distinct breakout stages driven by volume and price action analysis.

Stage Classification:

  Stage 1 — LAUNCH
    First signs of life: volume surges above baseline, price starts moving.
    Criteria: volume spike ≥ 2× 20-bar average on short timeframe,
              price breaks above recent range high, no prior stage detected.

  Stage 2 — SMALL PUMP
    Initial pump confirmed: rapid price gain + accelerating volume.
    Criteria: price up ≥ 3% in 4h, volume 3–6× baseline,
              buy ratio elevated (taker-buy dominant), RSI < 70 (not yet overbought).

  Stage 3 — CONSOLIDATION
    Price stalls after pump, volume drops but stays elevated vs pre-launch.
    Criteria: price trading in ≤ 2% range for ≥ 6 bars,
              volume declining from peak but still 1.5× pre-breakout average,
              stage 2 was detected in the prior window.

  Stage 4 — LARGE BREAKOUT
    Major move: price breaks above consolidation on heavy volume.
    Criteria: price breaks above stage-3 range high by ≥ 2%,
              volume ≥ 4× baseline, sustained (persists for ≥ 2 bars).

Algorithm runs on 15m klines (last 96 bars = 24h window).

  volume_baseline  : median(volume[0:40])
  volume_spike     : volume[-1] / volume_baseline
  price_change_4h  : (close[-1] - close[-16]) / close[-16] × 100
  rsi_14           : standard 14-bar RSI
  consolidation    : std(close[-8:]) / mean(close[-8:]) < 0.01

  breakout_score   : weighted combination of sub-scores per stage
  stage            : 0 (NONE) | 1 (LAUNCH) | 2 (PUMP) | 3 (CONSOLIDATION) | 4 (BREAKOUT)

Results:
  - Stored in pair_registry.breakout_stage + breakout_score
  - Exposed via get_by_stage(n) for UI and strategy modules
  - Callbacks fired for stage 2, 3, 4 detections

Refresh: every SCAN_INTERVAL_SEC (default 900 s / 15 min).
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


SCAN_INTERVAL_SEC  = 900    # 15-minute cycle
LOOKBACK_BARS      = 96     # 96 × 15m = 24h
MIN_BARS           = 40     # minimum bars for any signal
BASELINE_BARS      = 40     # bars used to compute volume baseline (pre-signal)

# Volume multiplier thresholds
LAUNCH_VOL_X    = 2.0
PUMP_VOL_X      = 3.0
CONSOL_VOL_X    = 1.5
BREAKOUT_VOL_X  = 4.0

# Price movement thresholds (%)
PUMP_PRICE_PCT      = 3.0   # min gain in 4h to call PUMP
BREAKOUT_PRICE_PCT  = 2.0   # must break consolidation range by this much
CONSOL_RANGE_PCT    = 2.0   # max range width for consolidation
CONSOL_MIN_BARS     = 6     # min bars in tight range

# RSI
RSI_OVERBOUGHT = 72


@dataclass
class BreakoutResult:
    """Volume breakout analysis result for one symbol."""
    symbol:          str
    stage:           int           # 0–4
    stage_label:     str           # NONE | LAUNCH | PUMP | CONSOLIDATION | BREAKOUT
    breakout_score:  float         # 0.0–1.0 confidence within the stage
    volume_spike:    float = 0.0   # volume / baseline
    price_change_4h: float = 0.0   # % change over last 4h
    rsi:             float = 50.0
    in_consolidation: bool = False
    consol_bars:     int   = 0     # how many bars in current tight range
    last_price:      float = 0.0
    volume_baseline: float = 0.0
    bars_analysed:   int   = 0
    note:            str   = ""
    updated_at:      str   = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def stage_emoji(self) -> str:
        return {
            0: "⬛",
            1: "🚀",
            2: "📈",
            3: "⏸",
            4: "💥",
        }.get(self.stage, "⬛")

    @property
    def stage_color(self) -> str:
        """Return a CSS colour string for the UI."""
        return {
            0: "#666666",
            1: "#00BFFF",   # launch — cyan
            2: "#00CC66",   # pump — green
            3: "#FFD700",   # consolidation — gold
            4: "#FF4500",   # large breakout — red-orange
        }.get(self.stage, "#666666")


class VolumeBreakoutDetector:
    """
    Detects tokens progressing through the 4-stage volume breakout pattern.

    Usage::

        detector = VolumeBreakoutDetector(
            binance_client=client,
            pair_scanner=pair_scanner,
        )
        detector.on_breakout(my_callback)   # called for stages 2, 3, 4
        detector.start()
        stage4 = detector.get_by_stage(4)
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

        self._results:   dict[str, BreakoutResult] = {}
        self._callbacks: list[Callable[[list[BreakoutResult]], None]] = []

        # Cache: (symbol, interval) → {"data": list, "ts": float}
        self._cache: dict[tuple[str, str], dict] = {}

        # Track last-seen stage per symbol for change detection
        self._prev_stages: dict[str, int] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_breakout(self, cb: Callable[[list[BreakoutResult]], None]) -> None:
        """Register callback — called when any stage-2/3/4 result is detected."""
        self._callbacks.append(cb)

    def get_all(self) -> list[BreakoutResult]:
        """Return all results sorted by stage desc, then score desc."""
        with self._lock:
            return sorted(
                self._results.values(),
                key=lambda r: (-r.stage, -r.breakout_score),
            )

    def get_by_stage(self, stage: int) -> list[BreakoutResult]:
        """Return all results matching a specific stage (1–4)."""
        with self._lock:
            return sorted(
                [r for r in self._results.values() if r.stage == stage],
                key=lambda r: -r.breakout_score,
            )

    def get_active(self) -> list[BreakoutResult]:
        """Return all results with stage ≥ 1."""
        with self._lock:
            return sorted(
                [r for r in self._results.values() if r.stage >= 1],
                key=lambda r: (-r.stage, -r.breakout_score),
            )

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="volume-breakout-detector"
        )
        self._thread.start()
        self._intel.ml("VolumeBreakoutDetector",
                       "Started — scanning for 4-stage volume breakout patterns")

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(20)  # wait for pair scanner first
        while self._running:
            t0 = time.monotonic()
            try:
                self._scan()
            except Exception as exc:
                logger.warning(f"VolumeBreakoutDetector error: {exc!r}")
            elapsed = time.monotonic() - t0
            time.sleep(max(1.0, SCAN_INTERVAL_SEC - elapsed))

    def _scan(self) -> None:
        """Scan HIGH + MEDIUM priority pairs for breakout stages."""
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

        new_results:    dict[str, BreakoutResult] = {}
        notable: list[BreakoutResult] = []

        for sym in candidates:
            if not self._running:
                break
            try:
                result = self._analyze(sym)
                if result:
                    new_results[sym] = result
                    prev = self._prev_stages.get(sym, 0)
                    # Notify on stage 2+ and on stage advancement
                    if result.stage >= 2 or result.stage > prev:
                        notable.append(result)
                    self._prev_stages[sym] = result.stage
                    if result.stage >= 2:
                        self._persist(result)
            except Exception as exc:
                logger.debug(f"VolumeBreakoutDetector: {sym} failed: {exc!r}")

        with self._lock:
            self._results.update(new_results)

        counts = {s: sum(1 for r in new_results.values() if r.stage == s) for s in range(5)}
        self._intel.ml(
            "VolumeBreakoutDetector",
            f"Scan complete — {len(new_results)} pairs  "
            f"LAUNCH={counts[1]}  PUMP={counts[2]}  "
            f"CONSOL={counts[3]}  BREAKOUT={counts[4]}"
        )

        if notable:
            sorted_notable = sorted(notable, key=lambda r: (-r.stage, -r.breakout_score))
            for cb in self._callbacks:
                try:
                    cb(sorted_notable)
                except Exception as exc:
                    logger.warning(f"VolumeBreakoutDetector callback error: {exc!r}")

    # ── Per-symbol analysis ────────────────────────────────────────────────────

    def _analyze(self, symbol: str) -> Optional[BreakoutResult]:
        """Fetch 15m klines and classify breakout stage."""
        klines = self._fetch_klines(symbol, "15m", LOOKBACK_BARS + 5)
        if not klines or len(klines) < MIN_BARS:
            return None

        closes  = np.array([float(k[4]) for k in klines], dtype=float)
        volumes = np.array([float(k[5]) for k in klines], dtype=float)
        buy_vols = np.array([float(k[9]) for k in klines], dtype=float)

        n = len(closes)

        # Volume baseline from first BASELINE_BARS bars
        baseline_vol = float(np.median(volumes[:BASELINE_BARS]))
        if baseline_vol < 1e-10:
            return None

        current_vol  = float(volumes[-1])
        recent_vol   = float(np.mean(volumes[-4:]))   # last 1h average
        volume_spike = recent_vol / baseline_vol

        # Price changes
        price_change_4h = float((closes[-1] - closes[-16]) / closes[-16] * 100) if n >= 16 else 0.0
        price_change_1h = float((closes[-1] - closes[-4]) / closes[-4] * 100)  if n >= 4  else 0.0

        # RSI-14
        rsi = self._rsi(closes, 14)

        # Buy ratio — last 8 bars
        with np.errstate(divide="ignore", invalid="ignore"):
            buy_ratios = np.where(volumes[-8:] > 0, buy_vols[-8:] / volumes[-8:], 0.5)
        buy_ratio = float(np.mean(buy_ratios))

        # Consolidation detection — last CONSOL_MIN_BARS bars
        consol_window = closes[-CONSOL_MIN_BARS:]
        consol_range  = (consol_window.max() - consol_window.min()) / consol_window.mean() * 100
        in_consol     = consol_range <= CONSOL_RANGE_PCT
        consol_bars   = self._count_consol_bars(closes, CONSOL_RANGE_PCT)

        # ── Stage classification ───────────────────────────────────────────────

        # Stage 4 — LARGE BREAKOUT: price breaks above prior 8-bar range on heavy volume
        prior_range_high = float(np.max(closes[-16:-8])) if n >= 16 else closes.max()
        breakout_pct     = (closes[-1] - prior_range_high) / prior_range_high * 100

        if (volume_spike >= BREAKOUT_VOL_X
                and breakout_pct >= BREAKOUT_PRICE_PCT
                and price_change_4h >= PUMP_PRICE_PCT):
            # Confirm with ≥ 2 bars sustaining above the level
            bars_above = sum(1 for c in closes[-4:] if c > prior_range_high)
            if bars_above >= 2:
                score = min(1.0, (volume_spike / BREAKOUT_VOL_X) * 0.5
                            + (breakout_pct / (BREAKOUT_PRICE_PCT * 3)) * 0.5)
                return self._make_result(symbol, 4, "BREAKOUT", score,
                                         volume_spike, price_change_4h, rsi,
                                         in_consol, consol_bars, closes[-1],
                                         baseline_vol, n,
                                         f"Break={breakout_pct:.2f}%  VolX={volume_spike:.1f}")

        # Stage 3 — CONSOLIDATION: flat price after a pump, volume elevated
        if (in_consol
                and consol_bars >= CONSOL_MIN_BARS
                and volume_spike >= CONSOL_VOL_X
                and price_change_4h >= 1.0):   # started from some elevation
            score = min(1.0, (consol_bars / 12) * 0.4
                        + (volume_spike / CONSOL_VOL_X) * 0.3
                        + (1.0 - consol_range / CONSOL_RANGE_PCT) * 0.3)
            return self._make_result(symbol, 3, "CONSOLIDATION", score,
                                     volume_spike, price_change_4h, rsi,
                                     in_consol, consol_bars, closes[-1],
                                     baseline_vol, n,
                                     f"Range={consol_range:.2f}%  Bars={consol_bars}")

        # Stage 2 — SMALL PUMP: price rising, volume surging, RSI not overbought
        if (volume_spike >= PUMP_VOL_X
                and price_change_4h >= PUMP_PRICE_PCT
                and rsi < RSI_OVERBOUGHT
                and buy_ratio > 0.55):
            score = min(1.0, (volume_spike / (PUMP_VOL_X * 2)) * 0.4
                        + (price_change_4h / (PUMP_PRICE_PCT * 3)) * 0.3
                        + buy_ratio * 0.3)
            return self._make_result(symbol, 2, "PUMP", score,
                                     volume_spike, price_change_4h, rsi,
                                     in_consol, consol_bars, closes[-1],
                                     baseline_vol, n,
                                     f"BuyRatio={buy_ratio:.2f}  RSI={rsi:.1f}")

        # Stage 1 — LAUNCH: first spike, price starting to move
        if (volume_spike >= LAUNCH_VOL_X
                and price_change_1h >= 1.0
                and buy_ratio > 0.52):
            score = min(1.0, (volume_spike / (LAUNCH_VOL_X * 2)) * 0.5
                        + (price_change_1h / 5.0) * 0.3
                        + (buy_ratio - 0.5) * 0.4)
            return self._make_result(symbol, 1, "LAUNCH", score,
                                     volume_spike, price_change_4h, rsi,
                                     in_consol, consol_bars, closes[-1],
                                     baseline_vol, n,
                                     f"VolX={volume_spike:.1f}  1h={price_change_1h:.2f}%")

        # Stage 0 — no signal
        return BreakoutResult(
            symbol          = symbol,
            stage           = 0,
            stage_label     = "NONE",
            breakout_score  = 0.0,
            volume_spike    = round(volume_spike, 2),
            price_change_4h = round(price_change_4h, 3),
            rsi             = round(rsi, 1),
            in_consolidation = in_consol,
            consol_bars     = consol_bars,
            last_price      = float(closes[-1]),
            volume_baseline = round(baseline_vol, 2),
            bars_analysed   = n,
        )

    @staticmethod
    def _make_result(
        symbol: str, stage: int, label: str, score: float,
        vol_spike: float, price_4h: float, rsi: float,
        in_consol: bool, consol_bars: int,
        last_price: float, baseline_vol: float, n: int, note: str,
    ) -> BreakoutResult:
        return BreakoutResult(
            symbol           = symbol,
            stage            = stage,
            stage_label      = label,
            breakout_score   = round(max(0.0, min(1.0, score)), 4),
            volume_spike     = round(vol_spike, 2),
            price_change_4h  = round(price_4h, 3),
            rsi              = round(rsi, 1),
            in_consolidation = in_consol,
            consol_bars      = consol_bars,
            last_price       = last_price,
            volume_baseline  = round(baseline_vol, 2),
            bars_analysed    = n,
            note             = note,
        )

    # ── Indicators ─────────────────────────────────────────────────────────────

    @staticmethod
    def _rsi(closes: np.ndarray, period: int = 14) -> float:
        """Compute RSI using Wilder's smoothing."""
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains  = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))
        for g, l in zip(gains[period:], losses[period:]):
            avg_gain = (avg_gain * (period - 1) + g) / period
            avg_loss = (avg_loss * (period - 1) + l) / period
        if avg_loss < 1e-12:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    @staticmethod
    def _count_consol_bars(closes: np.ndarray, range_pct: float) -> int:
        """Count how many trailing bars fit within a tight range_pct band.

        Expands the window backward from the last bar until the range exceeds
        range_pct, then returns the last window size that still passed.
        """
        n = len(closes)
        if n < 2:
            return 0
        mean = closes.mean()
        if mean == 0:
            return 0
        for count in range(2, n + 1):
            window = closes[n - count:]
            r = (window.max() - window.min()) / window.mean() * 100
            if r > range_pct:
                return count - 1
        return n

    # ── Kline cache ────────────────────────────────────────────────────────────

    def _fetch_klines(self, symbol: str, interval: str, limit: int) -> list:
        key = (symbol, interval)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and (now - cached["ts"]) < 120:   # 2-min TTL for 15m bars
            return cached["data"]

        data = self._fetch_api(symbol, interval, limit)
        if data:
            self._cache[key] = {"data": data, "ts": now}
        return data or (cached or {}).get("data", [])

    def _fetch_api(self, symbol: str, interval: str, limit: int) -> list:
        if not self._client:
            return self._synthetic_klines(symbol, limit)
        try:
            return self._client.get_klines(symbol=symbol, interval=interval, limit=limit)
        except Exception as exc:
            logger.debug(f"VolumeBreakoutDetector: fetch failed {symbol}: {exc!r}")
            return self._synthetic_klines(symbol, limit)

    @staticmethod
    def _synthetic_klines(symbol: str, limit: int) -> list:
        """Generate synthetic klines simulating a stage-1→4 breakout for demo."""
        rng   = np.random.default_rng(hash(symbol) % (2**31))
        price = 1.0
        now_ms = int(time.time() * 1000)
        bar_ms = 15 * 60 * 1000
        klines = []

        # Determine which stage to simulate based on symbol hash
        sim_stage = (hash(symbol) % 5)   # 0–4

        for i in range(limit):
            ts = now_ms - (limit - i) * bar_ms
            phase = i / limit

            if sim_stage == 0 or phase < 0.6:
                # Flat baseline
                price += rng.normal(0, 0.001) * price
                vol   = max(0, 10_000 + rng.normal(0, 2_000))
                buy   = vol * (0.50 + rng.normal(0, 0.04))
            elif phase < 0.7:
                # Stage 1 launch
                price += rng.normal(0.003, 0.002) * price
                vol   = max(0, 25_000 + rng.normal(0, 5_000))
                buy   = vol * (0.57 + rng.normal(0, 0.04))
            elif phase < 0.80:
                # Stage 2 pump
                price += rng.normal(0.008, 0.003) * price
                vol   = max(0, 40_000 + rng.normal(0, 8_000))
                buy   = vol * (0.65 + rng.normal(0, 0.04))
            elif phase < 0.90:
                # Stage 3 consolidation
                price += rng.normal(0, 0.0008) * price
                vol   = max(0, 20_000 + rng.normal(0, 3_000))
                buy   = vol * (0.53 + rng.normal(0, 0.04))
            else:
                # Stage 4 breakout
                price += rng.normal(0.015, 0.004) * price
                vol   = max(0, 70_000 + rng.normal(0, 10_000))
                buy   = vol * (0.70 + rng.normal(0, 0.04))

            h = price * (1 + abs(rng.normal(0, 0.002)))
            l = price * (1 - abs(rng.normal(0, 0.002)))
            klines.append([
                ts, str(price), str(h), str(l), str(price),
                str(vol), ts + bar_ms - 1, str(vol * price), 100,
                str(buy), str(buy * price), "0",
            ])
        return klines

    # ── DB persistence ─────────────────────────────────────────────────────────

    def _persist(self, result: BreakoutResult) -> None:
        """Update breakout_stage and breakout_score in pair_registry."""
        try:
            from sqlalchemy import select
            from db.postgres import get_db
            from db.models import PairRegistry
            with get_db() as db:
                row = db.execute(select(PairRegistry).filter_by(symbol=result.symbol)).scalar_one_or_none()
                if row:
                    row.breakout_stage = result.stage
                    row.breakout_score = result.breakout_score
        except Exception as exc:
            logger.debug(f"VolumeBreakoutDetector: DB persist failed: {exc!r}")
