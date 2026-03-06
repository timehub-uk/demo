"""
Signal Council – Iterative Multi-Model Deliberation.

Instead of a single-pass vote, the council runs multiple deliberation
rounds where each model can revise its confidence based on what its peers said.

Protocol (3 rounds):
  Round 0  – Each model gives its initial independent signal
  Round 1  – Each model updates confidence based on peer consensus:
               - 3+ peers agree → +15% confidence boost
               - Majority disagrees → -10% confidence penalty
               - Strong veto signal present → -20%
  Round 2  – Final consensus vote on updated confidences
             with correlation dampening applied

Correlation dampening:
  LSTM + TokenML share the same underlying price data → their joint
  agreement is dampened to 70% to prevent double-counting.

Veto powers:
  - whale_signal at >0.85 confidence can veto opposite signals
  - Regime detector VOLATILE can veto all BUY/SELL signals

The council also tracks a "disagreement_score" – high disagreement
means the market is uncertain, and position size is reduced.

Usage:
    council = SignalCouncil()
    result = council.deliberate({
        "lstm_predictor": {"signal": "BUY",  "confidence": 0.68},
        "token_model":    {"signal": "BUY",  "confidence": 0.71},
        "whale_signal":   {"signal": "SELL", "confidence": 0.82},
        "sentiment":      {"signal": "BUY",  "confidence": 0.55},
        "mtf_confluence": {"signal": "BUY",  "confidence": 0.60},
    })
    # result.final_signal = "HOLD" (whale veto overrides weak buy consensus)
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from loguru import logger
from utils.logger import get_intel_logger

COUNCIL_WEIGHTS_FILE = Path(__file__).parent.parent / "data" / "council_weights.json"
COUNCIL_WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)

# Per-regime source confidence multiplier bounds and learning rate
COUNCIL_LR     = 0.05    # Same as ensemble learning rate
COUNCIL_W_MIN  = 0.50    # Floor: a source can lose at most half its influence
COUNCIL_W_MAX  = 2.00    # Ceiling: a source can at most double its influence

# Known regimes — the weights file may contain others, these are the defaults
_KNOWN_REGIMES = ("TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE", "UNKNOWN")

# ── Correlation groups (models within a group share data → dampen) ────────────

CORRELATION_GROUPS = [
    {"lstm_predictor", "token_model"},   # Both use OHLCV price data
    {"whale_signal", "order_flow"},      # Both observe order book / trades
]
CORRELATION_DAMPENING = 0.70   # Multiply joint weight by this when both in same group agree

# Veto thresholds
WHALE_VETO_THRESHOLD = 0.85    # Whale signal confidence to issue veto
REGIME_VOLATILE_VETO = True    # Regime=VOLATILE always vetoes

# Deliberation parameters
MAX_ROUNDS   = 3
PEER_BOOST   = 0.15    # Confidence boost when majority peers agree
PEER_PENALTY = 0.10    # Confidence penalty when majority peers disagree
MAX_CONF     = 0.95
MIN_CONF     = 0.20

# Council thresholds
BUY_THRESHOLD  = 0.52
SELL_THRESHOLD = 0.52
STRONG_SIGNAL  = 0.72   # Above this → reduce disagreement position penalty


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class CouncilMember:
    name: str
    signal: str           # BUY | SELL | HOLD
    confidence: float     # Before deliberation
    final_confidence: float  # After deliberation
    votes: list[str] = field(default_factory=list)  # Round-by-round log
    vetoed: bool = False


@dataclass
class CouncilDecision:
    final_signal: str             # BUY | SELL | HOLD
    final_confidence: float
    buy_pressure: float           # 0-1
    sell_pressure: float          # 0-1
    disagreement_score: float     # 0-1 (0=all agree, 1=completely split)
    position_size_mult: float     # Suggested position multiplier
    vetoed_by: str                # "" or source name that issued veto
    members: list[CouncilMember] = field(default_factory=list)
    rounds: int = 0
    timestamp: str = ""

    @property
    def summary(self) -> str:
        mem = " | ".join(
            f"{m.name}:{m.signal}({m.final_confidence:.0%})" for m in self.members
        )
        veto = f" [VETO:{self.vetoed_by}]" if self.vetoed_by else ""
        return (
            f"Council → {self.final_signal} conf={self.final_confidence:.0%} "
            f"disagree={self.disagreement_score:.2f} size×{self.position_size_mult:.2f}"
            f"{veto} | {mem}"
        )


# ── Signal council ────────────────────────────────────────────────────────────

class SignalCouncil:
    """
    Multi-round deliberation engine.
    Each model adjusts its confidence based on peers before final vote.
    Per-regime source weights adapt after every trade via record_outcome().
    """

    def __init__(self) -> None:
        self._intel = get_intel_logger()
        self._lock = threading.Lock()
        self._regime_weights: dict[str, dict[str, float]] = self._load_council_weights()

    def deliberate(
        self,
        signals: dict[str, dict],   # {source: {"signal": ..., "confidence": ...}}
        symbol: str = "",
        regime: str = "UNKNOWN",
    ) -> CouncilDecision:
        """
        Run multi-round deliberation and return a CouncilDecision.
        """
        if not signals:
            return self._empty_decision(symbol)

        # Load per-regime source multipliers for this regime
        regime_mults = self._regime_weights.get(regime, {})

        # Initialise members, applying any learned per-regime confidence multiplier
        members = []
        for src, d in signals.items():
            raw_conf = max(MIN_CONF, min(MAX_CONF, float(d.get("confidence", 0.5))))
            mult = regime_mults.get(src, 1.0)
            adj_conf = max(MIN_CONF, min(MAX_CONF, raw_conf * mult))
            members.append(CouncilMember(
                name=src,
                signal=d.get("signal") or d.get("action", "HOLD"),
                confidence=raw_conf,
                final_confidence=adj_conf,
            ))

        # ── Check for vetoes first ────────────────────────────────────
        veto_by = self._check_veto(members, regime)

        # ── Deliberation rounds ───────────────────────────────────────
        for round_num in range(MAX_ROUNDS):
            changed = self._deliberation_round(members, round_num)
            if not changed:
                break   # Converged

        # ── Apply correlation dampening ───────────────────────────────
        self._apply_correlation_dampening(members)

        # ── Final vote ────────────────────────────────────────────────
        buy_pressure, sell_pressure = self._compute_pressures(members)
        disagreement = self._compute_disagreement(members)
        decision = self._make_decision(
            members, buy_pressure, sell_pressure, disagreement,
            veto_by, symbol,
        )

        self._intel.ml("SignalCouncil", f"🏛️  {decision.summary}")
        return decision

    # ── Deliberation ───────────────────────────────────────────────────

    def _deliberation_round(self, members: list[CouncilMember], round_num: int) -> bool:
        """
        Each member observes the current vote distribution and updates confidence.
        Returns True if any member changed significantly.
        """
        buy_count  = sum(1 for m in members if m.signal == "BUY")
        sell_count = sum(1 for m in members if m.signal == "SELL")
        total = len(members)
        changed = False

        for member in members:
            old_conf = member.final_confidence
            direction = member.signal

            if direction == "HOLD":
                continue

            # Count how many peers agree
            peers_agree = (buy_count - 1) if direction == "BUY" else (sell_count - 1)
            peers_oppose = sell_count if direction == "BUY" else buy_count
            majority_agrees = peers_agree > (total / 2 - 1)
            majority_opposes = peers_oppose > (total / 2)

            if majority_agrees:
                # Consensus forms – boost confidence
                boost = PEER_BOOST * (1 + peers_agree / total)
                member.final_confidence = min(MAX_CONF, old_conf + boost)
                member.votes.append(f"R{round_num}: {direction}↑{boost:.2f}")
            elif majority_opposes:
                # Being outvoted – reduce confidence
                member.final_confidence = max(MIN_CONF, old_conf - PEER_PENALTY)
                member.votes.append(f"R{round_num}: {direction}↓{PEER_PENALTY:.2f}")
            else:
                member.votes.append(f"R{round_num}: {direction}~")

            if abs(member.final_confidence - old_conf) > 0.01:
                changed = True

        return changed

    def _apply_correlation_dampening(self, members: list[CouncilMember]) -> None:
        """Dampen confidence of correlated sources that agree (avoid double-counting)."""
        member_map = {m.name: m for m in members}
        for group in CORRELATION_GROUPS:
            group_members = [member_map[n] for n in group if n in member_map]
            if len(group_members) < 2:
                continue
            # If all in group agree on direction, dampen each
            signals = [m.signal for m in group_members if m.signal != "HOLD"]
            if signals and len(set(signals)) == 1:   # All agree
                for m in group_members:
                    m.final_confidence *= CORRELATION_DAMPENING
                    m.votes.append(f"corr-damp×{CORRELATION_DAMPENING}")

    # ── Veto logic ─────────────────────────────────────────────────────

    def _check_veto(self, members: list[CouncilMember], regime: str) -> str:
        """Return veto source name or empty string."""
        # Regime veto
        if REGIME_VOLATILE_VETO and regime == "VOLATILE":
            for m in members:
                m.vetoed = True
            return "REGIME_VOLATILE"

        # Whale veto
        whale = next((m for m in members if m.name == "whale_signal"), None)
        if whale and whale.confidence >= WHALE_VETO_THRESHOLD and whale.signal != "HOLD":
            # Veto everyone going the opposite direction
            opposite = "SELL" if whale.signal == "BUY" else "BUY"
            for m in members:
                if m.signal == opposite:
                    m.vetoed = True
                    m.final_confidence *= 0.3  # Slash confidence of vetoed signals
            return f"whale_signal:{whale.signal}@{whale.confidence:.0%}"

        return ""

    # ── Pressure + decision ────────────────────────────────────────────

    def _compute_pressures(self, members: list[CouncilMember]) -> tuple[float, float]:
        """Compute normalised buy/sell pressure from final member confidences."""
        buy_w = sum(
            m.final_confidence for m in members
            if m.signal == "BUY" and not m.vetoed
        )
        sell_w = sum(
            m.final_confidence for m in members
            if m.signal == "SELL" and not m.vetoed
        )
        total_w = sum(m.final_confidence for m in members if not m.vetoed) or 1.0
        return buy_w / total_w, sell_w / total_w

    def _compute_disagreement(self, members: list[CouncilMember]) -> float:
        """
        0 = perfect consensus, 1 = completely split.
        Based on entropy of the buy/sell/hold distribution.
        """
        counts = [0, 0, 0]  # BUY, SELL, HOLD
        for m in members:
            if m.signal == "BUY":
                counts[0] += 1
            elif m.signal == "SELL":
                counts[1] += 1
            else:
                counts[2] += 1
        total = sum(counts) or 1
        probs = [c / total for c in counts if c > 0]
        entropy = -sum(p * np.log2(p) for p in probs)
        max_entropy = np.log2(3)   # Log2(num classes)
        return float(entropy / max_entropy)

    def _make_decision(
        self, members: list[CouncilMember], buy_p: float, sell_p: float,
        disagreement: float, veto_by: str, symbol: str,
    ) -> CouncilDecision:
        if veto_by == "REGIME_VOLATILE":
            final = "HOLD"
            conf  = 0.0
        elif buy_p >= BUY_THRESHOLD and buy_p > sell_p:
            final = "BUY"
            conf  = min(MAX_CONF, buy_p * (1 - disagreement * 0.3))
        elif sell_p >= SELL_THRESHOLD and sell_p > buy_p:
            final = "SELL"
            conf  = min(MAX_CONF, sell_p * (1 - disagreement * 0.3))
        else:
            final = "HOLD"
            conf  = max(buy_p, sell_p)

        # Position size multiplier: reduce when high disagreement
        if final == "HOLD":
            size_mult = 0.0
        elif conf >= STRONG_SIGNAL:
            size_mult = 1.0
        else:
            # Scale from 0.4 to 1.0 based on confidence and disagreement
            size_mult = max(0.4, conf * (1 - disagreement * 0.5))

        return CouncilDecision(
            final_signal=final, final_confidence=conf,
            buy_pressure=buy_p, sell_pressure=sell_p,
            disagreement_score=disagreement,
            position_size_mult=size_mult,
            vetoed_by=veto_by, members=members,
            rounds=MAX_ROUNDS,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # ── Outcome feedback ───────────────────────────────────────────────

    def record_outcome(
        self,
        regime: str,
        correct_sources: list[str],
        wrong_sources: list[str],
    ) -> None:
        """
        Update per-regime source confidence multipliers after a trade closes.
        Sources that were correct get a 5% boost; sources that were wrong get a 5% cut.
        Multipliers are clamped to [COUNCIL_W_MIN, COUNCIL_W_MAX] and saved to disk.
        """
        if not correct_sources and not wrong_sources:
            return
        regime_key = regime or "UNKNOWN"
        with self._lock:
            mults = self._regime_weights.setdefault(regime_key, {})
            for src in correct_sources:
                old = mults.get(src, 1.0)
                mults[src] = min(COUNCIL_W_MAX, old * (1 + COUNCIL_LR))
            for src in wrong_sources:
                old = mults.get(src, 1.0)
                mults[src] = max(COUNCIL_W_MIN, old * (1 - COUNCIL_LR))
            self._save_council_weights()

        self._intel.ml("SignalCouncil",
            f"⚖️  Per-regime weights updated [{regime_key}] "
            f"correct={correct_sources} wrong={wrong_sources} "
            + " ".join(
                f"{s}={self._regime_weights.get(regime_key, {}).get(s, 1.0):.2f}"
                for s in correct_sources + wrong_sources
            ))

    # ── Weight persistence ─────────────────────────────────────────────

    def _load_council_weights(self) -> dict[str, dict[str, float]]:
        try:
            if COUNCIL_WEIGHTS_FILE.exists():
                return json.loads(COUNCIL_WEIGHTS_FILE.read_text())
        except Exception:
            pass
        return {}

    def _save_council_weights(self) -> None:
        try:
            COUNCIL_WEIGHTS_FILE.write_text(json.dumps(self._regime_weights, indent=2))
        except Exception:
            pass

    def _empty_decision(self, symbol: str) -> CouncilDecision:
        return CouncilDecision(
            final_signal="HOLD", final_confidence=0.0,
            buy_pressure=0.0, sell_pressure=0.0,
            disagreement_score=1.0, position_size_mult=0.0,
            vetoed_by="NO_SIGNALS", members=[],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
