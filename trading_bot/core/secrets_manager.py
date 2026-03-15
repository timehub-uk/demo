"""
Secrets Manager
===============
Handles API keys, signing keys, RPC credentials, and secure secrets rotation.
Wraps the existing encryption layer with a clean secrets interface.

Security notes
--------------
* Secrets are obfuscated in memory using a process-scoped Fernet key that is
  generated fresh on every run.  This is not a substitute for OS-level memory
  protection, but it prevents plain-text secrets from appearing in a process
  heap dump or a naive strings(1) scan.
* The obfuscation key is never persisted – it lives only in process memory.
"""

from __future__ import annotations

import os
import threading
from typing import Dict, List, Optional

from loguru import logger


def _make_fernet():
    """Return a Fernet instance with a fresh random process-scoped key."""
    try:
        from cryptography.fernet import Fernet
        return Fernet(Fernet.generate_key())
    except ImportError:
        return None


class SecretsManager:
    """
    Centralised secrets store with optional rotation support.

    Sources (priority order):
    1. Environment variables
    2. Encrypted secrets file (via config.encryption)
    3. In-memory override (for tests / rotation)

    Values are stored obfuscated via a process-scoped Fernet key so that
    plain-text credentials do not appear in heap dumps.
    """

    def __init__(self):
        # Obfuscation cipher – generated fresh each process start
        self._fernet = _make_fernet()
        self._store: Dict[str, bytes] = {}   # values are Fernet tokens (or raw bytes if unavailable)
        self._lock = threading.RLock()
        self._rotation_callbacks: Dict[str, list] = {}
        self._loaded = False

    # ── Internal encode/decode ──────────────────────────────────────────

    def _encode(self, value: str) -> bytes:
        raw = value.encode()
        if self._fernet:
            return self._fernet.encrypt(raw)
        return raw  # fallback: at least avoid plain str in dict

    def _decode(self, token: bytes) -> str:
        if self._fernet:
            return self._fernet.decrypt(token).decode()
        return token.decode()

    # ── Public API ──────────────────────────────────────────────────────

    def load(self) -> None:
        """Load secrets from environment and encrypted config."""
        with self._lock:
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
                    self._store[key] = self._encode(val)

            try:
                from config.encryption import load_encrypted_config
                encrypted = load_encrypted_config()
                if encrypted:
                    for k, v in encrypted.items():
                        if k not in self._store:  # env takes priority
                            self._store[k] = self._encode(str(v))
            except Exception as exc:
                logger.debug(f"[SecretsManager] Encrypted config not loaded: {exc}")

            self._loaded = True
            obf = "Fernet-obfuscated" if self._fernet else "raw bytes (cryptography not available)"
            logger.info(f"[SecretsManager] Loaded {len(self._store)} secrets ({obf})")

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            token = self._store.get(key)
            if token is None:
                return default
            return self._decode(token)

    def set(self, key: str, value: str) -> None:
        """Set or update a secret in-memory (does not persist)."""
        with self._lock:
            old_token = self._store.get(key)
            old = self._decode(old_token) if old_token is not None else None
            self._store[key] = self._encode(value)
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


# ── Thread-safe singleton ────────────────────────────────────────────────────

_secrets: Optional[SecretsManager] = None
_secrets_lock = threading.Lock()


def get_secrets() -> SecretsManager:
    global _secrets
    if _secrets is None:
        with _secrets_lock:
            if _secrets is None:
                _secrets = SecretsManager()
    return _secrets
