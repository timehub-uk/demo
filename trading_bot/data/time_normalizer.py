"""
Time Normalisation Engine  (Layer 3 – Module 19)
=================================================
Synchronises timestamps across exchanges, chains, and external feeds.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from loguru import logger


class TimeNormalizer:
    """
    Converts and aligns timestamps from heterogeneous data sources.

    Sources:
    - Binance: milliseconds since epoch
    - Ethereum: seconds since epoch (block timestamps)
    - CoinGecko: ISO-8601 strings
    - Custom: various formats
    """

    _EXCHANGE_OFFSET: Dict[str, float] = {}  # measured clock drift per exchange

    def __init__(self):
        self._clock_offsets: Dict[str, float] = {}

    def to_utc_ms(self, ts: Any, source: str = "unknown") -> int:
        """Convert any timestamp format to UTC milliseconds."""
        offset = self._clock_offsets.get(source, 0.0)

        if isinstance(ts, (int, float)):
            # Auto-detect ms vs seconds
            if ts > 1e12:
                return int(ts + offset * 1000)
            else:
                return int(ts * 1000 + offset * 1000)

        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000 + offset * 1000)
            except ValueError:
                pass
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
            except ValueError:
                pass

        if isinstance(ts, datetime):
            return int(ts.timestamp() * 1000 + offset * 1000)

        logger.warning(f"[TimeNorm] Cannot parse timestamp: {ts!r} from {source}")
        return int(time.time() * 1000)

    def to_utc_seconds(self, ts: Any, source: str = "unknown") -> float:
        return self.to_utc_ms(ts, source) / 1000.0

    def to_datetime(self, ts: Any, source: str = "unknown") -> datetime:
        ms = self.to_utc_ms(ts, source)
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)

    def register_clock_offset(self, source: str, offset_seconds: float) -> None:
        """Register measured clock offset for a data source."""
        self._clock_offsets[source] = offset_seconds
        logger.debug(f"[TimeNorm] Clock offset {source}: {offset_seconds:+.3f}s")

    def align_series(
        self, series_a: List[dict], series_b: List[dict],
        ts_field: str = "timestamp", tolerance_ms: int = 500
    ) -> List[tuple]:
        """
        Align two time series by timestamp proximity.
        Returns list of (record_a, record_b) pairs.
        """
        result = []
        j = 0
        for rec_a in series_a:
            ts_a = self.to_utc_ms(rec_a[ts_field])
            best_b = None
            best_diff = tolerance_ms + 1
            for k in range(max(0, j - 2), min(len(series_b), j + 10)):
                ts_b = self.to_utc_ms(series_b[k][ts_field])
                diff = abs(ts_a - ts_b)
                if diff < best_diff:
                    best_diff = diff
                    best_b = series_b[k]
                    j = k
            if best_b is not None and best_diff <= tolerance_ms:
                result.append((rec_a, best_b))
        return result

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def now_s(self) -> float:
        return time.time()


# Singleton
_normalizer: Optional[TimeNormalizer] = None


def get_time_normalizer() -> TimeNormalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = TimeNormalizer()
    return _normalizer
