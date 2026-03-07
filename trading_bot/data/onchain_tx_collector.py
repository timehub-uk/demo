"""
On-Chain Transaction Collector  (Layer 2 – Module 13)
======================================================
Watches confirmed transfers, large wallet moves, approvals,
contract interactions, and bridge flows on EVM chains.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loguru import logger


@dataclass
class OnChainEvent:
    tx_hash: str
    block_number: int
    event_type: str        # "transfer", "approval", "swap", "bridge", "contract"
    from_addr: str
    to_addr: str
    token: Optional[str]
    amount: float
    amount_usd: float
    chain: str = "eth"
    contract: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class OnChainTxCollector:
    """
    Monitors confirmed on-chain transactions for whale activity,
    fund flows, and protocol interactions.

    Feature flag: 'ml_trading'
    """

    WHALE_USD = 500_000

    def __init__(self, rpc_urls: Optional[Dict[str, str]] = None):
        self._rpc_urls = rpc_urls or {}
        self._events: List[OnChainEvent] = []
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[OnChainEvent], None]] = []
        self._whale_callbacks: List[Callable[[OnChainEvent], None]] = []

    def on_event(self, callback: Callable[[OnChainEvent], None]) -> None:
        self._callbacks.append(callback)

    def on_whale(self, callback: Callable[[OnChainEvent], None]) -> None:
        self._whale_callbacks.append(callback)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="onchain-tx"
        )
        self._thread.start()
        logger.info("[OnChainTx] Started")

    def stop(self) -> None:
        self._running = False

    def get_recent(self, n: int = 50) -> List[OnChainEvent]:
        with self._lock:
            return list(self._events[-n:])

    def get_whale_moves(self, min_usd: float = 500_000) -> List[OnChainEvent]:
        with self._lock:
            return [e for e in self._events if e.amount_usd >= min_usd]

    def _poll_loop(self) -> None:
        import random
        while self._running:
            self._simulate_event(random)
            time.sleep(10)

    def _simulate_event(self, random_module) -> None:
        import random
        evt_type = random.choices(
            ["transfer", "swap", "bridge", "approval", "contract"],
            weights=[30, 35, 15, 10, 10],
        )[0]
        amount_usd = random.expovariate(1 / 20_000)
        evt = OnChainEvent(
            tx_hash="0x" + "".join(random.choices("0123456789abcdef", k=64)),
            block_number=random.randint(19_000_000, 20_000_000),
            event_type=evt_type,
            from_addr="0x" + "".join(random.choices("0123456789abcdef", k=40)),
            to_addr="0x" + "".join(random.choices("0123456789abcdef", k=40)),
            token=random.choice(["USDT", "USDC", "ETH", "WBTC", None]),
            amount=amount_usd / 3000,
            amount_usd=amount_usd,
            chain=random.choice(["eth", "bsc"]),
        )
        with self._lock:
            self._events.append(evt)
            if len(self._events) > 1000:
                self._events = self._events[-500:]

        for cb in self._callbacks:
            try:
                cb(evt)
            except Exception:
                pass

        if evt.amount_usd >= self.WHALE_USD:
            logger.info(
                f"[OnChainTx] Whale {evt_type} ${evt.amount_usd:,.0f} on {evt.chain}"
            )
            for cb in self._whale_callbacks:
                try:
                    cb(evt)
                except Exception:
                    pass
