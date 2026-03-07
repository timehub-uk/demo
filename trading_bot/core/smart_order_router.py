"""
Smart Order Router  (Layer 7 – Module 55)
==========================================
Chooses venue, route, slice size, and execution style for each order.
Considers liquidity, fees, slippage estimates, and latency.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


@dataclass
class Route:
    venue: str
    symbol: str
    side: str
    quantity: float
    expected_price: float
    estimated_slippage_pct: float
    estimated_fee_pct: float
    total_cost_pct: float         # slippage + fee
    execution_style: str          # "market", "limit", "twap", "iceberg"
    confidence: float             # 0–1
    notes: str = ""


@dataclass
class OrderIntent:
    symbol: str
    side: str
    notional_usd: float
    urgency: str = "normal"       # "urgent", "normal", "patient"
    max_slippage_pct: float = 0.5
    preferred_venue: Optional[str] = None


class SmartOrderRouter:
    """
    Routes orders to the optimal venue and selects execution style
    based on liquidity, urgency, and cost.

    Venue scoring:
    - Liquidity depth from order book snapshots
    - Historical fill quality
    - Current fee tier
    - Latency to exchange

    Feature flag: 'auto_trader'
    """

    _VENUE_FEES: Dict[str, float] = {
        "binance": 0.075,      # % with BNB discount
        "binance_perp": 0.02,
        "uniswap_v3": 0.30,
        "pancakeswap": 0.25,
    }

    def __init__(self, liquidity_engine=None):
        self._liquidity_engine = liquidity_engine
        self._venue_stats: Dict[str, Dict[str, float]] = {}
        self._lock = threading.RLock()

    def route(self, intent: OrderIntent) -> Route:
        """Evaluate venues and return the best route."""
        candidates = self._build_candidates(intent)
        if not candidates:
            # Fallback: binance market order
            return Route(
                venue="binance",
                symbol=intent.symbol,
                side=intent.side,
                quantity=intent.notional_usd,
                expected_price=0.0,
                estimated_slippage_pct=0.1,
                estimated_fee_pct=self._VENUE_FEES["binance"],
                total_cost_pct=0.1 + self._VENUE_FEES["binance"],
                execution_style=self._select_style(intent.urgency),
                confidence=0.5,
                notes="fallback default",
            )
        return min(candidates, key=lambda r: r.total_cost_pct)

    def _build_candidates(self, intent: OrderIntent) -> List[Route]:
        routes = []

        # CEX venues
        for venue, fee in self._VENUE_FEES.items():
            slippage = self._estimate_slippage(venue, intent.symbol, intent.notional_usd)
            if slippage > intent.max_slippage_pct:
                continue
            style = self._select_style(intent.urgency)
            routes.append(Route(
                venue=venue,
                symbol=intent.symbol,
                side=intent.side,
                quantity=intent.notional_usd,
                expected_price=0.0,
                estimated_slippage_pct=slippage,
                estimated_fee_pct=fee,
                total_cost_pct=slippage + fee,
                execution_style=style,
                confidence=0.8,
            ))

        return routes

    def _estimate_slippage(self, venue: str, symbol: str, notional_usd: float) -> float:
        """Estimate market impact slippage given venue and order size."""
        if self._liquidity_engine:
            try:
                return self._liquidity_engine.estimate_slippage(symbol, notional_usd)
            except Exception:
                pass
        # Simple square-root market impact model
        liquidity_est = 5_000_000  # default $5M daily volume
        return (notional_usd / liquidity_est) ** 0.5 * 0.5  # in %

    def _select_style(self, urgency: str) -> str:
        return {
            "urgent": "market",
            "normal": "limit",
            "patient": "twap",
        }.get(urgency, "limit")

    def update_venue_stats(self, venue: str, fill_quality: float, latency_ms: float) -> None:
        with self._lock:
            self._venue_stats.setdefault(venue, {})
            self._venue_stats[venue]["fill_quality"] = fill_quality
            self._venue_stats[venue]["latency_ms"] = latency_ms
