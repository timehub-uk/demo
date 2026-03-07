"""
Strategy Registry
=================
Stores all active, inactive, experimental, and archived strategies.
Provides versioning, lineage tracking, and promotion workflow.
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


class StrategyStatus(Enum):
    EXPERIMENTAL = "experimental"
    STAGING = "staging"
    ACTIVE = "active"
    PAUSED = "paused"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


@dataclass
class StrategyRecord:
    id: str
    name: str
    description: str
    status: StrategyStatus
    parameters: Dict[str, Any]
    performance: Dict[str, float] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    parent_id: Optional[str] = None          # For mutation lineage
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    activated_at: Optional[float] = None
    archived_at: Optional[float] = None
    notes: str = ""
    version: int = 1

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyRecord":
        d = d.copy()
        d["status"] = StrategyStatus(d["status"])
        return cls(**d)


class StrategyRegistry:
    """
    Central store for all strategies with lifecycle management.

    Features:
    - CRUD for strategies
    - Status transitions with validation
    - Lineage tracking (mutation parents)
    - Persistence to JSON
    - Performance metric updates
    """

    _VALID_TRANSITIONS = {
        StrategyStatus.EXPERIMENTAL: {StrategyStatus.STAGING, StrategyStatus.ARCHIVED},
        StrategyStatus.STAGING: {
            StrategyStatus.ACTIVE,
            StrategyStatus.EXPERIMENTAL,
            StrategyStatus.ARCHIVED,
        },
        StrategyStatus.ACTIVE: {StrategyStatus.PAUSED, StrategyStatus.INACTIVE},
        StrategyStatus.PAUSED: {StrategyStatus.ACTIVE, StrategyStatus.INACTIVE},
        StrategyStatus.INACTIVE: {StrategyStatus.EXPERIMENTAL, StrategyStatus.ARCHIVED},
        StrategyStatus.ARCHIVED: set(),
    }

    def __init__(self, persist_path: Optional[Path] = None):
        self._strategies: Dict[str, StrategyRecord] = {}
        self._lock = threading.RLock()
        self._persist_path = persist_path or Path("strategy_registry.json")
        self._load()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def register(
        self,
        id: str,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        status: StrategyStatus = StrategyStatus.EXPERIMENTAL,
        tags: Optional[List[str]] = None,
        parent_id: Optional[str] = None,
        notes: str = "",
    ) -> StrategyRecord:
        with self._lock:
            if id in self._strategies:
                raise ValueError(f"Strategy {id} already registered")
            record = StrategyRecord(
                id=id,
                name=name,
                description=description,
                status=status,
                parameters=parameters,
                tags=tags or [],
                parent_id=parent_id,
                notes=notes,
            )
            self._strategies[id] = record
            self._save()
            logger.info(f"[StrategyRegistry] Registered: {id} ({status.value})")
            return record

    def get(self, id: str) -> Optional[StrategyRecord]:
        with self._lock:
            return self._strategies.get(id)

    def update_parameters(self, id: str, params: Dict[str, Any]) -> bool:
        with self._lock:
            s = self._strategies.get(id)
            if not s:
                return False
            s.parameters.update(params)
            s.updated_at = time.time()
            s.version += 1
            self._save()
            return True

    def update_performance(self, id: str, metrics: Dict[str, float]) -> bool:
        with self._lock:
            s = self._strategies.get(id)
            if not s:
                return False
            s.performance.update(metrics)
            s.updated_at = time.time()
            self._save()
            return True

    def transition(self, id: str, new_status: StrategyStatus) -> bool:
        with self._lock:
            s = self._strategies.get(id)
            if not s:
                logger.error(f"[StrategyRegistry] Unknown strategy: {id}")
                return False
            allowed = self._VALID_TRANSITIONS.get(s.status, set())
            if new_status not in allowed:
                logger.error(
                    f"[StrategyRegistry] Invalid transition {s.status.value} → "
                    f"{new_status.value} for {id}"
                )
                return False
            s.status = new_status
            s.updated_at = time.time()
            if new_status == StrategyStatus.ACTIVE:
                s.activated_at = time.time()
            elif new_status == StrategyStatus.ARCHIVED:
                s.archived_at = time.time()
            self._save()
            logger.info(f"[StrategyRegistry] {id} → {new_status.value}")
            return True

    def delete(self, id: str) -> bool:
        with self._lock:
            if id not in self._strategies:
                return False
            del self._strategies[id]
            self._save()
            return True

    # ── Queries ───────────────────────────────────────────────────────────────

    def list_by_status(self, status: StrategyStatus) -> List[StrategyRecord]:
        with self._lock:
            return [s for s in self._strategies.values() if s.status == status]

    def list_active(self) -> List[StrategyRecord]:
        return self.list_by_status(StrategyStatus.ACTIVE)

    def list_experimental(self) -> List[StrategyRecord]:
        return self.list_by_status(StrategyStatus.EXPERIMENTAL)

    def get_lineage(self, id: str) -> List[StrategyRecord]:
        """Return ancestor chain from root to this strategy."""
        chain = []
        current_id: Optional[str] = id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            s = self._strategies.get(current_id)
            if s:
                chain.insert(0, s)
                current_id = s.parent_id
            else:
                break
        return chain

    def get_children(self, id: str) -> List[StrategyRecord]:
        """Return direct children (mutations spawned from this strategy)."""
        with self._lock:
            return [s for s in self._strategies.values() if s.parent_id == id]

    def summary(self) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            for s in self._strategies.values():
                counts[s.status.value] = counts.get(s.status.value, 0) + 1
            return counts

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            data = [s.to_dict() for s in self._strategies.values()]
            self._persist_path.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.warning(f"[StrategyRegistry] Save failed: {exc}")

    def _load(self) -> None:
        if not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text())
            for d in data:
                r = StrategyRecord.from_dict(d)
                self._strategies[r.id] = r
            logger.info(f"[StrategyRegistry] Loaded {len(self._strategies)} strategies")
        except Exception as exc:
            logger.warning(f"[StrategyRegistry] Load failed: {exc}")


# Singleton
_registry: Optional[StrategyRegistry] = None


def get_registry() -> StrategyRegistry:
    global _registry
    if _registry is None:
        _registry = StrategyRegistry()
    return _registry
