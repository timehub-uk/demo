"""
Stop and Kill-Switch Controller  (Layer 6 – Module 54)
=======================================================
Hard stops for strategies, venues, wallets, or the entire trading system.
Single point of emergency halt with cascading notifications.

Feature flag: 'kill_switch' — when enabled, halts ALL live trading.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loguru import logger


@dataclass
class KillEvent:
    scope: str                  # "global", "strategy:<id>", "venue:<name>", "wallet:<addr>"
    reason: str
    triggered_by: str           # "manual", "drawdown_guard", "risk_engine", "circuit_breaker"
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False
    resolved_at: Optional[float] = None


class KillSwitch:
    """
    Emergency halt controller.

    Scopes:
    - "global"              – halts ALL trading system-wide
    - "strategy:<id>"       – halts a specific strategy
    - "venue:<name>"        – halts trading on a specific exchange
    - "wallet:<address>"    – halts a specific wallet's transactions

    Once triggered, a scope stays halted until explicitly cleared
    (requires operator action for global scope).
    """

    def __init__(self):
        self._active: Dict[str, KillEvent] = {}
        self._history: List[KillEvent] = []
        self._lock = threading.RLock()
        self._callbacks: List[Callable[[KillEvent], None]] = []

    # ── Control ───────────────────────────────────────────────────────────────

    def trigger(self, scope: str, reason: str, triggered_by: str = "manual") -> KillEvent:
        """Activate a kill switch for the given scope."""
        evt = KillEvent(scope=scope, reason=reason, triggered_by=triggered_by)
        with self._lock:
            self._active[scope] = evt
            self._history.append(evt)
        logger.critical(f"[KillSwitch] TRIGGERED scope={scope!r} by={triggered_by}: {reason}")
        self._notify(evt)
        return evt

    def clear(self, scope: str, cleared_by: str = "manual") -> bool:
        """Clear a kill switch, allowing trading to resume."""
        with self._lock:
            evt = self._active.pop(scope, None)
            if evt:
                evt.resolved = True
                evt.resolved_at = time.time()
        if evt:
            logger.warning(f"[KillSwitch] Cleared scope={scope!r} by={cleared_by}")
            return True
        return False

    def trigger_global(self, reason: str, triggered_by: str = "manual") -> KillEvent:
        return self.trigger("global", reason, triggered_by)

    def clear_global(self, cleared_by: str = "manual") -> bool:
        return self.clear("global", cleared_by)

    # ── Checks ────────────────────────────────────────────────────────────────

    def is_halted(self, scope: Optional[str] = None) -> bool:
        """Return True if global or specific scope is halted."""
        with self._lock:
            if "global" in self._active:
                return True
            if scope and scope in self._active:
                return True
        return False

    def is_strategy_halted(self, strategy_id: str) -> bool:
        return self.is_halted(f"strategy:{strategy_id}")

    def is_venue_halted(self, venue: str) -> bool:
        return self.is_halted(f"venue:{venue}")

    def get_active_kills(self) -> Dict[str, KillEvent]:
        with self._lock:
            return dict(self._active)

    def get_history(self, n: int = 50) -> List[KillEvent]:
        with self._lock:
            return list(self._history[-n:])

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def on_trigger(self, callback: Callable[[KillEvent], None]) -> None:
        self._callbacks.append(callback)

    def _notify(self, evt: KillEvent) -> None:
        for cb in self._callbacks:
            try:
                cb(evt)
            except Exception as exc:
                logger.error(f"[KillSwitch] Callback error: {exc}")


# Singleton
_kill_switch: Optional[KillSwitch] = None


def get_kill_switch() -> KillSwitch:
    global _kill_switch
    if _kill_switch is None:
        _kill_switch = KillSwitch()
    return _kill_switch
