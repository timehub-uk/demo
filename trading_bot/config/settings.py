"""
Centralised application settings backed by an encrypted JSON file.
Provides typed access to all configuration values.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

CONFIG_DIR = Path.home() / ".binanceml"
CONFIG_FILE = CONFIG_DIR / "config.enc"
PLAIN_CONFIG_FILE = CONFIG_DIR / "app_config.json"


# ── Typed sub-models ─────────────────────────────────────────────────────────

class UserProfile(BaseModel):
    name: str = ""
    email: str = ""
    timezone: str = "Europe/London"
    currency: str = "GBP"


class BinanceConfig(BaseModel):
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True
    recv_window: int = 5000


class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str = "binanceml"
    user: str = "binanceml"
    password: str = ""
    pool_size: int = 10
    max_overflow: int = 20
    ssl_mode: str = "prefer"


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""
    ssl: bool = False
    max_connections: int = 50
    decode_responses: bool = True


class AIConfig(BaseModel):
    provider: str = "claude"          # claude | openai | gemini
    claude_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    voice_enabled: bool = True


class MLConfig(BaseModel):
    training_hours: int = 48
    top_tokens: int = 100
    lookback_window: int = 60          # candles
    prediction_horizon: int = 5        # candles ahead
    batch_size: int = 256
    learning_rate: float = 1e-3
    lstm_hidden_size: int = 256
    lstm_layers: int = 3
    dropout: float = 0.2
    confidence_threshold: float = 0.72
    max_position_size: float = 0.05    # 5 % of portfolio per trade
    stop_loss_pct: float = 0.02        # 2 %
    take_profit_pct: float = 0.04      # 4 %
    retrain_interval_hours: int = 24
    use_gpu: bool = True               # MPS on Apple Silicon


class TaxConfig(BaseModel):
    jurisdiction: str = "UK"
    tax_year_start_month: int = 4      # April
    tax_year_start_day: int = 6
    cgt_annual_allowance: float = 3_000.0   # 2024/25
    higher_rate_threshold: float = 50_270.0
    basic_rate_pct: float = 10.0
    higher_rate_pct: float = 20.0
    email_reports: bool = True
    report_day: int = 1                # day of month


class TradingConfig(BaseModel):
    mode: str = "manual"               # manual | auto | hybrid
    max_open_trades: int = 5
    risk_per_trade_pct: float = 1.0
    trailing_stop: bool = True
    trailing_stop_pct: float = 1.5
    order_type: str = "LIMIT"         # LIMIT | MARKET
    slippage_bps: int = 5
    fee_pct: float = 0.1              # Binance standard


class UIConfig(BaseModel):
    theme: str = "dark"
    accent_color: str = "#00D4FF"
    font_size: int = 13
    chart_candle_count: int = 200
    default_interval: str = "1m"
    show_notifications: bool = True
    sound_alerts: bool = True


# ── Main settings class ───────────────────────────────────────────────────────

class Settings:
    """Singleton settings store – load/save encrypted JSON."""

    _instance: "Settings | None" = None

    def __new__(cls) -> "Settings":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self) -> None:
        if self._loaded:
            return
        self.user = UserProfile()
        self.binance = BinanceConfig()
        self.database = DatabaseConfig()
        self.redis = RedisConfig()
        self.ai = AIConfig()
        self.ml = MLConfig()
        self.tax = TaxConfig()
        self.trading = TradingConfig()
        self.ui = UIConfig()
        self.first_run: bool = True
        self._loaded = True

    # ------------------------------------------------------------------
    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "user": self.user.model_dump(),
            "binance": self.binance.model_dump(),
            "database": self.database.model_dump(),
            "redis": self.redis.model_dump(),
            "ai": self.ai.model_dump(),
            "ml": self.ml.model_dump(),
            "tax": self.tax.model_dump(),
            "trading": self.trading.model_dump(),
            "ui": self.ui.model_dump(),
            "first_run": self.first_run,
        }
        from .encryption import EncryptionManager
        enc = EncryptionManager()
        try:
            encrypted = enc.encrypt_dict(data)
            CONFIG_FILE.write_text(encrypted)
            CONFIG_FILE.chmod(0o600)
        except RuntimeError:
            # Encryption not yet set up – write plain (will be re-encrypted on next save)
            PLAIN_CONFIG_FILE.write_text(json.dumps(data, indent=2))

    def load(self) -> None:
        from .encryption import EncryptionManager
        enc = EncryptionManager()
        try:
            if CONFIG_FILE.exists():
                encrypted = CONFIG_FILE.read_text()
                data = enc.decrypt_dict(encrypted)
                self._apply(data)
            elif PLAIN_CONFIG_FILE.exists():
                data = json.loads(PLAIN_CONFIG_FILE.read_text())
                self._apply(data)
        except Exception:
            pass  # Use defaults on any failure

    def _apply(self, data: dict[str, Any]) -> None:
        self.user = UserProfile(**data.get("user", {}))
        self.binance = BinanceConfig(**data.get("binance", {}))
        self.database = DatabaseConfig(**data.get("database", {}))
        self.redis = RedisConfig(**data.get("redis", {}))
        self.ai = AIConfig(**data.get("ai", {}))
        self.ml = MLConfig(**data.get("ml", {}))
        self.tax = TaxConfig(**data.get("tax", {}))
        self.trading = TradingConfig(**data.get("trading", {}))
        self.ui = UIConfig(**data.get("ui", {}))
        self.first_run = data.get("first_run", True)

    @property
    def db_url(self) -> str:
        db = self.database
        return (
            f"postgresql+psycopg2://{db.user}:{db.password}"
            f"@{db.host}:{db.port}/{db.name}"
        )

    @property
    def redis_url(self) -> str:
        r = self.redis
        auth = f":{r.password}@" if r.password else ""
        return f"redis://{auth}{r.host}:{r.port}/{r.db}"


_settings_singleton: Settings | None = None


def get_settings() -> Settings:
    global _settings_singleton
    if _settings_singleton is None:
        _settings_singleton = Settings()
    return _settings_singleton
