"""
Mempool Collector  (Layer 2 – Module 18)
=========================================
Captures pending transactions for early detection of:
- Large liquidity additions / removals
- Big swap attempts
- MEV sandwich setups
- Bridge inflows

Dependency activation:
  Requires: ETH_RPC_URL or BSC_RPC_URL
  Auto-enables: mev_protection
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loguru import logger


@dataclass
class PendingTx:
    tx_hash: str
    from_addr: str
    to_addr: str
    value_eth: float
    gas_price_gwei: float
    input_data: str
    estimated_type: str           # "swap", "add_lp", "remove_lp", "transfer", "unknown"
    token_in: Optional[str] = None
    token_out: Optional[str] = None
    amount_usd: float = 0.0
    timestamp: float = field(default_factory=time.time)


class MempoolCollector:
    """
    Monitors the blockchain mempool for high-value pending transactions.

    Connection: Ethereum/BSC full node with eth_subscribe("pendingTransactions")
    Falls back to polling pending tx pool if WebSocket unavailable.

    Feature flag: 'mempool_watch'
    Auto-activates: 'mev_protection' when sandwich-risk txs are detected
    """

    LARGE_TX_USD = 50_000  # Alert threshold

    def __init__(self, rpc_url: Optional[str] = None):
        self._rpc_url = rpc_url
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pending: Dict[str, PendingTx] = {}
        self._lock = threading.RLock()
        self._callbacks: List[Callable[[PendingTx], None]] = []
        self._large_tx_callbacks: List[Callable[[PendingTx], None]] = []

    def on_pending(self, callback: Callable[[PendingTx], None]) -> None:
        """Subscribe to all pending transactions."""
        self._callbacks.append(callback)

    def on_large_tx(self, callback: Callable[[PendingTx], None]) -> None:
        """Subscribe to large-value pending transactions only."""
        self._large_tx_callbacks.append(callback)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="mempool-collector"
        )
        self._thread.start()
        logger.info("[MempoolCollector] Started")

    def stop(self) -> None:
        self._running = False

    def get_pending_swaps(self) -> List[PendingTx]:
        with self._lock:
            return [t for t in self._pending.values() if t.estimated_type == "swap"]

    def get_large_pending(self, min_usd: float = 50_000) -> List[PendingTx]:
        with self._lock:
            return [t for t in self._pending.values() if t.amount_usd >= min_usd]

    def get_pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def _listen_loop(self) -> None:
        """
        Production: connect to eth_subscribe("newPendingTransactions") via WebSocket.
        Stub: generates synthetic mempool events at low rate.
        """
        import random, string
        while self._running:
            if self._rpc_url:
                self._try_rpc_connect()
            else:
                # Synthetic stub for development
                self._emit_synthetic(random)
            time.sleep(2)

    def _try_rpc_connect(self) -> None:
        """Attempt WebSocket connection to RPC node for real mempool data."""
        try:
            # Production: use web3.py eth_subscribe
            # from web3 import Web3
            # w3 = Web3(Web3.WebsocketProvider(self._rpc_url))
            # pending_filter = w3.eth.filter('pending')
            logger.debug("[MempoolCollector] RPC connection placeholder")
        except Exception as exc:
            logger.debug(f"[MempoolCollector] RPC error: {exc}")

    def _emit_synthetic(self, random_module) -> None:
        import random
        tx_hash = "0x" + "".join(random.choices("0123456789abcdef", k=64))
        amount = random.expovariate(1 / 5000)  # mostly small, some large
        tx_type = random.choices(
            ["swap", "add_lp", "remove_lp", "transfer", "unknown"],
            weights=[40, 20, 15, 20, 5],
        )[0]
        tx = PendingTx(
            tx_hash=tx_hash,
            from_addr="0x" + "".join(random.choices("0123456789abcdef", k=40)),
            to_addr="0x" + "".join(random.choices("0123456789abcdef", k=40)),
            value_eth=amount / 3000,
            gas_price_gwei=random.uniform(5, 100),
            input_data="0x",
            estimated_type=tx_type,
            amount_usd=amount,
        )
        with self._lock:
            self._pending[tx_hash] = tx
            # Keep buffer bounded
            if len(self._pending) > 500:
                oldest = list(self._pending.keys())[0]
                del self._pending[oldest]

        for cb in self._callbacks:
            try:
                cb(tx)
            except Exception:
                pass

        if tx.amount_usd >= self.LARGE_TX_USD:
            logger.info(
                f"[MempoolCollector] Large pending {tx_type} ${tx.amount_usd:,.0f}"
            )
            for cb in self._large_tx_callbacks:
                try:
                    cb(tx)
                except Exception:
                    pass
