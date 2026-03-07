"""
DEX Market Data Collector  (Layer 2 – Module 8)
================================================
Collects pool pricing, swaps, LP changes, and routing data from
on-chain venues (Uniswap, PancakeSwap, Raydium, etc.).

Dependency activation:
  Requires: ETH_RPC_URL or BSC_RPC_URL or SOL_RPC_URL
  Auto-enables: dex_execution, mempool_watch
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


@dataclass
class PoolData:
    address: str
    token0: str
    token1: str
    reserve0: float
    reserve1: float
    price: float                  # token1 per token0
    liquidity_usd: float
    volume_24h: float = 0.0
    fee_tier: float = 0.003
    chain: str = "eth"
    dex: str = "uniswap_v2"
    last_swap_ts: float = field(default_factory=time.time)
    timestamp: float = field(default_factory=time.time)


@dataclass
class SwapEvent:
    pool_address: str
    token_in: str
    token_out: str
    amount_in: float
    amount_out: float
    price_impact: float
    tx_hash: str
    trader: str
    timestamp: float = field(default_factory=time.time)


class DEXMarketDataCollector:
    """
    Monitors on-chain DEX pools for pricing, swap events, and LP changes.

    Supported chains: ETH, BSC, Solana (pluggable via RPC)
    Feature flag: 'dex_execution'
    """

    def __init__(self, rpc_urls: Optional[Dict[str, str]] = None):
        self._rpc_urls = rpc_urls or {}
        self._pools: Dict[str, PoolData] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._swap_callbacks: List[Callable[[SwapEvent], None]] = []
        self._pool_callbacks: List[Callable[[PoolData], None]] = []
        self._watched_pools: List[str] = []

    def watch_pool(self, address: str, chain: str = "eth") -> None:
        with self._lock:
            if address not in self._watched_pools:
                self._watched_pools.append(address)
        logger.debug(f"[DEX-MDC] Watching pool {address} on {chain}")

    def on_swap(self, callback: Callable[[SwapEvent], None]) -> None:
        self._swap_callbacks.append(callback)

    def on_pool_update(self, callback: Callable[[PoolData], None]) -> None:
        self._pool_callbacks.append(callback)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="dex-mdc"
        )
        self._thread.start()
        logger.info("[DEX-MDC] Started")

    def stop(self) -> None:
        self._running = False

    def get_pool(self, address: str) -> Optional[PoolData]:
        with self._lock:
            return self._pools.get(address)

    def get_all_pools(self) -> Dict[str, PoolData]:
        with self._lock:
            return dict(self._pools)

    def get_best_price(self, token_in: str, token_out: str) -> Optional[float]:
        """Find best available price across all tracked pools."""
        with self._lock:
            candidates = [
                p for p in self._pools.values()
                if (p.token0 == token_in and p.token1 == token_out) or
                   (p.token1 == token_in and p.token0 == token_out)
            ]
        if not candidates:
            return None
        # Best price = highest liquidity
        best = max(candidates, key=lambda p: p.liquidity_usd)
        if best.token0 == token_in:
            return best.price
        return 1.0 / best.price if best.price else None

    def _poll_loop(self) -> None:
        while self._running:
            self._fetch_pools()
            time.sleep(15)

    def _fetch_pools(self) -> None:
        """
        Real implementation would call RPC nodes or subgraph APIs.
        Stub generates synthetic data for architecture completeness.
        """
        import random
        for addr in self._watched_pools:
            base_price = self._pools.get(addr, PoolData(
                addr, "TOKEN0", "USDT", 1e6, 1e6 * 0.5, 0.5,
                liquidity_usd=1_000_000
            )).price
            new_price = base_price * (1 + random.gauss(0, 0.001))
            pool = PoolData(
                address=addr,
                token0="TOKEN",
                token1="USDT",
                reserve0=1_000_000,
                reserve1=1_000_000 * new_price,
                price=new_price,
                liquidity_usd=1_000_000 * new_price,
            )
            with self._lock:
                self._pools[addr] = pool
            for cb in self._pool_callbacks:
                try:
                    cb(pool)
                except Exception:
                    pass

    @property
    def is_running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())
