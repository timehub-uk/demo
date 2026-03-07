"""
Rug-Pull Probability Engine  (Layer 8 – Module 65)
====================================================
Scores launches based on contract risk, wallet behavior,
liquidity profile, and abnormal flow.

Aggregates signals from all other safety modules into a single score.

Feature flag: 'rugpull_score'
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger


@dataclass
class RugPullScore:
    address: str
    symbol: str
    chain: str
    probability: float              # 0.0 – 1.0
    risk_level: str                 # "low", "medium", "high", "critical"
    component_scores: Dict[str, float] = field(default_factory=dict)
    red_flags: List[str] = field(default_factory=list)
    green_flags: List[str] = field(default_factory=list)
    recommendation: str = "do_not_trade"
    analyzed_at: float = field(default_factory=time.time)

    @property
    def is_tradeable(self) -> bool:
        return self.risk_level in ("low", "medium") and self.probability < 0.4


class RugPullScorer:
    """
    Composite rug-pull probability scorer.

    Component weights:
    - Contract risk:        30%
    - Honeypot check:       25%
    - Liquidity lock:       20%
    - Wallet graph:         15%
    - Token metadata:       10%
    """

    COMPONENT_WEIGHTS = {
        "contract":   0.30,
        "honeypot":   0.25,
        "liquidity":  0.20,
        "wallet":     0.15,
        "metadata":   0.10,
    }

    RISK_LEVELS = [
        (0.0,  0.2,  "low",      "proceed_with_caution"),
        (0.2,  0.45, "medium",   "reduce_position_size"),
        (0.45, 0.70, "high",     "avoid"),
        (0.70, 1.01, "critical", "do_not_trade"),
    ]

    def __init__(
        self,
        contract_analyzer=None,
        honeypot_detector=None,
        liquidity_analyzer=None,
        wallet_analyzer=None,
        metadata_collector=None,
    ):
        self._contract = contract_analyzer
        self._honeypot = honeypot_detector
        self._liquidity = liquidity_analyzer
        self._wallet = wallet_analyzer
        self._metadata = metadata_collector

    def score(self, address: str, pool_address: Optional[str] = None,
              deployer_address: Optional[str] = None, symbol: str = "UNKNOWN",
              chain: str = "eth") -> RugPullScore:
        """Compute composite rug-pull probability."""
        components: Dict[str, float] = {}
        red_flags: List[str] = []
        green_flags: List[str] = []

        # Contract risk
        if self._contract:
            try:
                risk = self._contract.analyze(address, chain, symbol)
                components["contract"] = risk.risk_score / 100
                red_flags.extend(risk.flags)
                if risk.owner_renounced:
                    green_flags.append("owner_renounced")
            except Exception:
                components["contract"] = 0.5  # neutral if unavailable

        # Honeypot
        if self._honeypot:
            try:
                hp = self._honeypot.check(address, chain, symbol)
                if hp.is_honeypot:
                    components["honeypot"] = 1.0
                    red_flags.append("honeypot_detected")
                else:
                    components["honeypot"] = hp.sell_tax_pct / 100
            except Exception:
                components["honeypot"] = 0.5

        # Liquidity lock
        if self._liquidity and pool_address:
            try:
                liq = self._liquidity.analyze(pool_address, symbol, chain)
                components["liquidity"] = liq.risk_score / 100
                red_flags.extend(liq.flags)
                if liq.locked_pct >= 95:
                    green_flags.append(f"liquidity_{liq.locked_pct:.0f}pct_locked")
            except Exception:
                components["liquidity"] = 0.5

        # Wallet graph
        if self._wallet and deployer_address:
            try:
                graph = self._wallet.analyze(deployer_address, chain)
                components["wallet"] = graph.max_risk_score / 100
                if graph.is_suspicious:
                    red_flags.append("suspicious_deployer_wallet")
            except Exception:
                components["wallet"] = 0.5

        # Metadata
        if self._metadata:
            try:
                meta = self._metadata.fetch(address, chain)
                if meta:
                    meta_score = 0.0
                    if meta.has_mint:
                        meta_score += 0.3
                    if meta.has_blacklist:
                        meta_score += 0.2
                    if not meta.verified:
                        meta_score += 0.2
                    if meta.sell_tax_pct > 10:
                        meta_score += 0.3
                    components["metadata"] = min(1.0, meta_score)
            except Exception:
                components["metadata"] = 0.5

        # Fill missing with neutral
        for key in self.COMPONENT_WEIGHTS:
            if key not in components:
                components[key] = 0.5

        # Weighted sum
        probability = sum(
            components[k] * w for k, w in self.COMPONENT_WEIGHTS.items()
        )

        # Risk level + recommendation
        risk_level = "critical"
        recommendation = "do_not_trade"
        for lo, hi, level, rec in self.RISK_LEVELS:
            if lo <= probability < hi:
                risk_level = level
                recommendation = rec
                break

        result = RugPullScore(
            address=address,
            symbol=symbol,
            chain=chain,
            probability=round(probability, 3),
            risk_level=risk_level,
            component_scores={k: round(v, 3) for k, v in components.items()},
            red_flags=list(set(red_flags)),
            green_flags=list(set(green_flags)),
            recommendation=recommendation,
        )

        logger.info(
            f"[RugPull] {symbol} score={probability:.0%} level={risk_level} "
            f"flags={len(red_flags)}"
        )
        return result
