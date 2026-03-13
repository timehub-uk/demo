"""
Risk management engine – enforces position sizing, stop-loss,
take-profit, max drawdown limits, and daily loss limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from loguru import logger

from config import get_settings


@dataclass
class TradeProposal:
    symbol: str
    side: str              # BUY | SELL
    entry_price: Decimal
    quantity: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    confidence: float
    risk_reward: float = 0.0
    approved: bool = False
    reject_reason: str = ""


@dataclass
class RiskMetrics:
    portfolio_value: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    daily_pnl_pct: float = 0.0
    open_trades: int = 0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0


class RiskManager:
    """Enforce trading risk rules before orders are sent."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._peak_value: Decimal = Decimal("0")
        self._daily_start_value: Decimal = Decimal("0")
        self._metrics = RiskMetrics()

    # ── Position sizing ────────────────────────────────────────────────
    def calculate_position_size(
        self,
        portfolio_value: Decimal,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        risk_pct: float | None = None,
    ) -> Decimal:
        """Kelly/fixed-fraction position sizing."""
        risk_pct = risk_pct or self._settings.trading.risk_per_trade_pct
        max_size_pct = self._settings.ml.max_position_size

        risk_amount = portfolio_value * Decimal(str(risk_pct / 100))
        stop_distance = abs(entry_price - stop_loss_price)
        min_stop = entry_price * Decimal("0.001")  # 0.1% minimum stop distance
        if stop_distance < min_stop:
            return Decimal("0")

        qty = risk_amount / stop_distance
        # Cap at max position size
        max_qty = (portfolio_value * Decimal(str(max_size_pct))) / entry_price
        qty = min(qty, max_qty)
        return qty.quantize(Decimal("0.00001"))

    def calculate_stop_loss(self, entry_price: Decimal, side: str) -> Decimal:
        pct = self._settings.ml.stop_loss_pct
        if side == "BUY":
            return entry_price * Decimal(str(1 - pct))
        return entry_price * Decimal(str(1 + pct))

    def calculate_take_profit(self, entry_price: Decimal, side: str) -> Decimal:
        pct = self._settings.ml.take_profit_pct
        if side == "BUY":
            return entry_price * Decimal(str(1 + pct))
        return entry_price * Decimal(str(1 - pct))

    # ── Proposal evaluation ────────────────────────────────────────────
    def evaluate(self, proposal: TradeProposal, metrics: RiskMetrics) -> TradeProposal:
        settings = self._settings

        # 1. Max concurrent trades
        if metrics.open_trades >= settings.trading.max_open_trades:
            proposal.reject_reason = f"Max open trades ({settings.trading.max_open_trades}) reached"
            return proposal

        # 2. Daily loss limit (5 %)
        if metrics.daily_pnl_pct <= -5.0:
            proposal.reject_reason = "Daily loss limit (5%) breached – trading halted"
            logger.warning(proposal.reject_reason)
            return proposal

        # 3. Max drawdown (15 %)
        if metrics.current_drawdown >= 15.0:
            proposal.reject_reason = "Max drawdown (15%) breached – trading paused"
            logger.warning(proposal.reject_reason)
            return proposal

        # 4. Minimum confidence
        min_conf = settings.ml.confidence_threshold
        if proposal.confidence < min_conf:
            proposal.reject_reason = f"Confidence {proposal.confidence:.2%} < threshold {min_conf:.2%}"
            return proposal

        # 5. Minimum risk/reward (1.5:1)
        risk = abs(proposal.entry_price - proposal.stop_loss)
        reward = abs(proposal.take_profit - proposal.entry_price)
        if risk > 0:
            proposal.risk_reward = float(reward / risk)
        if proposal.risk_reward < 1.5:
            proposal.reject_reason = f"Risk/reward {proposal.risk_reward:.2f} < minimum 1.5"
            return proposal

        proposal.approved = True
        return proposal

    # ── Drawdown tracking ──────────────────────────────────────────────
    def update_portfolio_value(self, value: Decimal) -> None:
        if value > self._peak_value:
            self._peak_value = value
        if self._peak_value > 0:
            drawdown = float((self._peak_value - value) / self._peak_value * 100)
            self._metrics.current_drawdown = drawdown

    def set_day_start(self, value: Decimal) -> None:
        self._daily_start_value = value

    def get_metrics(self) -> RiskMetrics:
        return self._metrics
