"""
Funding and Basis Collector  (Layer 2 – Module 11)
===================================================
Tracks perpetual funding rates, spot-perp basis, and
cash-and-carry conditions across exchanges.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loguru import logger


@dataclass
class FundingRecord:
    symbol: str
    funding_rate: float           # 8h rate
    annualised_rate: float        # = funding_rate * 3 * 365
    next_funding_ts: float
    mark_price: float
    index_price: float
    basis_pct: float              # (mark - index) / index * 100
    exchange: str = "binance"
    timestamp: float = field(default_factory=time.time)


class FundingBasisCollector:
    """
    Polls funding rates and spot-perp basis for perpetual contracts.
    Signals when carry conditions are extreme (high positive = crowded long,
    high negative = crowded short).

    Feature flag: 'ml_trading'
    """

    EXTREME_ANNUALISED_PCT = 50.0  # Alert threshold

    def __init__(self, client=None):
        self._client = client
        self._data: Dict[str, FundingRecord] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[FundingRecord], None]] = []

    def on_update(self, callback: Callable[[FundingRecord], None]) -> None:
        self._callbacks.append(callback)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="funding-collector"
        )
        self._thread.start()
        logger.info("[FundingCollector] Started")

    def stop(self) -> None:
        self._running = False

    def get(self, symbol: str) -> Optional[FundingRecord]:
        with self._lock:
            return self._data.get(symbol)

    def get_all(self) -> Dict[str, FundingRecord]:
        with self._lock:
            return dict(self._data)

    def get_extreme_funding(self, threshold_pct: float = 50.0) -> List[FundingRecord]:
        """Return symbols with extreme annualised funding rates."""
        with self._lock:
            return [
                r for r in self._data.values()
                if abs(r.annualised_rate) >= threshold_pct
            ]

    def get_best_carry(self, min_rate_pct: float = 20.0) -> List[FundingRecord]:
        """Return symbols where carry is positive (long perp, short spot)."""
        with self._lock:
            return sorted(
                [r for r in self._data.values() if r.annualised_rate >= min_rate_pct],
                key=lambda r: r.annualised_rate,
                reverse=True,
            )

    def _poll_loop(self) -> None:
        while self._running:
            self._fetch()
            time.sleep(60)

    def _fetch(self) -> None:
        if not self._client:
            return
        try:
            funding_info = None
            if hasattr(self._client, "futures_funding_rate"):
                funding_info = self._client.futures_funding_rate()
            elif hasattr(self._client, "get_funding_rate"):
                funding_info = self._client.get_funding_rate()

            if not funding_info:
                return

            mark_prices = {}
            if hasattr(self._client, "futures_mark_price"):
                try:
                    mp = self._client.futures_mark_price()
                    mark_prices = {item["symbol"]: item for item in (mp or [])}
                except Exception:
                    pass

            for item in (funding_info or []):
                sym = item.get("symbol", "")
                rate = float(item.get("fundingRate", 0))
                ann = rate * 3 * 365 * 100  # annualised %
                mp = mark_prices.get(sym, {})
                mark = float(mp.get("markPrice", 0))
                idx = float(mp.get("indexPrice", mark))
                basis = ((mark - idx) / idx * 100) if idx else 0.0

                rec = FundingRecord(
                    symbol=sym,
                    funding_rate=rate,
                    annualised_rate=ann,
                    next_funding_ts=float(item.get("nextFundingTime", 0)) / 1000,
                    mark_price=mark,
                    index_price=idx,
                    basis_pct=basis,
                )
                with self._lock:
                    self._data[sym] = rec
                for cb in self._callbacks:
                    try:
                        cb(rec)
                    except Exception:
                        pass

                if abs(ann) >= self.EXTREME_ANNUALISED_PCT:
                    logger.info(
                        f"[FundingCollector] Extreme funding {sym}: {ann:.1f}% ann"
                    )
        except Exception as exc:
            logger.debug(f"[FundingCollector] Fetch error: {exc}")
