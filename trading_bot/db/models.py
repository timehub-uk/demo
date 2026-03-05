"""
SQLAlchemy ORM models for BinanceML Pro.
All sensitive columns are stored encrypted via the @encrypted_column pattern.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index, Integer,
    Numeric, String, Text, ForeignKey, Enum, JSON, LargeBinary,
    UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ── Helper ────────────────────────────────────────────────────────────────────

def uuid_pk():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

def now_utc():
    return Column(DateTime(timezone=True), default=func.now(), nullable=False)


# ── Models ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = uuid_pk()
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    timezone = Column(String(50), default="Europe/London")
    currency = Column(String(10), default="GBP")
    is_active = Column(Boolean, default=True)
    created_at = now_utc()
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ApiCredential(Base):
    """Stores encrypted API keys – never stored in plaintext."""
    __tablename__ = "api_credentials"

    id = uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    service = Column(String(50), nullable=False)   # binance | claude | openai | …
    encrypted_key = Column(Text, nullable=False)
    encrypted_secret = Column(Text)
    created_at = now_utc()

    __table_args__ = (UniqueConstraint("user_id", "service"),)


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    asset = Column(String(20), nullable=False)
    free = Column(Numeric(30, 12), default=0)
    locked = Column(Numeric(30, 12), default=0)
    usd_value = Column(Numeric(20, 6), default=0)
    gbp_value = Column(Numeric(20, 6), default=0)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("user_id", "asset"),)


class Trade(Base):
    __tablename__ = "trades"

    id = uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    binance_order_id = Column(String(40), unique=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(Enum("BUY", "SELL", name="trade_side"), nullable=False)
    order_type = Column(String(20), default="LIMIT")
    status = Column(String(20), default="OPEN")          # OPEN|FILLED|CANCELLED|PARTIAL

    quantity = Column(Numeric(30, 12), nullable=False)
    price = Column(Numeric(30, 12), nullable=False)
    filled_qty = Column(Numeric(30, 12), default=0)
    avg_fill_price = Column(Numeric(30, 12), default=0)
    fee = Column(Numeric(20, 8), default=0)
    fee_asset = Column(String(10), default="BNB")

    # P&L (populated on SELL)
    realized_pnl = Column(Numeric(20, 8))
    realized_pnl_gbp = Column(Numeric(20, 8))
    entry_price = Column(Numeric(30, 12))

    # ML metadata
    ml_signal = Column(String(10))                        # BUY|SELL|HOLD
    ml_confidence = Column(Float)
    ml_model_version = Column(String(40))

    # Tax metadata (UK HMRC)
    tax_year = Column(String(10))                         # e.g. 2024/25
    disposal_proceeds = Column(Numeric(20, 8))
    acquisition_cost = Column(Numeric(20, 8))
    gain_loss = Column(Numeric(20, 8))

    is_automated = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = now_utc()
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("idx_trades_symbol_created", "symbol", "created_at"),
        Index("idx_trades_user_status", "user_id", "status"),
    )


class Order(Base):
    """Pending / working orders."""
    __tablename__ = "orders"

    id = uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    trade_id = Column(UUID(as_uuid=True), ForeignKey("trades.id", ondelete="SET NULL"), nullable=True)
    binance_order_id = Column(String(40), unique=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(Enum("BUY", "SELL", name="order_side"), nullable=False)
    order_type = Column(String(20), default="LIMIT")
    status = Column(String(20), default="NEW")
    quantity = Column(Numeric(30, 12))
    price = Column(Numeric(30, 12))
    stop_price = Column(Numeric(30, 12))
    time_in_force = Column(String(10), default="GTC")
    created_at = now_utc()
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class TokenMetrics(Base):
    """Aggregated per-token metrics used for ML training."""
    __tablename__ = "token_metrics"

    id = uuid_pk()
    symbol = Column(String(20), nullable=False, index=True)
    interval = Column(String(5), nullable=False)          # 1m 5m 15m 1h 4h 1d
    open_time = Column(DateTime(timezone=True), nullable=False, index=True)
    open = Column(Numeric(30, 12))
    high = Column(Numeric(30, 12))
    low = Column(Numeric(30, 12))
    close = Column(Numeric(30, 12))
    volume = Column(Numeric(30, 6))
    quote_volume = Column(Numeric(30, 6))
    trades_count = Column(Integer)
    taker_buy_volume = Column(Numeric(30, 6))
    taker_buy_quote_volume = Column(Numeric(30, 6))

    # Computed indicators (stored for fast retrieval)
    rsi = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    bb_upper = Column(Float)
    bb_lower = Column(Float)
    ema_20 = Column(Float)
    ema_50 = Column(Float)
    ema_200 = Column(Float)
    atr = Column(Float)
    obv = Column(Float)
    vwap = Column(Float)
    adx = Column(Float)

    created_at = now_utc()

    __table_args__ = (
        UniqueConstraint("symbol", "interval", "open_time"),
        Index("idx_token_metrics_symbol_interval_time", "symbol", "interval", "open_time"),
    )


class MLModel(Base):
    __tablename__ = "ml_models"

    id = uuid_pk()
    version = Column(String(40), unique=True, nullable=False)
    model_type = Column(String(40), default="LSTM")
    symbol = Column(String(20))                           # NULL = universal model
    interval = Column(String(5))
    accuracy = Column(Float)
    sharpe_ratio = Column(Float)
    max_drawdown = Column(Float)
    win_rate = Column(Float)
    total_trades_tested = Column(Integer)
    training_hours = Column(Float)
    model_path = Column(Text)
    hyperparams = Column(JSONB)
    metrics = Column(JSONB)
    is_active = Column(Boolean, default=False)
    created_at = now_utc()


class TrainingSession(Base):
    __tablename__ = "training_sessions"

    id = uuid_pk()
    ml_model_id = Column(UUID(as_uuid=True), ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=True)
    status = Column(String(20), default="PENDING")       # PENDING|RUNNING|COMPLETE|FAILED
    stage = Column(String(60))
    progress_pct = Column(Float, default=0.0)
    tokens_trained = Column(Integer, default=0)
    epoch = Column(Integer, default=0)
    total_epochs = Column(Integer)
    train_loss = Column(Float)
    val_loss = Column(Float)
    best_accuracy = Column(Float)
    log_output = Column(Text)
    error = Column(Text)
    started_at = now_utc()
    completed_at = Column(DateTime(timezone=True))


class TaxRecord(Base):
    __tablename__ = "tax_records"

    id = uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    tax_year = Column(String(10), nullable=False, index=True)    # 2024/25
    month = Column(Integer)                                       # 1-12
    year = Column(Integer)

    total_proceeds = Column(Numeric(20, 8), default=0)
    total_cost = Column(Numeric(20, 8), default=0)
    total_gain = Column(Numeric(20, 8), default=0)
    total_loss = Column(Numeric(20, 8), default=0)
    net_gain = Column(Numeric(20, 8), default=0)
    annual_allowance_used = Column(Numeric(20, 8), default=0)
    taxable_gain = Column(Numeric(20, 8), default=0)
    estimated_tax_basic = Column(Numeric(20, 8), default=0)
    estimated_tax_higher = Column(Numeric(20, 8), default=0)

    section_104_data = Column(JSONB)                              # Pool cost basis
    report_path = Column(Text)
    email_sent_at = Column(DateTime(timezone=True))
    created_at = now_utc()


class Alert(Base):
    __tablename__ = "alerts"

    id = uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    alert_type = Column(String(30))         # PRICE|ML_SIGNAL|PORTFOLIO|TAX|SYSTEM
    symbol = Column(String(20))
    message = Column(Text, nullable=False)
    severity = Column(String(10), default="INFO")   # INFO|WARNING|ERROR|CRITICAL
    is_read = Column(Boolean, default=False)
    created_at = now_utc()

    __table_args__ = (Index("idx_alerts_user_read", "user_id", "is_read"),)
