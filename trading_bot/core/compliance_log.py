"""
Compliance Log Engine  (Layer 9 – Module 71)
=============================================
Maintains audit trails, decision logs, approvals, and model-change records.
Immutable append-only log with structured querying.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


class LogCategory(Enum):
    TRADE = "trade"
    RISK_EVENT = "risk_event"
    MODEL_CHANGE = "model_change"
    STRATEGY_CHANGE = "strategy_change"
    PARAMETER_CHANGE = "parameter_change"
    KILL_SWITCH = "kill_switch"
    APPROVAL = "approval"
    ACCESS = "access"
    SYSTEM = "system"
    ALERT = "alert"


@dataclass
class ComplianceEntry:
    entry_id: str
    category: LogCategory
    actor: str                   # user, system, strategy_id
    action: str
    details: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    approved_by: Optional[str] = None
    session_id: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        return d


class ComplianceLogEngine:
    """
    Immutable audit trail for all significant system events.

    Requirements:
    - Every trade must be logged
    - Every risk event (drawdown, kill switch) must be logged
    - Every parameter or model change must be logged
    - Log entries are never deleted or modified
    - Supports structured query by category, actor, time range
    """

    def __init__(self, log_path: Optional[Path] = None, max_memory: int = 10_000):
        self._log_path = log_path or Path("compliance_log.jsonl")
        self._entries: List[ComplianceEntry] = []
        self._lock = threading.RLock()
        self._counter = 0
        self._max_memory = max_memory
        self._load_recent()

    def log(
        self,
        category: LogCategory,
        actor: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        approved_by: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ComplianceEntry:
        with self._lock:
            self._counter += 1
            entry = ComplianceEntry(
                entry_id=f"LOG-{int(time.time() * 1000)}-{self._counter:04d}",
                category=category,
                actor=actor,
                action=action,
                details=details or {},
                approved_by=approved_by,
                session_id=session_id,
            )
            self._entries.append(entry)
            if len(self._entries) > self._max_memory:
                self._entries = self._entries[-self._max_memory // 2:]

        self._append_to_file(entry)
        return entry

    def log_trade(self, actor: str, symbol: str, side: str, qty: float,
                  price: float, strategy_id: str) -> None:
        self.log(
            LogCategory.TRADE, actor, "trade_executed",
            {"symbol": symbol, "side": side, "qty": qty,
             "price": price, "strategy_id": strategy_id}
        )

    def log_risk_event(self, actor: str, event_type: str, details: dict) -> None:
        self.log(LogCategory.RISK_EVENT, actor, event_type, details)

    def log_model_change(self, actor: str, model_id: str, change_type: str,
                          old_version: str, new_version: str) -> None:
        self.log(
            LogCategory.MODEL_CHANGE, actor, f"model_{change_type}",
            {"model_id": model_id, "old_version": old_version, "new_version": new_version}
        )

    def log_kill_switch(self, actor: str, scope: str, reason: str) -> None:
        self.log(LogCategory.KILL_SWITCH, actor, "kill_switch_triggered",
                 {"scope": scope, "reason": reason})

    # ── Query ─────────────────────────────────────────────────────────────────

    def query(
        self,
        category: Optional[LogCategory] = None,
        actor: Optional[str] = None,
        since_ts: Optional[float] = None,
        until_ts: Optional[float] = None,
        limit: int = 100,
    ) -> List[ComplianceEntry]:
        with self._lock:
            entries = list(self._entries)

        if category:
            entries = [e for e in entries if e.category == category]
        if actor:
            entries = [e for e in entries if e.actor == actor]
        if since_ts:
            entries = [e for e in entries if e.timestamp >= since_ts]
        if until_ts:
            entries = [e for e in entries if e.timestamp <= until_ts]

        return entries[-limit:]

    def get_recent(self, n: int = 50) -> List[ComplianceEntry]:
        with self._lock:
            return list(self._entries[-n:])

    def get_entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _append_to_file(self, entry: ComplianceEntry) -> None:
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")
        except Exception as exc:
            logger.debug(f"[ComplianceLog] Write error: {exc}")

    def _load_recent(self, last_n: int = 1000) -> None:
        if not self._log_path.exists():
            return
        try:
            lines = self._log_path.read_text().splitlines()[-last_n:]
            for line in lines:
                d = json.loads(line)
                d["category"] = LogCategory(d["category"])
                self._entries.append(ComplianceEntry(**d))
        except Exception as exc:
            logger.debug(f"[ComplianceLog] Load error: {exc}")


# Singleton
_log_engine: Optional[ComplianceLogEngine] = None


def get_compliance_log() -> ComplianceLogEngine:
    global _log_engine
    if _log_engine is None:
        _log_engine = ComplianceLogEngine()
    return _log_engine
