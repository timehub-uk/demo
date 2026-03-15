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
from sqlalchemy.types import Uuid
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ── Helper ────────────────────────────────────────────────────────────────────

def uuid_pk():
    # sqlalchemy.types.Uuid works with both PostgreSQL and SQLite
    return Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

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
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    service = Column(String(50), nullable=False)   # binance | claude | openai | …
    encrypted_key = Column(Text, nullable=False)
    encrypted_secret = Column(Text)
    created_at = now_utc()

    __table_args__ = (UniqueConstraint("user_id", "service"),)


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = uuid_pk()
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
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
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    binance_order_id = Column(String(40), unique=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(Enum("BUY", "SELL", name="trade_side", create_constraint=False), nullable=False)
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
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    trade_id = Column(Uuid(as_uuid=True), ForeignKey("trades.id", ondelete="SET NULL"), nullable=True)
    binance_order_id = Column(String(40), unique=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(Enum("BUY", "SELL", name="order_side", create_constraint=False), nullable=False)
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
    hyperparams = Column(JSON)
    metrics = Column(JSON)
    is_active = Column(Boolean, default=False)
    created_at = now_utc()


class TrainingSession(Base):
    __tablename__ = "training_sessions"

    id = uuid_pk()
    ml_model_id = Column(Uuid(as_uuid=True), ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=True)
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
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
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

    section_104_data = Column(JSON)                              # Pool cost basis
    report_path = Column(Text)
    email_sent_at = Column(DateTime(timezone=True))
    created_at = now_utc()


class PairRegistry(Base):
    """
    Master registry of every discovered trading pair.
    Updated by PairScanner every 15 minutes with 24h market stats and ML scores.
    Cross-ML tradability score is updated separately by PairMLAnalyzer every 5 min.
    """
    __tablename__ = "pair_registry"

    id       = uuid_pk()
    symbol   = Column(String(20), nullable=False, index=True)
    base     = Column(String(15), nullable=False)
    quote    = Column(String(10), nullable=False)

    # 24h market stats (PairScanner)
    last_price       = Column(Numeric(30, 12), default=0)
    price_change_pct = Column(Float,           default=0)
    quote_volume     = Column(Numeric(30, 12), default=0)
    trade_count      = Column(Integer,         default=0)
    high_24h         = Column(Numeric(30, 12), default=0)
    low_24h          = Column(Numeric(30, 12), default=0)

    # PairScanner ML scores (0–1)
    volume_score   = Column(Float, default=0)
    activity_score = Column(Float, default=0)
    momentum_score = Column(Float, default=0)
    priority_score = Column(Float, default=0)
    priority       = Column(String(10), default="LOW")   # HIGH | MEDIUM | LOW

    # Cross-ML tradability (PairMLAnalyzer — updated every 5 min)
    tradability_score = Column(Float, default=0)     # 0–1 composite
    trend_alignment   = Column(Float, default=0)     # fraction of TFs agreeing
    sentiment_score   = Column(Float, default=0)     # −1 to +1
    whale_score       = Column(Float, default=0)     # 0–1 whale activity
    ml_signal         = Column(String(10))           # BUY | HOLD | SELL
    ml_confidence     = Column(Float, default=0)     # 0–1
    regime            = Column(String(20))           # Bull | Bear | Ranging | Volatile
    arb_opportunity   = Column(Boolean, default=False)

    # Accumulation detector (AccumulationDetector)
    accumulation_score   = Column(Float, default=0)  # 0–1 stealth accumulation
    accumulation_label   = Column(String(20))        # NONE | WATCH | ALERT | STRONG

    # Liquidity depth (LiquidityDepthAnalyzer)
    liquidity_score   = Column(Float, default=0)    # 0–1 order-book depth quality
    liquidity_grade   = Column(String(15))          # DEEP | ADEQUATE | THIN | ILLIQUID

    # Volume breakout stage (VolumeBreakoutDetector)
    breakout_stage    = Column(Integer, default=0)  # 0–4
    breakout_score    = Column(Float, default=0)    # 0–1 stage confidence

    first_seen_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at    = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("symbol"),
        Index("idx_pair_registry_priority", "priority"),
        Index("idx_pair_registry_tradability", "tradability_score"),
    )


class PairMLSnapshot(Base):
    """
    Time-series record of per-pair ML analysis results.
    Enables the ML layer to review historical scores and learn which
    signals led to profitable outcomes.
    """
    __tablename__ = "pair_ml_snapshots"

    id        = uuid_pk()
    symbol    = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # Multi-timeframe trends
    trend_15m = Column(String(10))   # UP | SIDEWAYS | DOWN
    trend_30m = Column(String(10))
    trend_1h  = Column(String(10))
    trend_12h = Column(String(10))
    trend_24h = Column(String(10))
    trend_7d  = Column(String(10))
    trend_30d = Column(String(10))

    # ML signals at snapshot time
    ml_signal     = Column(String(10))
    ml_confidence = Column(Float)

    # Market context
    price       = Column(Numeric(30, 12))
    volume_usdt = Column(Numeric(30, 12))
    regime      = Column(String(20))

    # Composite scores
    tradability_score  = Column(Float)
    priority           = Column(String(10))
    accumulation_score = Column(Float)
    liquidity_score    = Column(Float)
    breakout_stage     = Column(Integer)

    created_at = now_utc()

    __table_args__ = (
        Index("idx_pair_ml_symbol_time", "symbol", "timestamp"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id = uuid_pk()
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    alert_type = Column(String(30))         # PRICE|ML_SIGNAL|PORTFOLIO|TAX|SYSTEM
    symbol = Column(String(20))
    message = Column(Text, nullable=False)
    severity = Column(String(10), default="INFO")   # INFO|WARNING|ERROR|CRITICAL
    is_read = Column(Boolean, default=False)
    created_at = now_utc()

    __table_args__ = (Index("idx_alerts_user_read", "user_id", "is_read"),)
