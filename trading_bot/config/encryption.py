"""
AES-256-GCM encryption for all sensitive configuration and database data.
Keys are derived via PBKDF2-HMAC-SHA256 and stored in the OS keychain.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

import keyring
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

APP_NAME = "BinanceMLPro"
KEYRING_SERVICE = "binance_ml_pro"
SALT_FILE = Path.home() / ".binanceml" / "salt.bin"


class EncryptionManager:
    """Thread-safe AES-256-GCM encryption / decryption manager."""

    _instance: "EncryptionManager | None" = None

    def __new__(cls) -> "EncryptionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialised = False
        return cls._instance

    # ------------------------------------------------------------------
    def initialise(self, master_password: str) -> None:
        """Derive encryption key from master password + stored salt."""
        if self._initialised:
            return
        salt = self._load_or_create_salt()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600_000,
        )
        key = kdf.derive(master_password.encode())
        self._aesgcm = AESGCM(key)
        self._key = key
        self._initialised = True

    # ------------------------------------------------------------------
    def encrypt(self, plaintext: str) -> str:
        """Return base64-encoded ciphertext (nonce‖ciphertext)."""
        self._check_init()
        nonce = secrets.token_bytes(12)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(nonce + ct).decode()

    def decrypt(self, token: str) -> str:
        """Decrypt a token produced by :meth:`encrypt`."""
        self._check_init()
        raw = base64.b64decode(token.encode())
        nonce, ct = raw[:12], raw[12:]
        return self._aesgcm.decrypt(nonce, ct, None).decode()

    def encrypt_dict(self, data: dict[str, Any]) -> str:
        return self.encrypt(json.dumps(data))

    def decrypt_dict(self, token: str) -> dict[str, Any]:
        return json.loads(self.decrypt(token))

    # ------------------------------------------------------------------
    def store_api_key(self, service_name: str, key_value: str) -> None:
        """Encrypt and store an API key in the OS keychain."""
        self._check_init()
        encrypted = self.encrypt(key_value)
        keyring.set_password(KEYRING_SERVICE, service_name, encrypted)

    def retrieve_api_key(self, service_name: str) -> str | None:
        """Retrieve and decrypt an API key from the OS keychain."""
        self._check_init()
        encrypted = keyring.get_password(KEYRING_SERVICE, service_name)
        if encrypted is None:
            return None
        try:
            return self.decrypt(encrypted)
        except Exception:
            return None

    # ------------------------------------------------------------------
    @staticmethod
    def hash_password(password: str) -> str:
        import bcrypt
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        import bcrypt
        return bcrypt.checkpw(password.encode(), hashed.encode())

    # ------------------------------------------------------------------
    def _load_or_create_salt(self) -> bytes:
        SALT_FILE.parent.mkdir(parents=True, exist_ok=True)
        if SALT_FILE.exists():
            return SALT_FILE.read_bytes()
        salt = secrets.token_bytes(32)
        SALT_FILE.write_bytes(salt)
        SALT_FILE.chmod(0o600)
        return salt

    def _check_init(self) -> None:
        if not self._initialised:
            raise RuntimeError("EncryptionManager not initialised – call initialise() first.")
