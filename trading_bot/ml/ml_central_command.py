"""
ML Central Command — Unified ML pipeline aggregator and signal hub.

Aggregates signals from every ML tool in the system into a single ranked
feed of "what's hot right now across all AI layers".

Architecture:
  Each ML tool feeds signals into the Central Command via feed().
  Central Command maintains a sliding-window store of recent signals
  (per symbol, per source), computes a weighted combined_score per symbol,
  and periodically broadcasts the ranked list to registered listeners.

Signal Sources and Weights:
  ensemble          1.5   — final ensemble aggregation
  signal_council    1.3   — vote-weighted multi-source council
  gap_up_watch      1.1   — price gap up detected (watch closely)
  gap_down_buy      1.1   — price gap down (BUY mean-reversion setup)
  accumulation      1.0   — stealth accumulation pattern
  breakout          1.0   — volume breakout stage 2–4
  large_candle      0.9   — rapid candle expansion event
  whale_watcher     0.9   — large institutional order flow
  trend_scanner     0.8   — multi-TF trend alignment
  market_pulse      0.7   — broad market momentum
  sentiment         0.6   — social/news sentiment
  predictor         1.0   — LSTM/Transformer ML model
  pair_ml_analyzer  0.7   — cross-pair cross-reference

Combined Score Formula:
  For each symbol, collect all signals within the TTL window.
  combined_score = Σ (source_weight × confidence) / normaliser
  normalised to 0–1 range.

Aggregated Signal (per symbol):
  combined_score   : 0–1 weighted aggregate across all sources
  signal_count     : how many ML tools have an active signal
  sources          : list of contributing source names
  dominant_signal  : most common signal type (BUY / WATCH / HOLD)
  max_confidence   : highest single-source confidence
  updated_at       : ISO timestamp

Refresh: BROADCAST_INTERVAL_SEC (default 30 s).
Signal TTL: SIGNAL_TTL_SEC (default 900 s = 15 min).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from loguru import logger
from utils.logger import get_intel_logger


# ── Configuration ──────────────────────────────────────────────────────────────
BROADCAST_INTERVAL_SEC = 30     # how often to recompute + broadcast rankings
SIGNAL_TTL_SEC         = 900    # signals older than 15 min are discarded
TOP_N_DEFAULT          = 30     # default number of top symbols to return

# Source weights: higher = more influence on combined_score
SOURCE_WEIGHTS: dict[str, float] = {
    "ensemble":         1.5,
    "signal_council":   1.3,
    "lstm_predictor":   1.0,
    "gap_down_buy":     1.1,
    "gap_up_watch":     1.1,
    "accumulation":     1.0,
    "breakout":         1.0,
    "large_candle_watch": 0.9,
    "whale_watcher":    0.9,
    "trend_scanner":    0.8,
    "market_pulse":     0.7,
    "sentiment":        0.6,
    "pair_ml_analyzer": 0.7,
}
DEFAULT_WEIGHT = 0.5


@dataclass
class RawSignal:
    """A single signal from one ML source for one symbol."""
    source:     str
    symbol:     str
    signal:     str        # "BUY" | "SELL" | "WATCH" | "HOLD"
    confidence: float      # 0–1
    note:       str        = ""
    ts:         float      = field(default_factory=time.monotonic)


@dataclass
class AggregatedSignal:
    """Combined signal view for one symbol across all ML sources."""
    symbol:          str
    combined_score:  float         # weighted aggregate 0–1
    signal_count:    int           # number of contributing sources
    sources:         list[str]     # names of contributing sources
    dominant_signal: str           # most common signal type
    max_confidence:  float         # highest single-source confidence
    buy_weight:      float         # total weighted confidence for BUY signals
    watch_weight:    float         # total weighted confidence for WATCH signals
    note:            str           = ""
    updated_at:      str           = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def rank_emoji(self) -> str:
        if self.combined_score >= 0.7:
            return "🚨"
        if self.combined_score >= 0.5:
            return "🔶"
        if self.combined_score >= 0.3:
            return "👁"
        return "·"


class MLCentralCommand:
    """
    Unified ML pipeline aggregator.

    All ML tools feed signals here via feed().  The command periodically
    reranks symbols by combined_score and broadcasts to UI + strategy layers.

    Usage::

        hub = MLCentralCommand()
        hub.on_update(my_callback)   # receives list[AggregatedSignal]
        hub.start()

        # ML tools push signals in:
        hub.feed("gap_up_watch", symbol="BTCUSDT", signal="WATCH", confidence=0.82)
        hub.feed("accumulation",  symbol="ETHUSDT", signal="BUY",   confidence=0.75)

        # Query top signals:
        top = hub.get_top_signals(20)
    """

    def __init__(self) -> None:
        self._intel   = get_intel_logger()
        self._lock    = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Raw signals store: symbol → list[RawSignal]
        self._raw: dict[str, list[RawSignal]] = defaultdict(list)

        # Aggregated results: symbol → AggregatedSignal
        self._aggregated: dict[str, AggregatedSignal] = {}

        # Callbacks fired after each rerank cycle
        self._update_callbacks: list[Callable[[list[AggregatedSignal]], None]] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    def feed(
        self,
        source:     str,
        symbol:     str,
        signal:     str,
        confidence: float,
        note:       str = "",
    ) -> None:
        """
        Ingest a signal from any ML tool.

        This is thread-safe and non-blocking — safe to call from any background thread.
        """
        sig = RawSignal(
            source     = source,
            symbol     = symbol.upper().strip(),
            signal     = signal.upper().strip(),
            confidence = float(max(0.0, min(1.0, confidence))),
            note       = note,
        )
        with self._lock:
            self._raw[sig.symbol].append(sig)

    def on_update(self, cb: Callable[[list[AggregatedSignal]], None]) -> None:
        """Register callback — called after each rerank cycle with the updated ranked list."""
        self._update_callbacks.append(cb)

    def get_top_signals(self, n: int = TOP_N_DEFAULT) -> list[AggregatedSignal]:
        """Return top-N aggregated signals sorted by combined_score descending."""
        with self._lock:
            return sorted(
                self._aggregated.values(),
                key=lambda s: -s.combined_score,
            )[:n]

    def get_signal(self, symbol: str) -> Optional[AggregatedSignal]:
        """Return the aggregated signal for a specific symbol, or None."""
        with self._lock:
            return self._aggregated.get(symbol.upper())

    def get_active_symbols(self) -> set[str]:
        """Return all symbols with at least one active signal in the window."""
        with self._lock:
            return set(self._aggregated.keys())

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="ml-central-command"
        )
        self._thread.start()
        self._intel.ml("MLCentralCommand", "Started — aggregating all ML pipeline signals")

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            t0 = time.monotonic()
            try:
                self._rerank_and_broadcast()
            except Exception as exc:
                logger.warning(f"MLCentralCommand error: {exc!r}")
            elapsed = time.monotonic() - t0
            time.sleep(max(1.0, BROADCAST_INTERVAL_SEC - elapsed))

    def _rerank_and_broadcast(self) -> None:
        now = time.monotonic()
        cutoff = now - SIGNAL_TTL_SEC

        new_aggregated: dict[str, AggregatedSignal] = {}

        with self._lock:
            # Prune stale signals
            for sym in list(self._raw.keys()):
                self._raw[sym] = [s for s in self._raw[sym] if s.ts >= cutoff]
                if not self._raw[sym]:
                    del self._raw[sym]

            symbols = list(self._raw.keys())
            raw_copy = {sym: list(sigs) for sym, sigs in self._raw.items()}

        # Compute aggregated score per symbol (outside lock)
        for sym in symbols:
            sigs = raw_copy[sym]
            if not sigs:
                continue

            total_weight = 0.0
            weighted_sum = 0.0
            buy_w  = 0.0
            watch_w = 0.0
            contributing_sources: list[str] = []
            signal_counts: dict[str, int] = {}
            max_conf = 0.0

            # Keep only the most recent signal per source
            latest_per_source: dict[str, RawSignal] = {}
            for s in sigs:
                if s.source not in latest_per_source or s.ts > latest_per_source[s.source].ts:
                    latest_per_source[s.source] = s

            for src, s in latest_per_source.items():
                w = SOURCE_WEIGHTS.get(src, DEFAULT_WEIGHT)
                weighted_sum += w * s.confidence
                total_weight += w
                contributing_sources.append(src)
                max_conf = max(max_conf, s.confidence)
                signal_counts[s.signal] = signal_counts.get(s.signal, 0) + 1
                if s.signal == "BUY":
                    buy_w += w * s.confidence
                elif s.signal == "WATCH":
                    watch_w += w * s.confidence

            if total_weight < 1e-9:
                continue

            combined_score = weighted_sum / total_weight   # normalised 0–1

            # Dominant signal = the one with the most source votes
            dominant = max(signal_counts, key=lambda k: signal_counts[k]) if signal_counts else "WATCH"

            # Build a short note from top contributors
            top_srcs = sorted(latest_per_source.values(), key=lambda s: -s.confidence)[:3]
            note = "  ·  ".join(
                f"{s.source}({s.signal} {s.confidence:.2f})" for s in top_srcs
            )

            new_aggregated[sym] = AggregatedSignal(
                symbol          = sym,
                combined_score  = round(combined_score, 4),
                signal_count    = len(contributing_sources),
                sources         = contributing_sources,
                dominant_signal = dominant,
                max_confidence  = round(max_conf, 4),
                buy_weight      = round(buy_w, 4),
                watch_weight    = round(watch_w, 4),
                note            = note,
            )

        with self._lock:
            self._aggregated = new_aggregated

        ranked = sorted(new_aggregated.values(), key=lambda s: -s.combined_score)

        if ranked:
            top3 = ", ".join(
                f"{r.symbol}({r.combined_score:.2f}×{r.signal_count})"
                for r in ranked[:3]
            )
            self._intel.ml(
                "MLCentralCommand",
                f"Ranked {len(ranked)} symbols — top: {top3}",
            )

        # Fire callbacks
        for cb in self._update_callbacks:
            try:
                cb(ranked)
            except Exception as exc:
                logger.warning(f"MLCentralCommand update callback error: {exc!r}")
