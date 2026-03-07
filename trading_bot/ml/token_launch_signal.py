"""
Token Launch Signal Engine  (Layer 5 – Module 43)
===================================================
Detects new pools, launch conditions, liquidity locks, deployer risk,
and early momentum for freshly launched tokens.

Integrates with: safety layer, mempool collector, DEX market data.

Feature flag: 'ml_trading'
Auto-enables: 'contract_safety', 'honeypot_check', 'rugpull_score'
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loguru import logger


@dataclass
class LaunchSignal:
    token_address: str
    symbol: str
    chain: str
    pool_address: str
    signal_strength: float      # 0–1
    direction: str              # "long", "avoid"
    entry_window_seconds: float # time window to act
    suggested_size_pct: float   # % of max position
    # Supporting metrics
    rugpull_probability: float
    honeypot: bool
    liquidity_usd: float
    liquidity_locked_pct: float
    deployer_risk: float
    momentum_score: float
    launch_age_minutes: float
    # Signal components
    flags: List[str] = field(default_factory=list)
    notes: str = ""
    timestamp: float = field(default_factory=time.time)

    @property
    def is_tradeable(self) -> bool:
        return (
            self.direction == "long" and
            not self.honeypot and
            self.rugpull_probability < 0.4 and
            self.signal_strength >= 0.5
        )


class TokenLaunchSignalEngine:
    """
    Combines safety checks, on-chain data, and momentum signals
    to generate actionable trade signals for new token launches.

    Pipeline:
    1. Detect new pool (from DEX MDC or mempool)
    2. Fetch token metadata
    3. Run safety gate: honeypot check, contract analysis
    4. Score rug-pull probability
    5. Assess initial liquidity and lock status
    6. Measure early price momentum
    7. Compute composite launch signal
    8. Emit signal if passes all thresholds

    Feature flag: 'ml_trading'
    """

    # Minimum thresholds
    MIN_LIQUIDITY_USD = 10_000
    MIN_LOCK_PCT = 50.0
    MAX_RUGPULL_PROB = 0.45
    MIN_MOMENTUM = 0.3

    def __init__(
        self,
        contract_analyzer=None,
        honeypot_detector=None,
        liquidity_analyzer=None,
        rugpull_scorer=None,
        metadata_collector=None,
    ):
        self._contract = contract_analyzer
        self._honeypot = honeypot_detector
        self._liq_analyzer = liquidity_analyzer
        self._rugpull = rugpull_scorer
        self._metadata = metadata_collector

        self._callbacks: List[Callable[[LaunchSignal], None]] = []
        self._recent_signals: List[LaunchSignal] = []
        self._lock = threading.RLock()

    def on_signal(self, callback: Callable[[LaunchSignal], None]) -> None:
        self._callbacks.append(callback)

    def analyze_launch(
        self,
        token_address: str,
        pool_address: str,
        symbol: str = "NEW",
        chain: str = "eth",
        deployer_address: Optional[str] = None,
        initial_liquidity_usd: float = 0.0,
        launch_age_minutes: float = 0.0,
    ) -> LaunchSignal:
        """Run full launch analysis pipeline and return signal."""
        flags = []
        notes_parts = []

        # 1. Honeypot check (hard gate)
        honeypot = False
        if self._honeypot:
            hp = self._honeypot.check(token_address, chain, symbol)
            honeypot = hp.is_honeypot
            if honeypot:
                flags.append("honeypot")

        # 2. Contract analysis
        contract_risk = 50.0
        if self._contract:
            cr = self._contract.analyze(token_address, chain, symbol)
            contract_risk = cr.risk_score
            flags.extend(cr.flags)

        # 3. Rug-pull scoring
        rugpull_prob = 0.5
        if self._rugpull:
            rp = self._rugpull.score(
                token_address, pool_address, deployer_address, symbol, chain
            )
            rugpull_prob = rp.probability
            flags.extend(rp.red_flags)

        # 4. Liquidity lock
        lock_pct = 0.0
        if self._liq_analyzer and pool_address:
            la = self._liq_analyzer.analyze(pool_address, symbol, chain)
            lock_pct = la.locked_pct

        # 5. Momentum score (synthetic / placeholder)
        import random
        rng = random.Random(token_address.lower())
        momentum = rng.uniform(0.2, 0.9)

        # 6. Composite signal strength
        raw_score = (
            (1 - rugpull_prob) * 0.35 +
            (1 - contract_risk / 100) * 0.25 +
            (lock_pct / 100) * 0.20 +
            momentum * 0.20
        )

        # 7. Apply hard gates
        if honeypot:
            direction = "avoid"
            raw_score = 0.0
            notes_parts.append("HONEYPOT – hard reject")
        elif rugpull_prob > self.MAX_RUGPULL_PROB:
            direction = "avoid"
            notes_parts.append(f"rug_prob too high ({rugpull_prob:.0%})")
        elif initial_liquidity_usd < self.MIN_LIQUIDITY_USD:
            direction = "avoid"
            notes_parts.append(f"low liquidity (${initial_liquidity_usd:,.0f})")
        elif lock_pct < self.MIN_LOCK_PCT:
            direction = "avoid"
            notes_parts.append(f"insufficient lock ({lock_pct:.0f}%)")
        else:
            direction = "long" if momentum >= self.MIN_MOMENTUM else "avoid"

        # Entry window (earlier = narrower window)
        entry_window = max(30, 300 - launch_age_minutes * 10)

        # Position sizing (inversely scale with risk)
        size_pct = max(0.0, (1 - rugpull_prob) * 5.0) if direction == "long" else 0.0

        signal = LaunchSignal(
            token_address=token_address,
            symbol=symbol,
            chain=chain,
            pool_address=pool_address,
            signal_strength=round(raw_score, 3),
            direction=direction,
            entry_window_seconds=entry_window,
            suggested_size_pct=round(size_pct, 2),
            rugpull_probability=round(rugpull_prob, 3),
            honeypot=honeypot,
            liquidity_usd=initial_liquidity_usd,
            liquidity_locked_pct=lock_pct,
            deployer_risk=contract_risk,
            momentum_score=round(momentum, 3),
            launch_age_minutes=launch_age_minutes,
            flags=list(set(flags)),
            notes=" | ".join(notes_parts),
        )

        with self._lock:
            self._recent_signals.append(signal)
            if len(self._recent_signals) > 500:
                self._recent_signals = self._recent_signals[-250:]

        if signal.is_tradeable:
            logger.info(
                f"[LaunchSignal] TRADEABLE {symbol} strength={raw_score:.2f} "
                f"rugpull={rugpull_prob:.0%} lock={lock_pct:.0f}%"
            )
            for cb in self._callbacks:
                try:
                    cb(signal)
                except Exception:
                    pass
        else:
            logger.debug(f"[LaunchSignal] REJECTED {symbol}: {signal.notes}")

        return signal

    def get_recent_signals(self, n: int = 20) -> List[LaunchSignal]:
        with self._lock:
            return list(self._recent_signals[-n:])

    def get_tradeable_signals(self) -> List[LaunchSignal]:
        with self._lock:
            return [s for s in self._recent_signals if s.is_tradeable]
