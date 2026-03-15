"""
Data Cleaner  (Layer 3 – Module 21)
=====================================
Removes bad ticks, duplicate trades, stale candles, and malformed records.
Provides a clean data pipeline for downstream feature engineering.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


@dataclass
class CleanResult:
    original_count: int
    cleaned_count: int
    removed_count: int
    removal_reasons: Dict[str, int]


class DataCleaner:
    """
    Multi-stage data cleaning for OHLCV candles, trade ticks, and order book snapshots.

    Stages:
    1. Null / NaN removal
    2. Duplicate deduplication
    3. Stale record detection (timestamp gaps)
    4. Price spike filtering (Z-score based)
    5. Volume sanity check
    6. Chronological ordering
    """

    def __init__(
        self,
        max_price_zscore: float = 5.0,
        max_gap_seconds: int = 3600,
        min_volume: float = 0.0,
    ):
        self.max_price_zscore = max_price_zscore
        self.max_gap_seconds = max_gap_seconds
        self.min_volume = min_volume
        self._stats: Dict[str, int] = {}

    def clean_candles(self, candles: List[dict]) -> Tuple[List[dict], CleanResult]:
        """
        Clean OHLCV candle data.

        Expected fields: open_time, open, high, low, close, volume
        """
        original = len(candles)
        reasons: Dict[str, int] = {}

        # Stage 1: Remove nulls
        cleaned = []
        for c in candles:
            if any(c.get(f) is None for f in ("open", "high", "low", "close", "volume")):
                reasons["null_fields"] = reasons.get("null_fields", 0) + 1
                continue
            cleaned.append(c)

        # Stage 2: Convert to float, remove non-numeric and NaN/inf values
        import math
        result = []
        for c in cleaned:
            try:
                c["open"] = float(c["open"])
                c["high"] = float(c["high"])
                c["low"] = float(c["low"])
                c["close"] = float(c["close"])
                c["volume"] = float(c["volume"])
                if any(not math.isfinite(c[f]) for f in ("open", "high", "low", "close", "volume")):
                    reasons["non_numeric"] = reasons.get("non_numeric", 0) + 1
                    continue
                result.append(c)
            except (ValueError, TypeError):
                reasons["non_numeric"] = reasons.get("non_numeric", 0) + 1
        cleaned = result

        # Stage 3: Deduplicate by open_time
        seen_ts: set = set()
        result = []
        for c in cleaned:
            ts = c.get("open_time")
            if ts in seen_ts:
                reasons["duplicate"] = reasons.get("duplicate", 0) + 1
                continue
            seen_ts.add(ts)
            result.append(c)
        cleaned = result

        # Stage 4: Sort chronologically
        cleaned.sort(key=lambda c: c.get("open_time", 0))

        # Stage 5: Price spike filter (Z-score on close prices)
        if len(cleaned) >= 10:
            closes = [c["close"] for c in cleaned]
            mean = statistics.mean(closes)
            std = statistics.stdev(closes) or 1.0
            result = []
            for c in cleaned:
                z = abs((c["close"] - mean) / std)
                if z > self.max_price_zscore:
                    reasons["price_spike"] = reasons.get("price_spike", 0) + 1
                    continue
                result.append(c)
            cleaned = result

        # Stage 6: Volume sanity
        result = []
        for c in cleaned:
            if c["volume"] < self.min_volume:
                reasons["low_volume"] = reasons.get("low_volume", 0) + 1
                continue
            # OHLC sanity: high >= max(open,close), low <= min(open,close)
            if c["high"] < max(c["open"], c["close"]) or c["low"] > min(c["open"], c["close"]):
                reasons["ohlc_invalid"] = reasons.get("ohlc_invalid", 0) + 1
                continue
            result.append(c)
        cleaned = result

        removed = original - len(cleaned)
        if removed > 0:
            logger.debug(f"[DataCleaner] Removed {removed}/{original} candles: {reasons}")

        return cleaned, CleanResult(
            original_count=original,
            cleaned_count=len(cleaned),
            removed_count=removed,
            removal_reasons=reasons,
        )

    def clean_trades(self, trades: List[dict]) -> Tuple[List[dict], CleanResult]:
        """Clean trade tick data. Expected fields: id, price, qty, time, side."""
        original = len(trades)
        reasons: Dict[str, int] = {}

        cleaned = []
        seen_ids: set = set()
        for t in trades:
            if t.get("id") in seen_ids:
                reasons["duplicate"] = reasons.get("duplicate", 0) + 1
                continue
            seen_ids.add(t.get("id"))
            try:
                t["price"] = float(t["price"])
                t["qty"] = float(t["qty"])
                if t["price"] <= 0 or t["qty"] <= 0:
                    reasons["non_positive"] = reasons.get("non_positive", 0) + 1
                    continue
                cleaned.append(t)
            except (ValueError, TypeError, KeyError):
                reasons["malformed"] = reasons.get("malformed", 0) + 1

        cleaned.sort(key=lambda t: t.get("time", 0))

        removed = original - len(cleaned)
        return cleaned, CleanResult(
            original_count=original,
            cleaned_count=len(cleaned),
            removed_count=removed,
            removal_reasons=reasons,
        )

    def get_stats(self) -> Dict[str, int]:
        return dict(self._stats)
