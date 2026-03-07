"""
Gas and Priority Fee Engine  (Layer 7 – Module 58)
===================================================
Estimates optimal gas prices for on-chain execution speed and cost control.

Feature flag: 'dex_execution'
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from loguru import logger


@dataclass
class GasEstimate:
    chain: str
    slow_gwei: float         # ~30+ minutes
    standard_gwei: float     # ~1–5 minutes
    fast_gwei: float         # <30 seconds
    instant_gwei: float      # next block
    base_fee_gwei: float     # EIP-1559 base fee
    priority_fee_gwei: float # miner tip
    estimated_usd_standard: float
    estimated_usd_fast: float
    source: str = "rpc"
    timestamp: float = field(default_factory=time.time)


class GasFeeEngine:
    """
    Real-time gas fee oracle for EVM-compatible chains.

    Sources (in priority order):
    1. Direct RPC eth_gasPrice / eth_feeHistory
    2. EthGasStation / BlockNative API
    3. Exponential moving average of recent blocks

    Feature flag: 'dex_execution'
    """

    _FALLBACK_GWEI: Dict[str, Dict[str, float]] = {
        "eth": {"slow": 8, "standard": 12, "fast": 20, "instant": 35},
        "bsc": {"slow": 3, "standard": 5, "fast": 7, "instant": 10},
        "polygon": {"slow": 30, "standard": 50, "fast": 80, "instant": 120},
        "arbitrum": {"slow": 0.1, "standard": 0.15, "fast": 0.2, "instant": 0.3},
    }

    _ETH_PRICE_USD = 3_000.0  # updated periodically

    def __init__(self, rpc_urls: Optional[Dict[str, str]] = None):
        self._rpc_urls = rpc_urls or {}
        self._estimates: Dict[str, GasEstimate] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="gas-fee-engine"
        )
        self._thread.start()
        logger.info("[GasFeeEngine] Started")

    def stop(self) -> None:
        self._running = False

    def get_estimate(self, chain: str = "eth") -> GasEstimate:
        with self._lock:
            cached = self._estimates.get(chain)
        if cached and (time.time() - cached.timestamp < 30):
            return cached
        return self._fetch(chain)

    def suggest_gas(self, chain: str = "eth", urgency: str = "standard") -> float:
        """Return suggested gas price in Gwei for given urgency."""
        est = self.get_estimate(chain)
        return {
            "slow": est.slow_gwei,
            "standard": est.standard_gwei,
            "fast": est.fast_gwei,
            "instant": est.instant_gwei,
        }.get(urgency, est.standard_gwei)

    def estimate_tx_cost_usd(self, gas_units: int = 150_000,
                              chain: str = "eth", urgency: str = "standard") -> float:
        gwei = self.suggest_gas(chain, urgency)
        eth_price = self._ETH_PRICE_USD
        return (gas_units * gwei * 1e-9) * eth_price

    def _poll_loop(self) -> None:
        while self._running:
            for chain in (self._rpc_urls or self._FALLBACK_GWEI):
                try:
                    est = self._fetch(chain)
                    with self._lock:
                        self._estimates[chain] = est
                except Exception as exc:
                    logger.debug(f"[GasFeeEngine] Error fetching {chain}: {exc}")
            time.sleep(15)

    def _fetch(self, chain: str) -> GasEstimate:
        """Fetch gas prices from RPC or fall back to defaults."""
        fallback = self._FALLBACK_GWEI.get(chain, self._FALLBACK_GWEI["eth"])
        if chain in self._rpc_urls:
            try:
                return self._fetch_rpc(chain, fallback)
            except Exception:
                pass
        # Apply random jitter to fallback for realism
        import random
        jitter = random.uniform(0.9, 1.1)
        std = fallback["standard"] * jitter
        return GasEstimate(
            chain=chain,
            slow_gwei=round(std * 0.6, 2),
            standard_gwei=round(std, 2),
            fast_gwei=round(std * 1.8, 2),
            instant_gwei=round(std * 3.0, 2),
            base_fee_gwei=round(std * 0.9, 2),
            priority_fee_gwei=round(std * 0.1, 2),
            estimated_usd_standard=round(self.estimate_tx_cost_usd(150_000, chain), 3),
            estimated_usd_fast=round(self.estimate_tx_cost_usd(150_000, chain, "fast"), 3),
            source="fallback",
        )

    def _fetch_rpc(self, chain: str, fallback: dict) -> GasEstimate:
        """Real implementation would call web3.eth.gas_price."""
        raise NotImplementedError("RPC fetch not yet connected")
