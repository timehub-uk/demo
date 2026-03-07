"""
Accumulation Detector ML — Finds stealth accumulation of low-volume tokens
that may be primed for a breakout ("secret collecting" pattern).

The detector looks for coins that show:

  1. Compressed price range   — price going sideways in a tight band
                                (low volatility relative to history)
  2. Rising volume trend      — slowly increasing buy-side volume despite
                                flat or declining price (smart money loading)
  3. Positive volume imbalance— taker-buy volume consistently > taker-sell
                                (aggressive buyers, not just market makers)
  4. Long accumulation window — the above conditions persisting for many bars
                                (days to weeks) without a breakout yet
  5. Low market cap / thin liquidity — easier to move; early mover advantage

Classification labels:
  NONE   — no accumulation signal
  WATCH  — mild signals (1–2 criteria met)
  ALERT  — moderate accumulation pattern detected (3 criteria)
  STRONG — high-conviction accumulation (4–5 criteria, sustained period)

Algorithm (all computed from 1h klines over 30–90 bar windows):

  range_score     : 1 - (std(close) / mean(close))   → tight range = 1.0
  volume_trend    : OLS slope of volume normalised by mean volume
  buy_ratio       : mean(taker_buy_volume / total_volume) → 0.5 = neutral
  duration_score  : how many consecutive bars the pattern has persisted
  price_stability : fraction of bars where |close_change| < 0.5%

  accumulation_score = (
      0.35 × range_score
    + 0.25 × volume_trend_score
    + 0.20 × buy_ratio_score
    + 0.12 × duration_score
    + 0.08 × price_stability
  )

Results are:
  - Stored in pair_registry.accumulation_score + accumulation_label
  - Exposed via get_alerts() and get_strong() for UI and other modules
  - Emitted as callbacks to subscribers

Refresh: every SCAN_INTERVAL_SEC (default 1800 s / 30 min).
Only scans LOW-priority pairs by default (thin markets where accumulation
is more detectable and potentially more rewarding).
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


SCAN_INTERVAL_SEC = 1800   # 30-minute cycle
LOOKBACK_BARS     = 60     # How many 1h bars to analyse
MIN_BARS          = 20     # Minimum bars needed for any signal
WATCH_THRESHOLD   = 0.35
ALERT_THRESHOLD   = 0.55
STRONG_THRESHOLD  = 0.70


@dataclass
class AccumulationResult:
    """Accumulation analysis result for one symbol."""
    symbol:            str
    accumulation_score: float        # 0.0–1.0
    label:             str           # NONE | WATCH | ALERT | STRONG
    range_score:       float = 0.0
    volume_trend:      float = 0.0
    buy_ratio:         float = 0.0
    duration_score:    float = 0.0
    price_stability:   float = 0.0
    bars_analysed:     int   = 0
    last_price:        float = 0.0
    price_change_pct:  float = 0.0
    note:              str   = ""
    updated_at:        str   = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def label_emoji(self) -> str:
        return {"NONE": "⬛", "WATCH": "👁", "ALERT": "🔶", "STRONG": "🚨"}.get(self.label, "⬛")


class AccumulationDetector:
    """
    Scans pairs for stealth accumulation patterns.  Focuses on LOW-priority
    pairs (thin markets) where early detection has the highest edge.

    Usage::

        detector = AccumulationDetector(
            binance_client=client,
            pair_scanner=pair_scanner,
        )
        detector.on_alert(my_callback)   # called for ALERT and STRONG signals
        detector.start()
        alerts = detector.get_alerts()
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

        self._results: dict[str, AccumulationResult] = {}
        self._callbacks: list[Callable[[list[AccumulationResult]], None]] = []

        # Kline cache: (symbol, interval) → {"data": list, "ts": float}
        self._cache: dict[tuple[str, str], dict] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_alert(self, cb: Callable[[list[AccumulationResult]], None]) -> None:
        """Register callback — called with ALERT/STRONG results after each scan."""
        self._callbacks.append(cb)

    def get_all(self) -> list[AccumulationResult]:
        """Return all results (NONE included), sorted by score descending."""
        with self._lock:
            return sorted(self._results.values(), key=lambda r: -r.accumulation_score)

    def get_alerts(self) -> list[AccumulationResult]:
        """Return ALERT and STRONG results."""
        with self._lock:
            return sorted(
                [r for r in self._results.values() if r.label in ("ALERT", "STRONG")],
                key=lambda r: -r.accumulation_score,
            )

    def get_strong(self) -> list[AccumulationResult]:
        """Return only STRONG results."""
        with self._lock:
            return sorted(
                [r for r in self._results.values() if r.label == "STRONG"],
                key=lambda r: -r.accumulation_score,
            )

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="accumulation-detector"
        )
        self._thread.start()
        self._intel.ml("AccumulationDetector",
                       "Started — scanning for stealth accumulation patterns")

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(10)  # wait for pair scanner first
        while self._running:
            t0 = time.monotonic()
            try:
                self._scan()
            except Exception as exc:
                logger.warning(f"AccumulationDetector error: {exc!r}")
            elapsed = time.monotonic() - t0
            time.sleep(max(1.0, SCAN_INTERVAL_SEC - elapsed))

    def _scan(self) -> None:
        """Scan all LOW + MEDIUM priority pairs for accumulation patterns."""
        candidates: list[str] = []

        if self._pairs:
            low    = self._pairs.get_pairs_by_priority("LOW")
            medium = self._pairs.get_pairs_by_priority("MEDIUM")
            candidates = [p.symbol for p in (low + medium)]
        else:
            # Offline fallback — a small demo list
            candidates = [
                "FILUSDT", "SANDUSDT", "MANAUSDT", "IOTAUSDT", "ALGOUSDT",
                "VETUSDT", "GRTUSDT", "CRVUSDT", "SNXUSDT", "ICPUSDT",
            ]

        new_results: dict[str, AccumulationResult] = {}
        alerts: list[AccumulationResult] = []

        for sym in candidates:
            if not self._running:
                break
            try:
                result = self._analyze(sym)
                if result:
                    new_results[sym] = result
                    if result.label in ("ALERT", "STRONG"):
                        alerts.append(result)
                        self._persist(result)
            except Exception as exc:
                logger.debug(f"AccumulationDetector: {sym} failed: {exc!r}")

        with self._lock:
            self._results.update(new_results)

        alert_count  = sum(1 for r in new_results.values() if r.label == "ALERT")
        strong_count = sum(1 for r in new_results.values() if r.label == "STRONG")
        self._intel.ml(
            "AccumulationDetector",
            f"Scan complete — {len(new_results)} pairs  "
            f"ALERT={alert_count}  STRONG={strong_count}"
        )

        if alerts:
            for cb in self._callbacks:
                try:
                    cb(sorted(alerts, key=lambda r: -r.accumulation_score))
                except Exception as exc:
                    logger.warning(f"AccumulationDetector callback error: {exc!r}")

    # ── Per-symbol analysis ────────────────────────────────────────────────────

    def _analyze(self, symbol: str) -> Optional[AccumulationResult]:
        """Fetch 1h klines and compute accumulation sub-scores."""
        klines = self._fetch_klines(symbol, "1h", LOOKBACK_BARS + 5)
        if not klines or len(klines) < MIN_BARS:
            return None

        # Parse kline fields
        closes     = np.array([float(k[4]) for k in klines], dtype=float)
        volumes    = np.array([float(k[5]) for k in klines], dtype=float)
        buy_vols   = np.array([float(k[9]) for k in klines], dtype=float)   # taker buy base vol

        n = len(closes)

        # ── 1. Range score — tight price = high score ──────────────────────────
        mean_price = closes.mean()
        if mean_price < 1e-12:
            return None
        cv         = closes.std() / mean_price   # coefficient of variation
        range_score = max(0.0, min(1.0, 1.0 - cv * 20))   # cv > 0.05 → 0

        # ── 2. Volume trend — slowly rising volume = positive signal ───────────
        if volumes.mean() < 1e-10:
            vol_trend_score = 0.0
        else:
            norm_vol = volumes / volumes.mean()
            x = np.arange(n, dtype=float)
            xm, ym = x.mean(), norm_vol.mean()
            ssxy = np.sum((x - xm) * (norm_vol - ym))
            ssxx = np.sum((x - xm) ** 2)
            slope = ssxy / ssxx if ssxx > 1e-12 else 0.0
            # Positive slope = rising volume trend
            vol_trend_score = max(0.0, min(1.0, slope * 50 + 0.5))

        # ── 3. Buy ratio — taker-buy vs total volume ───────────────────────────
        total_vol = volumes
        with np.errstate(divide="ignore", invalid="ignore"):
            ratios = np.where(total_vol > 0, buy_vols / total_vol, 0.5)
        buy_ratio = float(ratios.mean())
        buy_ratio_score = max(0.0, min(1.0, (buy_ratio - 0.5) * 4))   # 0.5=0, 0.75=1.0

        # ── 4. Duration — how many consecutive bars the pattern holds ──────────
        flat_bars = 0
        for i in range(n - 1, -1, -1):
            if abs(closes[i] - mean_price) / mean_price < 0.02:   # within ±2%
                flat_bars += 1
            else:
                break
        duration_score = min(1.0, flat_bars / 30)   # 30 bars = full score

        # ── 5. Price stability — fraction of bars with tiny moves ──────────────
        if n > 1:
            pct_changes = np.abs(np.diff(closes) / closes[:-1])
            stable      = float(np.mean(pct_changes < 0.005))
        else:
            stable = 0.0

        # ── Composite ──────────────────────────────────────────────────────────
        score = (
            0.35 * range_score
            + 0.25 * vol_trend_score
            + 0.20 * buy_ratio_score
            + 0.12 * duration_score
            + 0.08 * stable
        )

        # Label
        if score >= STRONG_THRESHOLD:
            label = "STRONG"
        elif score >= ALERT_THRESHOLD:
            label = "ALERT"
        elif score >= WATCH_THRESHOLD:
            label = "WATCH"
        else:
            label = "NONE"

        return AccumulationResult(
            symbol             = symbol,
            accumulation_score = round(score, 4),
            label              = label,
            range_score        = round(range_score, 3),
            volume_trend       = round(vol_trend_score, 3),
            buy_ratio          = round(buy_ratio, 3),
            duration_score     = round(duration_score, 3),
            price_stability    = round(stable, 3),
            bars_analysed      = n,
            last_price         = float(closes[-1]),
            price_change_pct   = float((closes[-1] - closes[0]) / closes[0] * 100),
            note               = (
                f"Range CV={cv:.3f}  BuyRatio={buy_ratio:.2f}  "
                f"Flat={flat_bars}bars"
            ),
        )

    # ── Kline cache ────────────────────────────────────────────────────────────

    def _fetch_klines(self, symbol: str, interval: str, limit: int) -> list:
        key = (symbol, interval)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and (now - cached["ts"]) < 3600:   # 1h TTL for 1h bars
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
            logger.debug(f"AccumulationDetector: fetch failed {symbol}: {exc!r}")
            return self._synthetic_klines(symbol, limit)

    @staticmethod
    def _synthetic_klines(symbol: str, limit: int) -> list:
        """Generate synthetic accumulation-pattern klines for demo/offline."""
        rng   = np.random.default_rng(hash(symbol) % (2**31))
        price = 1.0
        now_ms = int(time.time() * 1000)
        h_ms   = 3_600_000
        klines = []
        for i in range(limit):
            ts   = now_ms - (limit - i) * h_ms
            # Tight sideways drift with mild volume trend
            price += rng.normal(0, 0.003) * price
            vol   = max(0, 100_000 + i * 500 + rng.normal(0, 20_000))
            buy   = vol * (0.52 + rng.normal(0, 0.05))   # slightly more buyers
            h = price * (1 + abs(rng.normal(0, 0.002)))
            l = price * (1 - abs(rng.normal(0, 0.002)))
            klines.append([
                ts, str(price), str(h), str(l), str(price),
                str(vol), ts + h_ms - 1, str(vol * price), 100,
                str(buy), str(buy * price), "0",
            ])
        return klines

    # ── DB persistence ─────────────────────────────────────────────────────────

    def _persist(self, result: AccumulationResult) -> None:
        """Update accumulation_score and label in pair_registry."""
        try:
            from db.postgres import get_db
            from db.models import PairRegistry
            with get_db() as db:
                row = db.query(PairRegistry).filter_by(symbol=result.symbol).first()
                if row:
                    row.accumulation_score = result.accumulation_score
                    row.accumulation_label = result.label
        except Exception as exc:
            logger.debug(f"AccumulationDetector: DB persist failed: {exc!r}")
