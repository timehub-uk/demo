"""
Access Control Layer  (Layer 10 – Module 76)
=============================================
Defines operator, researcher, trader, and admin privileges.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

from loguru import logger


class Role(Enum):
    VIEWER = "viewer"         # read-only: view positions, PnL, charts
    RESEARCHER = "researcher" # viewer + backtest + ML training
    TRADER = "trader"         # researcher + manual order placement
    OPERATOR = "operator"     # trader + strategy enable/disable + risk limits
    ADMIN = "admin"           # full access including secrets + model promotion


_ROLE_PERMISSIONS: Dict[Role, Set[str]] = {
    Role.VIEWER: {
        "view_positions", "view_pnl", "view_charts",
        "view_signals", "view_orderbook", "view_alerts",
    },
    Role.RESEARCHER: {
        "run_backtest", "run_monte_carlo", "run_walk_forward",
        "train_ml_model", "view_feature_store", "export_data",
    },
    Role.TRADER: {
        "place_order", "cancel_order", "adjust_position",
        "view_order_history", "manual_exit",
    },
    Role.OPERATOR: {
        "enable_strategy", "disable_strategy", "pause_strategy",
        "adjust_risk_limits", "trigger_kill_switch", "clear_kill_switch",
        "adjust_position_size", "view_compliance_log",
    },
    Role.ADMIN: {
        "manage_secrets", "promote_model", "archive_strategy",
        "manage_users", "view_all_logs", "approve_workflows",
        "modify_feature_flags", "disaster_recovery",
    },
}

# Each role inherits all permissions of lower roles
_ROLE_HIERARCHY = [Role.VIEWER, Role.RESEARCHER, Role.TRADER, Role.OPERATOR, Role.ADMIN]


def _get_effective_permissions(role: Role) -> Set[str]:
    """Return all permissions for a role including inherited ones."""
    permissions: Set[str] = set()
    for r in _ROLE_HIERARCHY:
        permissions.update(_ROLE_PERMISSIONS.get(r, set()))
        if r == role:
            break
    return permissions


@dataclass
class User:
    username: str
    role: Role
    active: bool = True
    session_id: Optional[str] = None
    permissions_override: Set[str] = field(default_factory=set)  # extra grants


class AccessControlLayer:
    """
    Role-based access control (RBAC) for the trading system.

    Usage:
        acl = get_access_control()
        if acl.can(username, "place_order"):
            # allow
    """

    def __init__(self):
        self._users: Dict[str, User] = {}
        self._lock = threading.RLock()
        self._access_log: List[dict] = []
        # Create default admin
        self._users["admin"] = User("admin", Role.ADMIN)

    def add_user(self, username: str, role: Role) -> User:
        with self._lock:
            user = User(username=username, role=role)
            self._users[username] = user
            logger.info(f"[ACL] Added user {username!r} role={role.value}")
            return user

    def set_role(self, username: str, role: Role) -> bool:
        with self._lock:
            user = self._users.get(username)
            if not user:
                return False
            old = user.role
            user.role = role
            logger.info(f"[ACL] {username}: {old.value} → {role.value}")
            return True

    def deactivate(self, username: str) -> bool:
        with self._lock:
            user = self._users.get(username)
            if user:
                user.active = False
                return True
            return False

    def grant(self, username: str, permission: str) -> bool:
        with self._lock:
            user = self._users.get(username)
            if user:
                user.permissions_override.add(permission)
                return True
            return False

    def can(self, username: str, permission: str) -> bool:
        """Check if a user has a specific permission."""
        with self._lock:
            user = self._users.get(username)
        if not user or not user.active:
            return False
        effective = _get_effective_permissions(user.role) | user.permissions_override
        result = permission in effective
        self._log_access(username, permission, result)
        return result

    def get_permissions(self, username: str) -> Set[str]:
        with self._lock:
            user = self._users.get(username)
        if not user:
            return set()
        return _get_effective_permissions(user.role) | user.permissions_override

    def get_user(self, username: str) -> Optional[User]:
        with self._lock:
            return self._users.get(username)

    def list_users(self) -> List[User]:
        with self._lock:
            return list(self._users.values())

    def get_recent_access_log(self, n: int = 50) -> List[dict]:
        with self._lock:
            return list(self._access_log[-n:])

    def _log_access(self, username: str, permission: str, granted: bool) -> None:
        import time
        entry = {
            "username": username,
            "permission": permission,
            "granted": granted,
            "timestamp": time.time(),
        }
        with self._lock:
            self._access_log.append(entry)
            if len(self._access_log) > 5000:
                self._access_log = self._access_log[-2500:]


# Singleton
_acl: Optional[AccessControlLayer] = None


def get_access_control() -> AccessControlLayer:
    global _acl
    if _acl is None:
        _acl = AccessControlLayer()
    return _acl
