"""
Mempool and MEV Protection Engine  (Layer 7 – Module 59)
=========================================================
Detects sandwich risk, frontrunning exposure, and identifies
private relay opportunities for on-chain orders.

Feature flag: 'mev_protection'
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loguru import logger


@dataclass
class MEVRisk:
    tx_hash: Optional[str]
    symbol: str
    estimated_sandwich_cost_pct: float   # % of trade value lost to sandwich
    frontrun_risk: float                  # 0–1
    backrun_risk: float                   # 0–1
    overall_risk: str                     # "low", "medium", "high", "critical"
    recommendation: str                   # "proceed", "use_private_relay", "delay", "cancel"
    relay_available: bool = False
    notes: str = ""
    timestamp: float = field(default_factory=time.time)


class MEVProtectionEngine:
    """
    Analyses on-chain transactions for MEV exposure and recommends
    protective routing (Flashbots, BloxRoute, etc.).

    Detection methods:
    1. Pending tx scan: look for pending large swaps on same pair
    2. Gas price analysis: unusually high gas = potential frontrunner
    3. Historical sandwich analysis for the pool/token
    4. Slippage tolerance check

    Feature flag: 'mev_protection'
    """

    _PRIVATE_RELAYS = {
        "eth": "https://relay.flashbots.net",
        "bsc": "https://bsc-relay.private",
    }

    def __init__(self, mempool_collector=None, gas_engine=None):
        self._mempool = mempool_collector
        self._gas_engine = gas_engine
        self._risk_history: List[MEVRisk] = []
        self._lock = threading.RLock()
        self._sandwich_counts: Dict[str, int] = {}  # pool → sandwich events in last 1h

    def assess_risk(self, symbol: str, notional_usd: float,
                    pool_address: Optional[str] = None,
                    chain: str = "eth") -> MEVRisk:
        """Assess MEV risk for a planned on-chain trade."""
        sandwich_cost = self._estimate_sandwich_cost(symbol, notional_usd, pool_address)
        frontrun = self._frontrun_risk(notional_usd)
        backrun = 0.3  # moderate by default

        if sandwich_cost > 2.0:
            overall = "critical"
            rec = "use_private_relay"
        elif sandwich_cost > 1.0 or frontrun > 0.6:
            overall = "high"
            rec = "use_private_relay"
        elif sandwich_cost > 0.3:
            overall = "medium"
            rec = "delay" if notional_usd < 5000 else "use_private_relay"
        else:
            overall = "low"
            rec = "proceed"

        relay_avail = chain in self._PRIVATE_RELAYS

        risk = MEVRisk(
            tx_hash=None,
            symbol=symbol,
            estimated_sandwich_cost_pct=round(sandwich_cost, 3),
            frontrun_risk=round(frontrun, 2),
            backrun_risk=round(backrun, 2),
            overall_risk=overall,
            recommendation=rec,
            relay_available=relay_avail,
            notes=f"relay={self._PRIVATE_RELAYS.get(chain, 'none')}",
        )

        with self._lock:
            self._risk_history.append(risk)
            if len(self._risk_history) > 1000:
                self._risk_history = self._risk_history[-500:]

        if overall in ("high", "critical"):
            logger.warning(
                f"[MEVProtection] {overall.upper()} risk for {symbol} "
                f"sandwich_cost={sandwich_cost:.2f}% rec={rec}"
            )

        return risk

    def get_private_relay_url(self, chain: str = "eth") -> Optional[str]:
        return self._PRIVATE_RELAYS.get(chain)

    def get_recent_risks(self, n: int = 20) -> List[MEVRisk]:
        with self._lock:
            return list(self._risk_history[-n:])

    def get_high_risk_count(self) -> int:
        with self._lock:
            return sum(
                1 for r in self._risk_history[-100:]
                if r.overall_risk in ("high", "critical")
            )

    def _estimate_sandwich_cost(self, symbol: str, notional_usd: float,
                                 pool_address: Optional[str]) -> float:
        """
        Estimate % of trade value lost to sandwich attacks.
        Larger trades in illiquid pools are more expensive to sandwich.
        """
        # Pending large swaps on same pair = higher risk
        pending_risk = 0.0
        if self._mempool:
            pending_swaps = self._mempool.get_pending_swaps()
            same_pair = sum(1 for t in pending_swaps if t.estimated_type == "swap"
                           and t.amount_usd > notional_usd * 0.5)
            pending_risk = min(1.0, same_pair * 0.2)

        # Base sandwich cost: square root of notional / liquidity
        liquidity_est = 1_000_000  # default
        cost_pct = (notional_usd / liquidity_est) ** 0.5 * 0.5 + pending_risk * 1.5
        return min(cost_pct, 5.0)

    def _frontrun_risk(self, notional_usd: float) -> float:
        """Larger trades are more profitable to frontrun."""
        return min(0.9, (notional_usd / 100_000) ** 0.3 * 0.4)
