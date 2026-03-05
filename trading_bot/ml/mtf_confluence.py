"""
Multi-Timeframe Confluence Filter.

A signal only passes if multiple timeframes agree on the direction.
This eliminates most false signals caused by noise on a single timeframe.

Timeframe weights (higher = more authoritative):
  1m  → weight 1
  5m  → weight 2
  15m → weight 3
  1h  → weight 5
  4h  → weight 8
  1d  → weight 13

Scoring:
  weighted_score = Σ(weight × signal_value)  where BUY=+1, SELL=-1, HOLD=0
  confluence_pct = weighted_score / max_possible_score

Signal passes if:
  - confluence_pct ≥ 0.45 for BUY (majority weighted agreement)
  - confluence_pct ≤ -0.45 for SELL
  - Otherwise → HOLD (conflicted)

The filter queries the predictor on each timeframe independently,
caches results for 2-5 minutes (matching bar close periods),
and returns a ConfluentSignal with a breakdown per timeframe.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from loguru import logger
from utils.logger import get_intel_logger


# ── Timeframe config ──────────────────────────────────────────────────────────

TIMEFRAME_WEIGHTS: dict[str, int] = {
    "1m":  1,
    "5m":  2,
    "15m": 3,
    "1h":  5,
    "4h":  8,
    "1d":  13,
}

# Cache TTL per timeframe (seconds)
TIMEFRAME_TTL: dict[str, int] = {
    "1m": 60, "5m": 300, "15m": 900,
    "1h": 3600, "4h": 14400, "1d": 86400,
}

ACTIVE_TIMEFRAMES = ["15m", "1h", "4h"]   # Default active set (balance speed vs depth)
MIN_CONFLUENCE    = 0.45                   # Must have ≥45% weighted agreement


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class TimeframeVote:
    timeframe: str
    signal: str          # BUY | SELL | HOLD
    confidence: float
    weight: int
    contribution: float  # Signed weighted contribution


@dataclass
class ConfluentSignal:
    symbol: str
    final_signal: str    # BUY | SELL | HOLD
    confluence_pct: float   # -1.0 to +1.0
    confidence: float
    votes: list[TimeframeVote] = field(default_factory=list)
    passes_filter: bool = False
    reject_reason: str = ""
    timestamp: str = ""

    @property
    def summary(self) -> str:
        votes_str = " | ".join(
            f"{v.timeframe}:{v.signal}({v.confidence:.0%})" for v in self.votes
        )
        return (f"MTF {self.symbol}: {self.final_signal} conf={self.confluence_pct:+.2f} "
                f"pass={self.passes_filter} [{votes_str}]")


# ── Confluence filter ─────────────────────────────────────────────────────────

class MTFConfluenceFilter:
    """
    Multi-timeframe signal confluence checker.

    Usage:
        mtf = MTFConfluenceFilter(predictor)
        result = mtf.check("BTCUSDT", primary_signal="BUY", timeframes=["15m","1h","4h"])
        if result.passes_filter:
            execute_trade(result.final_signal)
    """

    def __init__(self, predictor=None, token_ml_manager=None) -> None:
        self._predictor = predictor       # Universal MLPredictor
        self._token_ml  = token_ml_manager
        self._intel = get_intel_logger()
        self._cache: dict[str, tuple[float, dict]] = {}   # (timestamp, signal_dict)
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[ConfluentSignal], None]] = []

    def on_confluence(self, cb: Callable[[ConfluentSignal], None]) -> None:
        self._callbacks.append(cb)

    def check(
        self,
        symbol: str,
        primary_signal: str,
        primary_confidence: float = 0.0,
        timeframes: list[str] = ACTIVE_TIMEFRAMES,
        min_confluence: float = MIN_CONFLUENCE,
    ) -> ConfluentSignal:
        """
        Check if the primary_signal has multi-timeframe confluence support.
        Returns a ConfluentSignal with passes_filter=True if it does.
        """
        votes: list[TimeframeVote] = []
        max_weight = sum(TIMEFRAME_WEIGHTS.get(tf, 1) for tf in timeframes)
        weighted_sum = 0.0

        for tf in timeframes:
            weight = TIMEFRAME_WEIGHTS.get(tf, 1)
            signal_dict = self._get_signal(symbol, tf)
            sig  = signal_dict.get("signal") or signal_dict.get("action", "HOLD")
            conf = float(signal_dict.get("confidence", 0.5))

            value = +1.0 if sig == "BUY" else (-1.0 if sig == "SELL" else 0.0)
            contribution = value * weight * conf
            weighted_sum += contribution

            votes.append(TimeframeVote(
                timeframe=tf, signal=sig, confidence=conf,
                weight=weight, contribution=contribution,
            ))

        confluence_pct = weighted_sum / max(max_weight, 1)

        # Determine final signal from confluence
        if confluence_pct >= min_confluence:
            final = "BUY"
            conf_out = min(0.95, 0.5 + confluence_pct * 0.5)
        elif confluence_pct <= -min_confluence:
            final = "SELL"
            conf_out = min(0.95, 0.5 + abs(confluence_pct) * 0.5)
        else:
            final = "HOLD"
            conf_out = abs(confluence_pct)

        # Check if primary signal is aligned with confluence
        passes = (final == primary_signal) or (
            primary_signal == "BUY" and confluence_pct > 0
        ) or (
            primary_signal == "SELL" and confluence_pct < 0
        )

        reject_reason = ""
        if not passes:
            reject_reason = (
                f"MTF confluence conflict: primary={primary_signal} but "
                f"confluence={final} ({confluence_pct:+.2f})"
            )
        elif abs(confluence_pct) < min_confluence:
            passes = False
            reject_reason = f"MTF confluence too weak: {confluence_pct:+.2f} < ±{min_confluence}"

        result = ConfluentSignal(
            symbol=symbol, final_signal=final, confluence_pct=confluence_pct,
            confidence=conf_out, votes=votes,
            passes_filter=passes, reject_reason=reject_reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if passes:
            self._intel.ml("MTFConfluence",
                f"✅ {result.summary}")
        else:
            self._intel.ml("MTFConfluence",
                f"⛔ {result.summary} | {reject_reason}")

        for cb in self._callbacks:
            try:
                cb(result)
            except Exception:
                pass
        return result

    # ── Internal ───────────────────────────────────────────────────────

    def _get_signal(self, symbol: str, timeframe: str) -> dict:
        """Get (possibly cached) ML signal for symbol on a given timeframe."""
        cache_key = f"{symbol}:{timeframe}"
        ttl = TIMEFRAME_TTL.get(timeframe, 300)

        with self._lock:
            if cache_key in self._cache:
                ts, cached = self._cache[cache_key]
                if time.time() - ts < ttl:
                    return cached

        signal = self._fetch_signal(symbol, timeframe)
        with self._lock:
            self._cache[cache_key] = (time.time(), signal)
        return signal

    def _fetch_signal(self, symbol: str, timeframe: str) -> dict:
        """Fetch a fresh signal from the ML predictor for a specific timeframe."""
        # Try per-token model first
        if self._token_ml:
            try:
                task = self._token_ml.get_task(symbol)
                if task and task.is_trained:
                    from ml.data_collector import DataCollector
                    df = DataCollector.load_dataframe(symbol, timeframe, limit=60)
                    if not df.empty:
                        result = task.predict(df)
                        return {
                            "signal": result.get("signal", "HOLD"),
                            "confidence": result.get("confidence", 0.5),
                        }
            except Exception:
                pass

        # Fall back to universal predictor
        if self._predictor:
            try:
                result = self._predictor.predict(symbol, interval=timeframe)
                if result:
                    return {
                        "signal": result.get("action", "HOLD"),
                        "confidence": result.get("confidence", 0.5),
                    }
            except Exception:
                pass

        return {"signal": "HOLD", "confidence": 0.5}
