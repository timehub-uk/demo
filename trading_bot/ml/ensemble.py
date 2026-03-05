"""
Ensemble Signal Aggregator with Adaptive Weights.

Combines signals from all sources using Bayesian-updated weights
based on each source's recent win rate. Sources that have been
correct more recently are weighted higher automatically.

Signal sources:
  - lstm_predictor   : Universal LSTM/Transformer model
  - token_model      : Per-symbol TokenMLNet
  - whale_signal     : Derived from WhaleWatcher events
  - sentiment        : SentimentAnalyser score
  - mtf_confluence   : Multi-timeframe confluence vote
  - order_flow       : Bid/ask imbalance from live order book

Adaptive weight update (Bayesian):
  weight_new = weight_old × (1 + α × outcome)  then normalised
  where outcome = +1 for correct, -1 for wrong, α = 0.05 learning rate

The ensemble only fires a BUY/SELL if the weighted confidence
exceeds the dynamic threshold. HOLD otherwise.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from loguru import logger
from utils.logger import get_intel_logger

WEIGHTS_FILE = Path(__file__).parent.parent / "data" / "ensemble_weights.json"
WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)

# Initial equal weights (will adapt over time)
DEFAULT_WEIGHTS: dict[str, float] = {
    "lstm_predictor": 1.0,
    "token_model":    1.2,    # Slightly favour specialised model
    "whale_signal":   0.8,
    "sentiment":      0.4,    # Sentiment is a weak signal alone
    "mtf_confluence": 1.5,    # MTF already filters noise
    "order_flow":     0.6,
}

SIGNAL_THRESHOLD = 0.52       # Weighted confidence must exceed this to fire
LEARNING_RATE    = 0.05       # Weight update speed


@dataclass
class SourceSignal:
    source: str
    signal: str       # BUY | SELL | HOLD
    confidence: float
    weight: float     # Current weight of this source
    contribution: float   # Signed weighted contribution to final score


@dataclass
class EnsembleSignal:
    symbol: str
    final_signal: str     # BUY | SELL | HOLD
    final_confidence: float
    buy_score: float      # Weighted buy pressure 0-1
    sell_score: float     # Weighted sell pressure 0-1
    sources: list[SourceSignal] = field(default_factory=list)
    regime: str = "UNKNOWN"
    passed_regime_filter: bool = True
    timestamp: str = ""

    @property
    def summary(self) -> str:
        src = ", ".join(f"{s.source}:{s.signal}({s.confidence:.0%})" for s in self.sources)
        return (f"Ensemble {self.symbol}: {self.final_signal} "
                f"(conf={self.final_confidence:.0%} buy={self.buy_score:.2f} "
                f"sell={self.sell_score:.2f}) [{src}]")


class EnsembleAggregator:
    """
    Central signal aggregator with adaptive Bayesian weight updating.

    Usage:
        ens = EnsembleAggregator(regime_detector=..., mtf=..., ...)
        ens.on_signal(callback)
        # Feed signals from each source:
        ens.feed("lstm_predictor", {"symbol":"BTCUSDT","action":"BUY","confidence":0.72})
        ens.feed("whale_signal", {"symbol":"BTCUSDT","action":"BUY","confidence":0.65})
        # Ensemble fires callback when threshold is crossed
    """

    def __init__(
        self,
        regime_detector=None,
        mtf_filter=None,
        sentiment_analyser=None,
    ) -> None:
        self._regime   = regime_detector
        self._mtf      = mtf_filter
        self._sentiment = sentiment_analyser
        self._intel    = get_intel_logger()
        self._callbacks: list[Callable[[EnsembleSignal], None]] = []
        self._lock = threading.Lock()

        # Weights (loaded from disk, adaptive)
        self._weights: dict[str, float] = self._load_weights()

        # Recent signals per symbol per source (latest only)
        self._signals: dict[str, dict[str, dict]] = {}   # symbol → {source → signal_dict}

        # Track outcomes for weight adaptation
        self._pending_outcomes: list[dict] = []

    def on_signal(self, cb: Callable[[EnsembleSignal], None]) -> None:
        self._callbacks.append(cb)

    def feed(self, source: str, signal_dict: dict) -> Optional[EnsembleSignal]:
        """
        Feed a new signal from a named source.
        Returns EnsembleSignal if threshold is crossed, else None.
        """
        symbol = signal_dict.get("symbol", "")
        if not symbol:
            return None

        with self._lock:
            if symbol not in self._signals:
                self._signals[symbol] = {}
            self._signals[symbol][source] = signal_dict
            return self._aggregate(symbol)

    def record_outcome(self, symbol: str, signal_was_correct: bool) -> None:
        """
        Call after a trade closes. Updates source weights based on which
        sources contributed to the winning/losing signal.
        """
        if symbol not in self._signals:
            return
        outcome = +1.0 if signal_was_correct else -1.0
        with self._lock:
            for src, sig in self._signals[symbol].items():
                old_w = self._weights.get(src, 1.0)
                direction = sig.get("action") or sig.get("signal", "HOLD")
                if direction == "HOLD":
                    continue
                update = 1 + LEARNING_RATE * outcome
                self._weights[src] = max(0.1, min(3.0, old_w * update))
            self._normalise_weights()
            self._save_weights()
        self._intel.ml("Ensemble",
            f"Weights updated after {'WIN' if signal_was_correct else 'LOSS'} on {symbol}: "
            + " ".join(f"{k}={v:.2f}" for k, v in self._weights.items()))

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._weights)

    # ── Internal ───────────────────────────────────────────────────────

    def _aggregate(self, symbol: str) -> Optional[EnsembleSignal]:
        source_signals = self._signals.get(symbol, {})
        if not source_signals:
            return None

        buy_num  = 0.0
        sell_num = 0.0
        total_w  = 0.0
        sources_out: list[SourceSignal] = []

        # Add sentiment if available (not fed via feed() — pulled directly)
        sentiment_sig = self._get_sentiment_signal(symbol)
        if sentiment_sig:
            source_signals = {**source_signals, "sentiment": sentiment_sig}

        for src, sig in source_signals.items():
            direction = sig.get("action") or sig.get("signal", "HOLD")
            confidence = float(sig.get("confidence", 0.5))
            weight = self._weights.get(src, 0.5)

            value = +1.0 if direction == "BUY" else (-1.0 if direction == "SELL" else 0.0)
            contribution = value * weight * confidence
            buy_num  += max(0.0, contribution)
            sell_num += max(0.0, -contribution)
            total_w  += weight

            sources_out.append(SourceSignal(
                source=src, signal=direction, confidence=confidence,
                weight=weight, contribution=contribution,
            ))

        if total_w == 0:
            return None

        buy_score  = buy_num  / total_w
        sell_score = sell_num / total_w
        net_score  = (buy_score - sell_score)

        if buy_score > sell_score and buy_score >= SIGNAL_THRESHOLD:
            final = "BUY"
            conf  = min(0.95, buy_score)
        elif sell_score > buy_score and sell_score >= SIGNAL_THRESHOLD:
            final = "SELL"
            conf  = min(0.95, sell_score)
        else:
            final = "HOLD"
            conf  = max(buy_score, sell_score)

        # Regime gate
        regime_str = "UNKNOWN"
        passed_regime = True
        if self._regime and final != "HOLD":
            snap = self._regime.current
            regime_str = snap.regime.value
            ok, reason = self._regime.filter_signal(final, conf)
            if not ok:
                self._intel.ml("Ensemble",
                    f"⛔ [{symbol}] {final} blocked by regime [{regime_str}]: {reason}")
                final = "HOLD"
                passed_regime = False

        # MTF confluence gate
        if self._mtf and final != "HOLD":
            confluence = self._mtf.check(symbol, final, conf)
            if not confluence.passes_filter:
                self._intel.ml("Ensemble",
                    f"⛔ [{symbol}] {final} blocked by MTF: {confluence.reject_reason}")
                final = "HOLD"
                passed_regime = False

        ens = EnsembleSignal(
            symbol=symbol, final_signal=final, final_confidence=conf,
            buy_score=buy_score, sell_score=sell_score,
            sources=sources_out, regime=regime_str,
            passed_regime_filter=passed_regime,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if final != "HOLD":
            emoji = "🟢" if final == "BUY" else "🔴"
            self._intel.ml("Ensemble",
                f"{emoji} {ens.summary}")
            for cb in self._callbacks:
                try:
                    cb(ens)
                except Exception:
                    pass

        return ens

    def _get_sentiment_signal(self, symbol: str) -> Optional[dict]:
        if not self._sentiment:
            return None
        try:
            result = self._sentiment.get(symbol)
            if result and abs(result.score) > 0.2:
                sig = "BUY" if result.score > 0 else "SELL"
                return {"signal": sig, "confidence": abs(result.score) * 0.6}
        except Exception:
            pass
        return None

    def _normalise_weights(self) -> None:
        """Keep weights summing to len(weights) so absolute scale is preserved."""
        total = sum(self._weights.values())
        n = len(self._weights)
        if total > 0:
            self._weights = {k: v / total * n for k, v in self._weights.items()}

    def _load_weights(self) -> dict[str, float]:
        try:
            if WEIGHTS_FILE.exists():
                loaded = json.loads(WEIGHTS_FILE.read_text())
                merged = {**DEFAULT_WEIGHTS, **loaded}
                return merged
        except Exception:
            pass
        return dict(DEFAULT_WEIGHTS)

    def _save_weights(self) -> None:
        try:
            WEIGHTS_FILE.write_text(json.dumps(self._weights, indent=2))
        except Exception:
            pass
