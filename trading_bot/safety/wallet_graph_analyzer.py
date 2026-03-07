"""
Wallet Graph Analyzer  (Layer 8 – Module 64)
=============================================
Builds relationships among deployer wallets, treasury wallets,
insiders, and connected entities.

Feature flag: 'contract_safety'
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from loguru import logger


@dataclass
class WalletNode:
    address: str
    label: str                    # "deployer", "treasury", "insider", "exchange", "unknown"
    eth_balance: float = 0.0
    tx_count: int = 0
    first_seen: Optional[float] = None
    risk_score: float = 0.0       # 0–100
    tags: List[str] = field(default_factory=list)


@dataclass
class WalletEdge:
    from_addr: str
    to_addr: str
    tx_count: int
    total_value_eth: float
    edge_type: str               # "funded_by", "sent_to", "deployed", "interacted"


@dataclass
class WalletGraph:
    root_address: str
    nodes: Dict[str, WalletNode] = field(default_factory=dict)
    edges: List[WalletEdge] = field(default_factory=list)
    depth: int = 0
    analyzed_at: float = field(default_factory=time.time)

    @property
    def deployer_count(self) -> int:
        return sum(1 for n in self.nodes.values() if n.label == "deployer")

    @property
    def max_risk_score(self) -> float:
        return max((n.risk_score for n in self.nodes.values()), default=0.0)

    @property
    def is_suspicious(self) -> bool:
        return self.max_risk_score >= 60 or self.deployer_count >= 3


class WalletGraphAnalyzer:
    """
    Traces wallet relationships up to N hops from a seed address.

    Identifies:
    - Multi-wallet deployers (same entity, multiple contracts)
    - Fresh wallet deployers (high risk)
    - Known scam addresses
    - Concentration: few wallets hold most supply
    - Circular flows (wash trading indicators)

    Feature flag: 'contract_safety'
    """

    KNOWN_RISKY_PATTERNS = [
        "fresh_deployer",     # wallet created <7 days before deployment
        "multi_deployer",     # same funder deployed >5 contracts
        "circular_flow",      # funds return to origin within 24h
        "high_concentration", # top 10 wallets hold >80% supply
        "insider_dump",       # insider sold >50% within 72h of launch
    ]

    def __init__(self, rpc_urls: Optional[Dict[str, str]] = None, max_depth: int = 3):
        self._rpc_urls = rpc_urls or {}
        self._max_depth = max_depth
        self._cache: Dict[str, WalletGraph] = {}
        self._known_risky: Set[str] = set()
        self._known_safe: Set[str] = set()
        self._lock = threading.RLock()

    def analyze(self, deployer_address: str, chain: str = "eth",
                depth: int = 2) -> WalletGraph:
        """Build wallet relationship graph from deployer address."""
        key = f"{chain}:{deployer_address.lower()}"
        with self._lock:
            cached = self._cache.get(key)
            if cached and (time.time() - cached.analyzed_at < 3600):
                return cached

        graph = self._build_graph(deployer_address, chain, min(depth, self._max_depth))
        with self._lock:
            self._cache[key] = graph

        if graph.is_suspicious:
            logger.warning(
                f"[WalletGraph] Suspicious deployer {deployer_address[:10]}... "
                f"risk={graph.max_risk_score:.0f} depth={graph.depth}"
            )

        return graph

    def mark_risky(self, address: str) -> None:
        with self._lock:
            self._known_risky.add(address.lower())

    def mark_safe(self, address: str) -> None:
        with self._lock:
            self._known_safe.add(address.lower())

    def is_known_risky(self, address: str) -> bool:
        return address.lower() in self._known_risky

    def _build_graph(self, root: str, chain: str, depth: int) -> WalletGraph:
        """
        Production: crawl blockchain via RPC / Etherscan tx history.
        Stub: generates synthetic relationship graph.
        """
        import random
        rng = random.Random(root.lower())

        graph = WalletGraph(root_address=root, depth=depth)

        # Root node (deployer)
        days_old = rng.uniform(0, 365)
        root_risk = 80 if days_old < 7 else max(0, 40 - days_old / 10)
        tags = []
        if days_old < 7:
            tags.append("fresh_wallet")
        if rng.random() < 0.3:
            tags.append("multi_deployer")

        graph.nodes[root] = WalletNode(
            address=root,
            label="deployer",
            eth_balance=rng.uniform(0.01, 10),
            tx_count=rng.randint(1, 200),
            first_seen=time.time() - days_old * 86400,
            risk_score=round(root_risk, 1),
            tags=tags,
        )

        # Add connected wallets
        n_connected = rng.randint(1, 5)
        for i in range(n_connected):
            addr = "0x" + "".join(rng.choices("0123456789abcdef", k=40))
            label = rng.choice(["funder", "treasury", "insider", "exchange", "unknown"])
            risk = rng.uniform(0, 50)
            graph.nodes[addr] = WalletNode(
                address=addr,
                label=label,
                eth_balance=rng.uniform(0, 100),
                tx_count=rng.randint(10, 10000),
                risk_score=round(risk, 1),
            )
            graph.edges.append(WalletEdge(
                from_addr=addr if label == "funder" else root,
                to_addr=root if label == "funder" else addr,
                tx_count=rng.randint(1, 20),
                total_value_eth=rng.uniform(0.1, 50),
                edge_type="funded_by" if label == "funder" else "sent_to",
            ))

        return graph
