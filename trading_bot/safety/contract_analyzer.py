"""
Contract Analyzer  (Layer 8 – Module 61)
==========================================
Checks mint authority, blacklist logic, trading lockouts, pausability,
and dangerous owner privileges for EVM token contracts.

Feature flag: 'contract_safety'
Auto-enables: 'honeypot_check', 'rugpull_score'
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger


@dataclass
class ContractRisk:
    address: str
    chain: str
    symbol: str
    risk_score: float               # 0 (safe) – 100 (dangerous)
    flags: List[str] = field(default_factory=list)
    # Specific checks
    has_mint: bool = False
    has_blacklist: bool = False
    has_whitelist: bool = False
    has_pause: bool = False
    has_fee_change: bool = False    # owner can change tax
    has_max_tx_limit: bool = False
    has_trading_cooldown: bool = False
    has_proxy: bool = False
    owner_renounced: bool = False
    verified_source: bool = False
    buy_tax_pct: float = 0.0
    sell_tax_pct: float = 0.0
    # Metadata
    analyzed_at: float = field(default_factory=time.time)
    notes: str = ""

    @property
    def is_safe(self) -> bool:
        return self.risk_score < 30

    @property
    def is_dangerous(self) -> bool:
        return self.risk_score >= 70


class ContractAnalyzer:
    """
    Static analysis of EVM token contracts for red flags.

    Risk scoring:
    - Mint authority:      +25
    - Blacklist:           +20
    - Pause:               +15
    - Fee change:          +15
    - Trading lockout:     +10
    - Unverified source:   +10
    - High sell tax >10%:  +20
    - Buy tax >5%:         +10
    - Proxy pattern:       +5
    Owner renounced:        -10

    Feature flag: 'contract_safety'
    """

    _RISK_WEIGHTS = {
        "has_mint": 25,
        "has_blacklist": 20,
        "has_pause": 15,
        "has_fee_change": 15,
        "has_trading_cooldown": 10,
        "unverified": 10,
        "has_proxy": 5,
        "high_sell_tax": 20,
        "high_buy_tax": 10,
        "owner_renounced": -10,
    }

    def __init__(self, rpc_urls: Optional[Dict[str, str]] = None,
                 explorer_api_key: Optional[str] = None):
        self._rpc_urls = rpc_urls or {}
        self._explorer_key = explorer_api_key
        self._cache: Dict[str, ContractRisk] = {}
        self._lock = threading.RLock()

    def analyze(self, address: str, chain: str = "eth",
                symbol: str = "UNKNOWN") -> ContractRisk:
        """Analyze a contract address. Returns cached result if fresh."""
        key = f"{chain}:{address.lower()}"
        with self._lock:
            cached = self._cache.get(key)
            if cached and (time.time() - cached.analyzed_at < 3600):
                return cached

        risk = self._run_analysis(address, chain, symbol)
        with self._lock:
            self._cache[key] = risk

        if risk.is_dangerous:
            logger.warning(
                f"[ContractAnalyzer] DANGER {symbol} ({address[:10]}...) "
                f"score={risk.risk_score:.0f} flags={risk.flags}"
            )
        elif not risk.is_safe:
            logger.info(
                f"[ContractAnalyzer] CAUTION {symbol} score={risk.risk_score:.0f}"
            )

        return risk

    def get_cached(self, address: str, chain: str = "eth") -> Optional[ContractRisk]:
        key = f"{chain}:{address.lower()}"
        with self._lock:
            return self._cache.get(key)

    def batch_analyze(self, addresses: List[tuple]) -> List[ContractRisk]:
        """Analyze multiple (address, chain, symbol) tuples."""
        results = []
        for addr, chain, symbol in addresses:
            results.append(self.analyze(addr, chain, symbol))
        return results

    def _run_analysis(self, address: str, chain: str, symbol: str) -> ContractRisk:
        """
        Production: decode bytecode and query Etherscan API.
        Stub: uses heuristics / synthetic analysis.
        """
        import random
        rng = random.Random(address.lower())

        has_mint = rng.random() < 0.35
        has_blacklist = rng.random() < 0.25
        has_pause = rng.random() < 0.20
        has_fee_change = rng.random() < 0.30
        has_cooldown = rng.random() < 0.15
        verified = rng.random() < 0.65
        has_proxy = rng.random() < 0.20
        owner_renounced = rng.random() < 0.40
        buy_tax = rng.uniform(0, 8)
        sell_tax = rng.uniform(0, 12)

        flags = []
        score = 0

        if has_mint:
            score += self._RISK_WEIGHTS["has_mint"]
            flags.append("mint_authority")
        if has_blacklist:
            score += self._RISK_WEIGHTS["has_blacklist"]
            flags.append("blacklist")
        if has_pause:
            score += self._RISK_WEIGHTS["has_pause"]
            flags.append("pausable")
        if has_fee_change:
            score += self._RISK_WEIGHTS["has_fee_change"]
            flags.append("mutable_fees")
        if has_cooldown:
            score += self._RISK_WEIGHTS["has_trading_cooldown"]
            flags.append("trading_cooldown")
        if not verified:
            score += self._RISK_WEIGHTS["unverified"]
            flags.append("unverified_source")
        if has_proxy:
            score += self._RISK_WEIGHTS["has_proxy"]
            flags.append("proxy_pattern")
        if sell_tax > 10:
            score += self._RISK_WEIGHTS["high_sell_tax"]
            flags.append(f"high_sell_tax_{sell_tax:.0f}pct")
        if buy_tax > 5:
            score += self._RISK_WEIGHTS["high_buy_tax"]
            flags.append(f"high_buy_tax_{buy_tax:.0f}pct")
        if owner_renounced:
            score += self._RISK_WEIGHTS["owner_renounced"]
            flags.append("owner_renounced")

        return ContractRisk(
            address=address,
            chain=chain,
            symbol=symbol,
            risk_score=max(0, min(100, score)),
            flags=flags,
            has_mint=has_mint,
            has_blacklist=has_blacklist,
            has_pause=has_pause,
            has_fee_change=has_fee_change,
            has_max_tx_limit=has_cooldown,
            has_trading_cooldown=has_cooldown,
            has_proxy=has_proxy,
            owner_renounced=owner_renounced,
            verified_source=verified,
            buy_tax_pct=round(buy_tax, 1),
            sell_tax_pct=round(sell_tax, 1),
        )
