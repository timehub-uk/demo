"""
Token Metadata Collector  (Layer 2 – Module 14)
================================================
Tracks supply, unlocks, emission schedules, tax logic,
and contract metadata for tokens.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loguru import logger


@dataclass
class TokenMetadata:
    address: str
    symbol: str
    name: str
    decimals: int
    total_supply: float
    circulating_supply: float
    chain: str
    deployer: Optional[str] = None
    deploy_block: Optional[int] = None
    deploy_ts: Optional[float] = None
    has_mint: bool = False
    has_blacklist: bool = False
    has_pause: bool = False
    has_fee_on_transfer: bool = False
    buy_tax_pct: float = 0.0
    sell_tax_pct: float = 0.0
    verified: bool = False
    unlock_events: List[dict] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)


class TokenMetadataCollector:
    """
    Fetches and caches token metadata for safety analysis and signal generation.

    Sources:
    - On-chain RPC (decimals, supply, deployer)
    - Etherscan / BSCScan API (verification, source code flags)
    - Token unlock APIs (Tokenomist, Vesting contracts)

    Feature flag: 'contract_safety'
    """

    def __init__(self, rpc_urls: Optional[Dict[str, str]] = None,
                 explorer_api_key: Optional[str] = None):
        self._rpc_urls = rpc_urls or {}
        self._explorer_key = explorer_api_key
        self._cache: Dict[str, TokenMetadata] = {}
        self._lock = threading.RLock()
        self._callbacks: List[Callable[[TokenMetadata], None]] = []

    def on_update(self, callback: Callable[[TokenMetadata], None]) -> None:
        self._callbacks.append(callback)

    def get(self, address: str) -> Optional[TokenMetadata]:
        with self._lock:
            return self._cache.get(address.lower())

    def fetch(self, address: str, chain: str = "eth") -> Optional[TokenMetadata]:
        """Fetch metadata for a token address (sync, with cache)."""
        key = address.lower()
        with self._lock:
            cached = self._cache.get(key)
            if cached and (time.time() - cached.last_updated < 300):
                return cached

        meta = self._fetch_from_rpc(address, chain)
        if meta:
            with self._lock:
                self._cache[key] = meta
            for cb in self._callbacks:
                try:
                    cb(meta)
                except Exception:
                    pass
        return meta

    def get_cached_count(self) -> int:
        with self._lock:
            return len(self._cache)

    def _fetch_from_rpc(self, address: str, chain: str) -> Optional[TokenMetadata]:
        """
        Production: call web3 ERC-20 ABI methods + Etherscan API.
        Stub: returns synthetic metadata.
        """
        import random
        return TokenMetadata(
            address=address,
            symbol="TKN",
            name="Unknown Token",
            decimals=18,
            total_supply=1_000_000_000,
            circulating_supply=random.uniform(100_000_000, 900_000_000),
            chain=chain,
            deployer="0x" + "".join(random.choices("0123456789abcdef", k=40)),
            deploy_block=random.randint(15_000_000, 19_000_000),
            has_mint=random.random() < 0.3,
            has_blacklist=random.random() < 0.2,
            has_pause=random.random() < 0.15,
            has_fee_on_transfer=random.random() < 0.4,
            buy_tax_pct=random.uniform(0, 10),
            sell_tax_pct=random.uniform(0, 15),
            verified=random.random() < 0.7,
        )
