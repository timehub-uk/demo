"""
Secrets Manager
===============
Handles API keys, signing keys, RPC credentials, and secure secrets rotation.
Wraps the existing encryption layer with a clean secrets interface.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger


class SecretsManager:
    """
    Centralised secrets store with optional rotation support.

    Sources (priority order):
    1. Environment variables
    2. Encrypted secrets file (via config.encryption)
    3. In-memory override (for tests / rotation)
    """

    def __init__(self):
        self._store: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._rotation_callbacks: Dict[str, list] = {}
        self._loaded = False

    def load(self) -> None:
        """Load secrets from environment and encrypted config."""
        with self._lock:
            # Pull known keys from environment
            env_keys = [
                "BINANCE_API_KEY", "BINANCE_SECRET_KEY",
                "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "POSTGRES_URL", "REDIS_PASSWORD",
                "ENCRYPTION_PASSWORD",
                "ETH_RPC_URL", "BSC_RPC_URL", "SOL_RPC_URL",
                "WALLET_PRIVATE_KEY", "WALLET_ADDRESS",
            ]
            for key in env_keys:
                val = os.environ.get(key)
                if val:
                    self._store[key] = val

            # Try encrypted config
            try:
                from config.encryption import load_encrypted_config
                encrypted = load_encrypted_config()
                if encrypted:
                    for k, v in encrypted.items():
                        if k not in self._store:  # env takes priority
                            self._store[k] = str(v)
            except Exception as exc:
                logger.debug(f"[SecretsManager] Encrypted config not loaded: {exc}")

            self._loaded = True
            logger.info(f"[SecretsManager] Loaded {len(self._store)} secrets")

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            return self._store.get(key, default)

    def set(self, key: str, value: str) -> None:
        """Set or update a secret in-memory (does not persist)."""
        with self._lock:
            old = self._store.get(key)
            self._store[key] = value
            if old != value:
                self._fire_rotation(key, value)

    def rotate(self, key: str, new_value: str) -> None:
        """Rotate a secret and notify subscribers."""
        logger.info(f"[SecretsManager] Rotating secret: {key}")
        self.set(key, new_value)

    def on_rotation(self, key: str, callback) -> None:
        """Register a callback to be called when a secret is rotated."""
        with self._lock:
            self._rotation_callbacks.setdefault(key, []).append(callback)

    def list_keys(self) -> List[str]:
        """Return all known secret keys (not values)."""
        with self._lock:
            return list(self._store.keys())

    def is_loaded(self) -> bool:
        return self._loaded

    def _fire_rotation(self, key: str, value: str) -> None:
        for cb in self._rotation_callbacks.get(key, []):
            try:
                cb(key, value)
            except Exception as exc:
                logger.error(f"[SecretsManager] Rotation callback error: {exc}")


# Singleton
_secrets: Optional[SecretsManager] = None


def get_secrets() -> SecretsManager:
    global _secrets
    if _secrets is None:
        _secrets = SecretsManager()
    return _secrets
