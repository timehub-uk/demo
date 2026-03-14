"""
Strategy Manager – Multi-Strategy Orchestrator with ML-Driven Selection.

Manages a portfolio of trading strategies and uses the ML ensemble + regime
detector to select the best-performing strategy for current market conditions.

Strategies available:
  - trend_follow   : Ride strong directional moves (TRENDING_UP / TRENDING_DOWN)
  - mean_revert    : Buy dips / sell rallies inside a range (RANGING)
  - ping_pong      : Tight buy/sell between channel high and low (RANGING / VOLATILE)
  - momentum       : Breakout + volume confirmation (any high-confidence regime)
  - sentiment      : News/social sentiment-driven contrarian or trend trades
  - ml_pure        : Pure ML ensemble signal, no overlay strategy

ML Selection logic:
  Every EVAL_INTERVAL_SEC seconds the selector scores each strategy using:
    score = win_rate × avg_rr × regime_fit × recent_momentum
  The highest-scoring strategy for the current regime becomes the ACTIVE strategy.

  Regime fit matrix:
    TRENDING_UP    →  trend_follow (0.9), momentum (0.8), ping_pong (0.2)
    TRENDING_DOWN  →  trend_follow (0.9), momentum (0.7), ping_pong (0.2)
    RANGING        →  ping_pong   (0.9), mean_revert (0.8), trend_follow (0.3)
    VOLATILE       →  momentum    (0.7), ping_pong (0.6), ml_pure (0.5)

Each strategy emits trade signals; only the ACTIVE strategy's signals are
forwarded to the TradingEngine and AutoTrader.

Thread model:
  - Background evaluator thread runs every EVAL_INTERVAL_SEC.
  - Emits strategy_changed callbacks when the active strategy changes.
  - All mutations protected by a lock.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

from loguru import logger
from utils.logger import get_intel_logger


# ── Constants ──────────────────────────────────────────────────────────────────

EVAL_INTERVAL_SEC = 60        # Re-evaluate strategy every minute
MIN_TRADES_FOR_SCORE = 3      # Need at least this many trades to score reliably
DEFAULT_WIN_RATE = 0.52       # Assumed win rate for new strategies


# ── Regime fit matrix ──────────────────────────────────────────────────────────

REGIME_FIT: dict[str, dict[str, float]] = {
    "TRENDING_UP":   {"trend_follow": 0.9, "momentum": 0.8, "ml_pure": 0.7,
                      "sentiment": 0.6, "mean_revert": 0.3, "ping_pong": 0.2},
    "TRENDING_DOWN": {"trend_follow": 0.9, "momentum": 0.7, "ml_pure": 0.7,
                      "sentiment": 0.6, "mean_revert": 0.3, "ping_pong": 0.2},
    "RANGING":       {"ping_pong": 0.9, "mean_revert": 0.8, "ml_pure": 0.5,
                      "sentiment": 0.5, "momentum": 0.3, "trend_follow": 0.3},
    "VOLATILE":      {"momentum": 0.7, "ping_pong": 0.6, "ml_pure": 0.6,
                      "trend_follow": 0.4, "mean_revert": 0.3, "sentiment": 0.5},
    "UNKNOWN":       {"ml_pure": 0.8, "trend_follow": 0.5, "momentum": 0.5,
                      "ping_pong": 0.4, "mean_revert": 0.4, "sentiment": 0.4},
}

ALL_STRATEGIES = ["trend_follow", "mean_revert", "ping_pong", "momentum", "sentiment", "ml_pure"]


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class StrategyStats:
    name: str
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    total_rr: float = 0.0          # Sum of R:R ratios for completed trades
    recent_wins: int = 0           # Last 10 trades
    recent_losses: int = 0
    last_used: str = ""

    @property
    def total_trades(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        if self.total_trades < MIN_TRADES_FOR_SCORE:
            return DEFAULT_WIN_RATE
        return self.wins / self.total_trades

    @property
    def avg_rr(self) -> float:
        if self.total_trades == 0:
            return 1.0
        return self.total_rr / max(1, self.total_trades)

    @property
    def recent_win_rate(self) -> float:
        recent_total = self.recent_wins + self.recent_losses
        if recent_total == 0:
            return self.win_rate
        return self.recent_wins / recent_total


@dataclass
class StrategyScore:
    name: str
    score: float
    regime_fit: float
    win_rate: float
    avg_rr: float
    recent_momentum: float


@dataclass
class StrategySelection:
    active_strategy: str
    regime: str
    scores: list[StrategyScore]
    switched_from: Optional[str]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def summary(self) -> str:
        top = sorted(self.scores, key=lambda s: -s.score)[:3]
        top_str = "  ".join(f"{s.name}={s.score:.2f}" for s in top)
        return (f"Active: {self.active_strategy} | Regime: {self.regime} | "
                f"Top scores: {top_str}")


class StrategyManager:
    """
    Orchestrates multiple trading strategies, using ML + regime to select
    the best one for current conditions.

    Usage:
        mgr = StrategyManager(regime_detector=rd, ensemble=ens, trade_journal=tj)
        mgr.on_strategy_changed(my_callback)
        mgr.start()
        # Query which strategy is currently active:
        mgr.active_strategy    # → "trend_follow"
        # Record a trade result for learning:
        mgr.record_trade_result("trend_follow", pnl=0.05, rr=2.1)
    """

    def __init__(
        self,
        regime_detector=None,
        ensemble=None,
        trade_journal=None,
        ping_pong_trader=None,
    ) -> None:
        self._regime    = regime_detector
        self._ensemble  = ensemble
        self._journal   = trade_journal
        self._pp        = ping_pong_trader
        self._intel     = get_intel_logger()

        self._active: str = "ml_pure"          # Default strategy
        self._stats: dict[str, StrategyStats] = {
            name: StrategyStats(name=name) for name in ALL_STRATEGIES
        }
        self._last_selection: Optional[StrategySelection] = None
        self._manual_override: Optional[str] = None   # Overrides auto-selection
        self._running = False
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._change_cbs: list[Callable[[StrategySelection], None]] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def active_strategy(self) -> str:
        return self._manual_override or self._active

    @property
    def all_stats(self) -> dict[str, StrategyStats]:
        with self._lock:
            return dict(self._stats)

    @property
    def last_selection(self) -> Optional[StrategySelection]:
        return self._last_selection

    def on_strategy_changed(self, cb: Callable[[StrategySelection], None]) -> None:
        self._change_cbs.append(cb)

    def set_manual_override(self, strategy: Optional[str]) -> None:
        """
        Force a specific strategy regardless of ML scoring.
        Pass None to return to auto-selection.
        """
        if strategy and strategy not in ALL_STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy}. Use one of {ALL_STRATEGIES}")
        with self._lock:
            self._manual_override = strategy
        if strategy:
            self._intel.ml("StrategyManager", f"Manual override → {strategy}")
        else:
            self._intel.ml("StrategyManager", "Manual override cleared – resuming auto-selection")

    def record_trade_result(
        self,
        strategy: str,
        pnl: float,
        rr: float = 1.0,
    ) -> None:
        """
        Inform the strategy manager of a trade result so scores can be updated.
        Call this whenever a trade completes.
        """
        if strategy not in self._stats:
            return
        with self._lock:
            s = self._stats[strategy]
            if pnl > 0:
                s.wins += 1
                s.recent_wins += 1
            else:
                s.losses += 1
                s.recent_losses += 1
            s.total_pnl += pnl
            s.total_rr  += max(0, rr)
            s.last_used  = datetime.now(timezone.utc).isoformat()
            # Decay recent window
            total_recent = s.recent_wins + s.recent_losses
            if total_recent > 10:
                decay = total_recent - 10
                ratio = s.recent_wins / total_recent
                s.recent_wins   = round(10 * ratio)
                s.recent_losses = 10 - s.recent_wins

    def evaluate_now(self) -> StrategySelection:
        """Force an immediate re-evaluation and return the result."""
        return self._evaluate()

    # ── Control ────────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="strategy-manager"
        )
        self._thread.start()
        self._intel.ml("StrategyManager", "Started – auto-selecting best strategy")

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        # Initial evaluation after a short delay
        time.sleep(5)
        while self._running:
            try:
                self._evaluate()
            except Exception as exc:
                logger.warning(f"StrategyManager eval error: {exc}")
            time.sleep(EVAL_INTERVAL_SEC)

    # ── Scoring ────────────────────────────────────────────────────────────────

    def _evaluate(self) -> StrategySelection:
        regime = self._current_regime()
        fit_map = REGIME_FIT.get(regime, REGIME_FIT["UNKNOWN"])

        scores: list[StrategyScore] = []
        with self._lock:
            for name in ALL_STRATEGIES:
                st = self._stats[name]
                regime_fit      = fit_map.get(name, 0.4)
                win_rate        = st.win_rate
                avg_rr          = min(3.0, st.avg_rr)           # cap at 3:1
                recent_momentum = st.recent_win_rate

                # Composite score
                score = (
                    regime_fit      * 0.40 +
                    win_rate        * 0.30 +
                    (avg_rr / 3.0)  * 0.20 +
                    recent_momentum * 0.10
                )
                scores.append(StrategyScore(
                    name=name, score=score,
                    regime_fit=regime_fit, win_rate=win_rate,
                    avg_rr=avg_rr, recent_momentum=recent_momentum,
                ))

        scores.sort(key=lambda s: -s.score)
        if not scores:
            return self._last_selection or StrategySelection(
                active_strategy=self._active, regime=regime, scores=[], switched_from=None
            )
        best = scores[0].name

        old = self._active
        switched = best != old
        with self._lock:
            self._active = best

        selection = StrategySelection(
            active_strategy=best,
            regime=regime,
            scores=scores,
            switched_from=old if switched else None,
        )
        self._last_selection = selection

        if switched:
            self._intel.ml("StrategyManager",
                f"Strategy switched: {old} → {best}  (regime={regime})")
            for cb in self._change_cbs:
                try:
                    cb(selection)
                except Exception:
                    pass
        else:
            self._intel.ml("StrategyManager",
                f"Strategy confirmed: {best}  (regime={regime}  score={scores[0].score:.2f})" if scores else
                f"Strategy confirmed: {best}  (regime={regime})")

        return selection

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _current_regime(self) -> str:
        if self._regime:
            try:
                return str(self._regime.current().regime)
            except Exception:
                pass
        return "UNKNOWN"
