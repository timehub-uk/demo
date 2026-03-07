"""
Data Quality Auditor  (Layer 3 – Module 25)
============================================
Scores feed reliability, missingness, drift, and source confidence.
Provides a per-source quality report used by downstream models.
"""

from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger


@dataclass
class FeedQualityReport:
    source: str
    symbol: str
    completeness: float          # 0–1 fraction of expected records received
    freshness_sec: float         # seconds since last update
    price_drift_pct: float       # % price drift vs 1-hour MA
    outlier_rate: float          # fraction of records flagged as outliers
    confidence: float            # composite 0–1 score
    issues: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def is_healthy(self) -> bool:
        return self.confidence >= 0.7 and self.freshness_sec < 300


class DataQualityAuditor:
    """
    Continuously monitors incoming data feeds and produces quality scores.

    Thresholds (configurable):
    - Stale if no update in > 5 minutes
    - Low confidence if completeness < 80%
    - Drift alert if price moves > 5% vs 1h MA without corresponding volume
    """

    STALE_SECONDS = 300
    MIN_COMPLETENESS = 0.8
    MAX_DRIFT_PCT = 5.0
    MAX_OUTLIER_RATE = 0.05

    def __init__(self):
        self._reports: Dict[str, FeedQualityReport] = {}  # key: f"{source}:{symbol}"
        self._price_buffers: Dict[str, List[float]] = {}
        self._last_ts: Dict[str, float] = {}
        self._expected_intervals: Dict[str, float] = {}  # expected seconds between updates
        self._update_counts: Dict[str, int] = {}
        self._outlier_counts: Dict[str, int] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def register_feed(self, source: str, symbol: str, expected_interval_sec: float = 60.0) -> None:
        key = f"{source}:{symbol}"
        with self._lock:
            self._expected_intervals[key] = expected_interval_sec
            self._price_buffers.setdefault(key, [])
            self._update_counts[key] = 0
            self._outlier_counts[key] = 0

    def record_update(self, source: str, symbol: str, price: float,
                      is_outlier: bool = False) -> None:
        key = f"{source}:{symbol}"
        with self._lock:
            self._last_ts[key] = time.time()
            self._update_counts[key] = self._update_counts.get(key, 0) + 1
            if is_outlier:
                self._outlier_counts[key] = self._outlier_counts.get(key, 0) + 1
            buf = self._price_buffers.setdefault(key, [])
            buf.append(price)
            if len(buf) > 60:
                self._price_buffers[key] = buf[-60:]

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._audit_loop, daemon=True, name="data-quality-auditor"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def get_report(self, source: str, symbol: str) -> Optional[FeedQualityReport]:
        key = f"{source}:{symbol}"
        with self._lock:
            return self._reports.get(key)

    def get_all_reports(self) -> Dict[str, FeedQualityReport]:
        with self._lock:
            return dict(self._reports)

    def get_unhealthy_feeds(self) -> List[FeedQualityReport]:
        with self._lock:
            return [r for r in self._reports.values() if not r.is_healthy]

    def _audit_loop(self) -> None:
        while self._running:
            self._run_audit()
            time.sleep(60)

    def _run_audit(self) -> None:
        now = time.time()
        with self._lock:
            keys = list(self._expected_intervals.keys())

        for key in keys:
            source, symbol = key.split(":", 1)
            with self._lock:
                last = self._last_ts.get(key, 0)
                interval = self._expected_intervals.get(key, 60)
                total = self._update_counts.get(key, 0)
                outliers = self._outlier_counts.get(key, 0)
                prices = list(self._price_buffers.get(key, []))

            freshness = now - last if last else 9999.0
            issues = []

            # Completeness: rough ratio of received vs expected updates
            expected_total = max(1, int((now - (last - interval * total)) / interval))
            completeness = min(1.0, total / max(1, expected_total))

            # Price drift
            drift_pct = 0.0
            if len(prices) >= 10:
                ma = statistics.mean(prices[-10:])
                current = prices[-1]
                drift_pct = abs((current - ma) / ma * 100) if ma else 0.0

            # Outlier rate
            outlier_rate = outliers / max(1, total)

            if freshness > self.STALE_SECONDS:
                issues.append(f"stale ({freshness:.0f}s)")
            if completeness < self.MIN_COMPLETENESS:
                issues.append(f"low completeness ({completeness:.0%})")
            if drift_pct > self.MAX_DRIFT_PCT:
                issues.append(f"price drift {drift_pct:.1f}%")
            if outlier_rate > self.MAX_OUTLIER_RATE:
                issues.append(f"high outlier rate {outlier_rate:.0%}")

            confidence = (
                (1.0 if freshness < self.STALE_SECONDS else 0.0) * 0.4 +
                completeness * 0.3 +
                (1.0 - min(1.0, outlier_rate / self.MAX_OUTLIER_RATE)) * 0.2 +
                (1.0 - min(1.0, drift_pct / self.MAX_DRIFT_PCT)) * 0.1
            )

            report = FeedQualityReport(
                source=source,
                symbol=symbol,
                completeness=completeness,
                freshness_sec=freshness,
                price_drift_pct=drift_pct,
                outlier_rate=outlier_rate,
                confidence=round(confidence, 3),
                issues=issues,
            )
            with self._lock:
                self._reports[key] = report

            if issues:
                logger.debug(f"[DataAuditor] {key} issues: {', '.join(issues)}")
