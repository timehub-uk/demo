"""
Drawdown Guard  (Layer 6 – Module 50)
=======================================
Triggers de-risking, cool-down windows, or strategy shutdown
during loss clusters. Integrates with KillSwitch.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loguru import logger


@dataclass
class DrawdownLevel:
    name: str
    threshold_pct: float          # e.g. 5.0 = 5% drawdown
    action: str                   # "warn", "reduce_size", "pause", "halt"
    cooldown_minutes: int = 60
    auto_resume: bool = True


@dataclass
class DrawdownEvent:
    strategy_id: str
    peak_equity: float
    current_equity: float
    drawdown_pct: float
    level: str
    action_taken: str
    timestamp: float = field(default_factory=time.time)


class DrawdownGuard:
    """
    Multi-level drawdown protection with configurable thresholds.

    Default levels:
    Level 1 (5%):   Warn operator
    Level 2 (10%):  Reduce position sizes by 50%
    Level 3 (15%):  Pause strategy for cooldown window
    Level 4 (20%):  Hard halt via KillSwitch
    """

    DEFAULT_LEVELS = [
        DrawdownLevel("L1_warn",        5.0,  "warn",        cooldown_minutes=0),
        DrawdownLevel("L2_reduce",      10.0, "reduce_size", cooldown_minutes=30),
        DrawdownLevel("L3_pause",       15.0, "pause",       cooldown_minutes=120),
        DrawdownLevel("L4_halt",        20.0, "halt",        cooldown_minutes=0, auto_resume=False),
    ]

    def __init__(self, kill_switch=None):
        self._kill_switch = kill_switch
        self._levels = list(self.DEFAULT_LEVELS)
        self._equity_peaks: Dict[str, float] = {}
        self._paused_until: Dict[str, float] = {}
        self._events: List[DrawdownEvent] = []
        self._callbacks: List[Callable[[DrawdownEvent], None]] = []
        self._lock = threading.RLock()

    def configure_levels(self, levels: List[DrawdownLevel]) -> None:
        with self._lock:
            self._levels = sorted(levels, key=lambda l: l.threshold_pct)

    def on_event(self, callback: Callable[[DrawdownEvent], None]) -> None:
        self._callbacks.append(callback)

    def record_equity(self, strategy_id: str, equity: float) -> Optional[DrawdownEvent]:
        """
        Update equity for a strategy. Returns a DrawdownEvent if a level is breached.
        Call this after every trade or on a regular heartbeat.
        """
        with self._lock:
            peak = self._equity_peaks.get(strategy_id, equity)
            if equity > peak:
                self._equity_peaks[strategy_id] = equity
                peak = equity

            if peak <= 0:
                return None

            dd_pct = (peak - equity) / peak * 100

            # Find breached level (highest breached)
            breached = None
            for lvl in reversed(self._levels):
                if dd_pct >= lvl.threshold_pct:
                    breached = lvl
                    break

            if not breached:
                return None

            evt = DrawdownEvent(
                strategy_id=strategy_id,
                peak_equity=peak,
                current_equity=equity,
                drawdown_pct=dd_pct,
                level=breached.name,
                action_taken=breached.action,
            )
            self._events.append(evt)

        self._execute_action(strategy_id, breached, evt)
        self._fire_callbacks(evt)
        return evt

    def is_paused(self, strategy_id: str) -> bool:
        with self._lock:
            until = self._paused_until.get(strategy_id, 0)
            return time.time() < until

    def get_drawdown_pct(self, strategy_id: str) -> float:
        """Current drawdown from peak for a strategy."""
        with self._lock:
            peak = self._equity_peaks.get(strategy_id, 0)
            return 0.0  # Would need current equity passed in

    def get_events(self, strategy_id: Optional[str] = None) -> List[DrawdownEvent]:
        with self._lock:
            if strategy_id:
                return [e for e in self._events if e.strategy_id == strategy_id]
            return list(self._events)

    def reset_peak(self, strategy_id: str) -> None:
        with self._lock:
            self._equity_peaks.pop(strategy_id, None)

    def configure(self, **kwargs) -> None:
        """Update thresholds from dict (for UI settings panel)."""
        if "l1_pct" in kwargs:
            self._levels[0].threshold_pct = float(kwargs["l1_pct"])
        if "l2_pct" in kwargs:
            self._levels[1].threshold_pct = float(kwargs["l2_pct"])
        if "l3_pct" in kwargs:
            self._levels[2].threshold_pct = float(kwargs["l3_pct"])
        if "l4_pct" in kwargs:
            self._levels[3].threshold_pct = float(kwargs["l4_pct"])

    def _execute_action(self, strategy_id: str, level: DrawdownLevel,
                         evt: DrawdownEvent) -> None:
        action = level.action
        logger.warning(
            f"[DrawdownGuard] {strategy_id} DD={evt.drawdown_pct:.1f}% "
            f"→ {level.name} action={action}"
        )
        if action == "pause":
            with self._lock:
                self._paused_until[strategy_id] = (
                    time.time() + level.cooldown_minutes * 60
                )
        elif action == "halt":
            if self._kill_switch:
                self._kill_switch.trigger(
                    f"strategy:{strategy_id}",
                    f"Drawdown {evt.drawdown_pct:.1f}% exceeded halt threshold",
                    triggered_by="drawdown_guard",
                )

    def _fire_callbacks(self, evt: DrawdownEvent) -> None:
        for cb in self._callbacks:
            try:
                cb(evt)
            except Exception:
                pass
