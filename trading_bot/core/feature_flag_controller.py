"""
Feature Flag Controller
=======================
Turns modules on and off safely without redeploying the full stack.
Supports gradual rollout, A/B testing, and emergency kill-flags.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class FeatureFlagController:
    """
    Runtime feature flag management.

    Flags are booleans keyed by name. Supports:
    - Default values
    - Override via JSON file (hot-reloaded on read)
    - In-memory override
    - Change callbacks
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or Path("feature_flags.json")
        self._flags: Dict[str, bool] = {}
        self._defaults: Dict[str, bool] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        self._lock = threading.RLock()
        self._load()

    # ── Default registration ───────────────────────────────────────────────────

    def declare(self, name: str, default: bool = False, description: str = "") -> None:
        """Register a flag with a default value."""
        with self._lock:
            self._defaults[name] = default
            if name not in self._flags:
                self._flags[name] = default

    # ── Read / Write ──────────────────────────────────────────────────────────

    def is_enabled(self, name: str) -> bool:
        """Check if a feature flag is enabled."""
        with self._lock:
            return self._flags.get(name, self._defaults.get(name, False))

    def enable(self, name: str) -> None:
        self._set(name, True)

    def disable(self, name: str) -> None:
        self._set(name, False)

    def toggle(self, name: str) -> bool:
        current = self.is_enabled(name)
        self._set(name, not current)
        return not current

    def set(self, name: str, value: bool) -> None:
        self._set(name, value)

    # ── Bulk ops ──────────────────────────────────────────────────────────────

    def get_all(self) -> Dict[str, bool]:
        with self._lock:
            all_flags = {**self._defaults, **self._flags}
            return dict(all_flags)

    def reset_to_defaults(self) -> None:
        with self._lock:
            self._flags = dict(self._defaults)
        self._save()

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def on_change(self, name: str, callback: Callable[[str, bool], None]) -> None:
        with self._lock:
            self._callbacks.setdefault(name, []).append(callback)

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        self._save()

    def reload(self) -> None:
        self._load()

    def _set(self, name: str, value: bool) -> None:
        with self._lock:
            old = self._flags.get(name)
            self._flags[name] = value
        self._save()
        if old != value:
            self._fire(name, value)
        logger.debug(f"[FeatureFlag] {name} = {value}")

    def _save(self) -> None:
        try:
            with self._lock:
                data = dict(self._flags)
            self._config_path.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.warning(f"[FeatureFlag] Save failed: {exc}")

    def _load(self) -> None:
        if not self._config_path.exists():
            return
        try:
            data = json.loads(self._config_path.read_text())
            with self._lock:
                self._flags.update(data)
            logger.debug(f"[FeatureFlag] Loaded {len(data)} flags")
        except Exception as exc:
            logger.warning(f"[FeatureFlag] Load failed: {exc}")

    def _fire(self, name: str, value: bool) -> None:
        for cb in self._callbacks.get(name, []):
            try:
                cb(name, value)
            except Exception as exc:
                logger.error(f"[FeatureFlag] Callback error for {name}: {exc}")


# ── Predefined flags ───────────────────────────────────────────────────────────

KNOWN_FLAGS: Dict[str, tuple] = {
    # (default, description)
    "ml_trading": (True, "Enable ML-based trading signals"),
    "auto_trader": (True, "Enable automated order placement"),
    "dex_execution": (False, "Enable DEX/on-chain execution"),
    "mempool_watch": (False, "Enable mempool monitoring"),
    "sentiment_signals": (True, "Enable social sentiment signals"),
    "options_surface": (False, "Enable options vol surface collection"),
    "strategy_mutation": (False, "Enable automated strategy mutation lab"),
    "live_simulation": (True, "Enable live simulation twin"),
    "contract_safety": (True, "Enable token contract safety checks"),
    "honeypot_check": (True, "Enable honeypot detection for new tokens"),
    "rugpull_score": (True, "Enable rug-pull probability scoring"),
    "walk_forward": (True, "Enable walk-forward validation"),
    "monte_carlo": (True, "Enable Monte Carlo stress testing"),
    "regime_detection": (True, "Enable market regime detection"),
    "telegram_alerts": (True, "Enable Telegram alert delivery"),
    "voice_alerts": (False, "Enable voice alert synthesis"),
    "tax_tracking": (True, "Enable UK tax calculation"),
    "api_server": (True, "Enable REST API server"),
    "mev_protection": (False, "Enable MEV / sandwich protection"),
    "kill_switch": (False, "Emergency kill switch – halts all trading"),
}

# Singleton
_controller: Optional[FeatureFlagController] = None


def get_flags() -> FeatureFlagController:
    global _controller
    if _controller is None:
        _controller = FeatureFlagController()
        for name, (default, desc) in KNOWN_FLAGS.items():
            _controller.declare(name, default, desc)
    return _controller
