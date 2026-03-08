"""
Pair ML Analyzer — Cross-references every discovered pair against all ML tools
to produce a composite Tradability Score at any given moment.

For each pair (from PairScanner's HIGH + MEDIUM buckets) the analyzer queries:

  TrendScanner       → multi-TF trend alignment (how many timeframes agree?)
  MLPredictor        → signal (BUY/HOLD/SELL) + confidence
  WhaleWatcher       → recent large-order activity score
  SentimentAnalyser  → news / social sentiment score
  RegimeDetector     → current market regime
  ArbitrageDetector  → whether an active arb opportunity exists for this pair

These are blended into a single Tradability Score (0–1):

  tradability = 0.30 × trend_alignment
              + 0.25 × signal_score
              + 0.15 × priority_score   (volume/activity rank from PairScanner)
              + 0.15 × whale_score
              + 0.10 × sentiment_score
              + 0.05 × regime_score

Results are:
  1. Written to the pair_registry table (live field: tradability_score)
  2. Written to pair_ml_snapshots for historical ML review
  3. Exposed via get_best_tradable(n) for other modules and the UI

Run cycle: every ANALYZE_INTERVAL_SEC (default 300 s / 5 min).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from loguru import logger
from utils.logger import get_intel_logger


ANALYZE_INTERVAL_SEC = 300   # 5-minute cycle

# Regime → score mapping
_REGIME_SCORES: dict[str, float] = {
    "bull":     0.90,
    "bullish":  0.90,
    "bear":     0.35,
    "bearish":  0.35,
    "ranging":  0.60,
    "volatile": 0.40,
}


class PairMLAnalyzer:
    """
    Runs every 5 minutes, querying all ML subsystems for every HIGH+MEDIUM pair.

    Usage::

        analyzer = PairMLAnalyzer(
            pair_scanner=pair_scanner,
            trend_scanner=trend_scanner,
            predictor=predictor,
            whale_watcher=whale_watcher,
            sentiment=sentiment,
            regime_detector=regime_detector,
            arb_detector=arb_detector,
        )
        analyzer.on_update(my_callback)   # cb(list[dict]) — sorted best→worst
        analyzer.start()
        top10 = analyzer.get_best_tradable(10)
    """

    def __init__(
        self,
        pair_scanner=None,
        trend_scanner=None,
        predictor=None,
        whale_watcher=None,
        sentiment=None,
        regime_detector=None,
        arb_detector=None,
    ) -> None:
        self._pairs    = pair_scanner
        self._trends   = trend_scanner
        self._pred     = predictor
        self._whale    = whale_watcher
        self._sent     = sentiment
        self._regime   = regime_detector
        self._arb      = arb_detector
        self._intel    = get_intel_logger()

        self._lock    = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Sorted results: list of dicts {symbol, tradability_score, ...}
        self._results: list[dict] = []
        self._callbacks: list[Callable[[list[dict]], None]] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_update(self, cb: Callable[[list[dict]], None]) -> None:
        """Register callback — called after every analysis cycle."""
        self._callbacks.append(cb)

    def get_best_tradable(self, n: int = 20) -> list[dict]:
        """Return top-N pairs sorted by tradability score (best first)."""
        with self._lock:
            return self._results[:n]

    def get_all_results(self) -> list[dict]:
        with self._lock:
            return list(self._results)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="pair-ml-analyzer"
        )
        self._thread.start()
        self._intel.ml("PairMLAnalyzer", "Started — cross-referencing all pairs × all ML tools")

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(5)   # wait for pair scanner first scan
        while self._running:
            t0 = time.monotonic()
            try:
                self._run_analysis()
            except Exception as exc:
                logger.warning(f"PairMLAnalyzer cycle error: {exc!r}")
            elapsed = time.monotonic() - t0
            time.sleep(max(1.0, ANALYZE_INTERVAL_SEC - elapsed))

    def _run_analysis(self) -> None:
        if not self._pairs:
            return

        # Analyze HIGH + MEDIUM pairs (skip LOW — too many, too thin)
        high   = self._pairs.get_pairs_by_priority("HIGH")
        medium = self._pairs.get_pairs_by_priority("MEDIUM")
        candidates = high + medium

        if not candidates:
            return

        # Get current regime once (applies to all pairs)
        regime_score = self._get_regime_score()
        regime_label = self._get_regime_label()

        results: list[dict] = []
        for pair_info in candidates:
            if not self._running:
                break
            try:
                rec = self._analyze_one(pair_info, regime_score, regime_label)
                results.append(rec)
                self._persist(rec)
            except Exception as exc:
                logger.debug(f"PairMLAnalyzer: {pair_info.symbol} analysis failed: {exc!r}")

        # Sort by tradability descending
        results.sort(key=lambda r: -r.get("tradability_score", 0))

        with self._lock:
            self._results = results

        for cb in self._callbacks:
            try:
                cb(list(results))
            except Exception as exc:
                logger.warning(f"PairMLAnalyzer callback error: {exc!r}")

        self._intel.ml(
            "PairMLAnalyzer",
            f"Analysis complete — {len(results)} pairs scored  "
            f"top: {results[0]['symbol']} ({results[0]['tradability_score']:.3f})"
            if results else "Analysis complete — 0 pairs"
        )

    # ── Per-pair analysis ──────────────────────────────────────────────────────

    def _analyze_one(self, pair_info, regime_score: float, regime_label: str) -> dict:
        sym = pair_info.symbol

        # 1. Trend alignment — fraction of timeframes that agree on one direction
        trend_alignment, trend_detail = self._get_trend_alignment(sym)

        # 2. ML predictor signal score
        signal, confidence, signal_score = self._get_signal_score(sym)

        # 3. Whale activity score
        whale_score = self._get_whale_score(sym)

        # 4. Sentiment score (normalised 0–1)
        sentiment_score = self._get_sentiment_score(sym)

        # 5. Arb opportunity flag
        arb_opp = self._has_arb_opportunity(sym)

        # Priority score from PairScanner (already 0–1)
        priority_score = pair_info.priority_score

        # Composite tradability
        tradability = (
            0.30 * trend_alignment
            + 0.25 * signal_score
            + 0.15 * priority_score
            + 0.15 * whale_score
            + 0.10 * sentiment_score
            + 0.05 * regime_score
        )
        # Small boost if arb opportunity is active
        if arb_opp:
            tradability = min(1.0, tradability + 0.05)

        return {
            "symbol":            sym,
            "tradability_score": round(tradability, 4),
            "trend_alignment":   round(trend_alignment, 3),
            "trend_detail":      trend_detail,
            "ml_signal":         signal,
            "ml_confidence":     round(confidence, 3),
            "whale_score":       round(whale_score, 3),
            "sentiment_score":   round(sentiment_score, 3),
            "regime":            regime_label,
            "arb_opportunity":   arb_opp,
            "priority":          pair_info.priority,
            "priority_score":    round(priority_score, 3),
            "last_price":        pair_info.last_price,
            "price_change_pct":  pair_info.price_change_pct,
            "quote_volume":      pair_info.quote_volume,
            "updated_at":        datetime.now(timezone.utc).isoformat(),
        }

    # ── ML tool queries (all defensive — never crash if tool unavailable) ───────

    def _get_trend_alignment(self, symbol: str) -> tuple[float, dict]:
        """
        Query TrendScanner. Returns (alignment_score, {timeframe: direction}).
        alignment_score = fraction of available timeframes that share the majority direction.
        """
        if not self._trends:
            return 0.5, {}
        try:
            snap = self._trends.get_snapshot(symbol)
            if not snap or not snap.trends:
                return 0.5, {}
            directions = [tr.direction for tr in snap.trends.values()]
            if not directions:
                return 0.5, {}
            # Count votes
            up   = directions.count("UP")
            down = directions.count("DOWN")
            side = directions.count("SIDEWAYS")
            total = len(directions)
            majority = max(up, down, side)
            alignment = majority / total
            detail = {tf: tr.direction for tf, tr in snap.trends.items()}
            return alignment, detail
        except Exception:
            return 0.5, {}

    def _get_signal_score(self, symbol: str) -> tuple[str, float, float]:
        """Query MLPredictor. Returns (signal, confidence, score)."""
        if not self._pred:
            return "HOLD", 0.0, 0.0
        try:
            # Predictor may expose get_latest_signal(symbol)
            sig = None
            if hasattr(self._pred, "get_latest_signal"):
                sig = self._pred.get_latest_signal(symbol)
            if sig is None and hasattr(self._pred, "_signals"):
                sig = self._pred._signals.get(symbol)
            if sig is None:
                return "HOLD", 0.0, 0.0
            action     = sig.get("action", "HOLD")
            confidence = float(sig.get("confidence", 0.0))
            # Score: directional confidence (HOLD = 0)
            score = confidence if action in ("BUY", "SELL") else 0.0
            return action, confidence, score
        except Exception:
            return "HOLD", 0.0, 0.0

    def _get_whale_score(self, symbol: str) -> float:
        """Query WhaleWatcher for recent large-order activity on this symbol."""
        if not self._whale:
            return 0.0
        try:
            # WhaleWatcher may expose get_activity_score(symbol) or recent_events
            if hasattr(self._whale, "get_activity_score"):
                return float(self._whale.get_activity_score(symbol))
            if hasattr(self._whale, "_events"):
                events = self._whale._events
                recent = [
                    e for e in events
                    if getattr(e, "symbol", "") == symbol
                ]
                if not recent:
                    return 0.0
                # Score by most recent event confidence
                latest = max(recent, key=lambda e: getattr(e, "timestamp", ""))
                return min(1.0, float(getattr(latest, "confidence", 0.5)))
        except Exception:
            pass
        return 0.0

    def _get_sentiment_score(self, symbol: str) -> float:
        """Query SentimentAnalyser. Returns 0–1 (0.5 = neutral)."""
        if not self._sent:
            return 0.5
        try:
            if hasattr(self._sent, "get_score"):
                raw = self._sent.get_score(symbol)
                # Normalise from [-1, 1] → [0, 1]
                return max(0.0, min(1.0, (float(raw) + 1.0) / 2.0))
            if hasattr(self._sent, "_scores"):
                base = symbol.replace("USDT", "").replace("BTC", "").replace("ETH", "")
                raw  = self._sent._scores.get(symbol, self._sent._scores.get(base, 0.0))
                return max(0.0, min(1.0, (float(raw) + 1.0) / 2.0))
        except Exception:
            pass
        return 0.5

    def _has_arb_opportunity(self, symbol: str) -> bool:
        """Check ArbitrageDetector for live opportunity involving this symbol."""
        if not self._arb:
            return False
        try:
            opps = self._arb.active_opportunities
            return any(
                symbol in (o.leg_buy, o.leg_sell, getattr(o, "leg3", ""))
                for o in opps
            )
        except Exception:
            return False

    def _get_regime_score(self) -> float:
        if not self._regime:
            return 0.6
        try:
            regime = getattr(self._regime, "current_regime", None)
            if regime is None and hasattr(self._regime, "get_regime"):
                regime = self._regime.get_regime()
            if regime is None:
                return 0.6
            label = str(regime).lower()
            for k, v in _REGIME_SCORES.items():
                if k in label:
                    return v
        except Exception:
            pass
        return 0.6

    def _get_regime_label(self) -> str:
        if not self._regime:
            return "Unknown"
        try:
            regime = getattr(self._regime, "current_regime", None)
            if regime is None and hasattr(self._regime, "get_regime"):
                regime = self._regime.get_regime()
            return str(regime) if regime else "Unknown"
        except Exception:
            return "Unknown"

    # ── DB persistence ─────────────────────────────────────────────────────────

    def _persist(self, rec: dict) -> None:
        """Write/update PairRegistry and insert a PairMLSnapshot row."""
        try:
            from sqlalchemy import select
            from db.postgres import get_db
            from db.models import PairRegistry, PairMLSnapshot
            import sqlalchemy as sa

            sym = rec["symbol"]
            ts  = datetime.now(timezone.utc)

            with get_db() as db:
                # Upsert PairRegistry row
                row = db.execute(select(PairRegistry).filter_by(symbol=sym)).scalar_one_or_none()
                if row is None:
                    row = PairRegistry(symbol=sym, base=sym[:-4] if sym.endswith("USDT") else sym, quote="USDT")
                    db.add(row)
                row.tradability_score = rec["tradability_score"]
                row.trend_alignment   = rec["trend_alignment"]
                row.sentiment_score   = rec["sentiment_score"]
                row.whale_score       = rec["whale_score"]
                row.ml_signal         = rec["ml_signal"]
                row.ml_confidence     = rec["ml_confidence"]
                row.regime            = rec["regime"]
                row.arb_opportunity   = rec["arb_opportunity"]

                # Insert snapshot
                snap = PairMLSnapshot(
                    symbol             = sym,
                    timestamp          = ts,
                    trend_15m          = rec["trend_detail"].get("15m"),
                    trend_30m          = rec["trend_detail"].get("30m"),
                    trend_1h           = rec["trend_detail"].get("1h"),
                    trend_12h          = rec["trend_detail"].get("12h"),
                    trend_24h          = rec["trend_detail"].get("24h"),
                    trend_7d           = rec["trend_detail"].get("7d"),
                    trend_30d          = rec["trend_detail"].get("30d"),
                    ml_signal          = rec["ml_signal"],
                    ml_confidence      = rec["ml_confidence"],
                    price              = rec["last_price"],
                    volume_usdt        = rec["quote_volume"],
                    regime             = rec["regime"],
                    tradability_score  = rec["tradability_score"],
                    priority           = rec["priority"],
                )
                db.add(snap)

        except Exception as exc:
            logger.debug(f"PairMLAnalyzer: DB persist failed for {rec.get('symbol')}: {exc!r}")
