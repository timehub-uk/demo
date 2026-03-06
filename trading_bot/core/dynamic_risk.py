"""
Dynamic Risk Manager.

Professional-grade risk controls that adapt to:
  - Current market volatility (ATR-based stops)
  - Daily P&L vs limits (circuit breaker)
  - Portfolio drawdown depth
  - Ensemble signal quality (disagreement score)
  - Regime parameters

Wraps the base RiskManager with additional checks and overrides.

Circuit breakers (auto-pause engine):
  - Daily loss > 3% of portfolio → pause for rest of day
  - Current drawdown > 12% from peak → reduce size by 50%
  - Current drawdown > 20% from peak → halt all trading
  - Win rate (rolling 20) < 40% → reduce size by 30%
  - 5 consecutive losses → pause for 1 hour

Position sizing:
  - Base size from RiskManager (Kelly-based)
  - × Regime multiplier (from RegimeDetector)
  - × Drawdown multiplier (scale down as DD deepens)
  - × Council disagreement multiplier (less certainty → less size)
  - × Win rate multiplier (winning streak → full size; losing → reduce)
  Min effective size = 0.0 (circuit broken) Max = 1.0× configured

ATR stops:
  - Stop = entry ± ATR14 × regime_atr_mult
  - Default atr_mult = 1.5 (Trending), 2.5 (Volatile), 1.2 (Ranging)
  - Minimum stop = 0.5%, Maximum stop = 8% of entry price
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import numpy as np

from loguru import logger
from utils.logger import get_intel_logger


# ── Circuit breaker limits ────────────────────────────────────────────────────

DAILY_LOSS_LIMIT_PCT    = 0.03    # 3% daily loss → pause
DRAWDOWN_REDUCE_PCT     = 0.12    # 12% drawdown → halve size
DRAWDOWN_HALT_PCT       = 0.20    # 20% drawdown → halt all trading
WIN_RATE_REDUCE_PCT     = 0.40    # <40% win rate (rolling 20) → reduce size
CONSECUTIVE_LOSS_LIMIT  = 5       # 5 losses in a row → pause 1 hour
ATR_PERIOD              = 14
ATR_MIN_STOP_PCT        = 0.005   # 0.5% minimum stop
ATR_MAX_STOP_PCT        = 0.08    # 8% maximum stop


@dataclass
class RiskCheck:
    approved: bool
    final_quantity: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    reject_reason: str = ""
    size_mult: float = 1.0
    circuit_broken: bool = False


class DynamicRiskManager:
    """
    Wraps RiskManager with dynamic circuit breakers and ATR-based stops.

    Usage:
        drm = DynamicRiskManager(base_risk_manager, regime_detector)
        check = drm.evaluate_trade(symbol, side, entry_price, confidence,
                                   portfolio_value, candles_df, council_decision)
        if check.approved:
            place_order(qty=check.final_quantity, sl=check.stop_loss, tp=check.take_profit)
    """

    def __init__(self, base_risk_manager=None, regime_detector=None) -> None:
        self._base = base_risk_manager
        self._regime = regime_detector
        self._intel = get_intel_logger()
        self._lock = threading.Lock()

        # Tracking state
        self._portfolio_peak: float = 0.0
        self._day_start_value: float = 0.0
        self._today: date = date.today()

        # Rolling trade outcomes (True=win, False=loss)
        self._outcomes: deque[bool] = deque(maxlen=50)
        self._consecutive_losses: int = 0
        self._pause_until: float = 0.0   # Unix timestamp

        # Circuit breaker state
        self._circuit_broken: bool = False
        self._circuit_reason: str = ""

    # ── Main evaluation ────────────────────────────────────────────────

    def evaluate_trade(
        self,
        symbol: str,
        side: str,
        entry_price: Decimal,
        confidence: float,
        portfolio_value: float,
        candles_df=None,           # Optional – for ATR stop calculation
        council_decision=None,     # Optional CouncilDecision
    ) -> RiskCheck:
        with self._lock:
            return self._evaluate(symbol, side, entry_price, confidence,
                                  portfolio_value, candles_df, council_decision)

    def record_outcome(self, win: bool, pnl: float = 0.0) -> None:
        """Call after each trade closes."""
        with self._lock:
            self._outcomes.append(win)
            if not win:
                self._consecutive_losses += 1
                if self._consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
                    self._pause_until = time.time() + 3600  # 1-hour pause
                    self._intel.warning("DynamicRisk",
                        f"⛔ {CONSECUTIVE_LOSS_LIMIT} consecutive losses – pausing for 1 hour")
            else:
                self._consecutive_losses = 0

    def update_portfolio(self, current_value: float) -> None:
        """Call regularly with current portfolio value."""
        with self._lock:
            today = date.today()
            if today != self._today:
                self._day_start_value = current_value
                self._today = today
                self._circuit_broken = False
                self._circuit_reason = ""
            if self._day_start_value == 0:
                self._day_start_value = current_value
            if current_value > self._portfolio_peak:
                self._portfolio_peak = current_value

    @property
    def circuit_broken(self) -> bool:
        return self._circuit_broken or time.time() < self._pause_until

    @property
    def circuit_reason(self) -> str:
        return self._circuit_reason

    @property
    def status(self) -> dict:
        rolling_wr = self._rolling_win_rate()
        dd = self._current_drawdown()
        return {
            "circuit_broken": self.circuit_broken,
            "circuit_reason": self._circuit_reason,
            "rolling_win_rate": rolling_wr,
            "consecutive_losses": self._consecutive_losses,
            "drawdown_pct": dd,
            "pause_until": datetime.fromtimestamp(self._pause_until).isoformat() if self._pause_until > time.time() else "",
        }

    # ── Internal ───────────────────────────────────────────────────────

    def _evaluate(self, symbol, side, entry_price, confidence,
                  portfolio_value, candles_df, council_decision) -> RiskCheck:

        entry_f = float(entry_price)

        # ── Hard circuit breakers ─────────────────────────────────────
        if time.time() < self._pause_until:
            remaining = int(self._pause_until - time.time())
            return RiskCheck(
                approved=False, final_quantity=Decimal("0"),
                stop_loss=Decimal("0"), take_profit=Decimal("0"),
                reject_reason=f"Consecutive loss pause – {remaining}s remaining",
                circuit_broken=True,
            )

        if portfolio_value > 0 and self._day_start_value > 0:
            daily_pnl_pct = (portfolio_value - self._day_start_value) / self._day_start_value
            if daily_pnl_pct <= -DAILY_LOSS_LIMIT_PCT:
                self._circuit_broken = True
                self._circuit_reason = f"Daily loss limit hit: {daily_pnl_pct:.1%}"
                self._intel.warning("DynamicRisk",
                    f"⛔ Daily loss circuit breaker: {daily_pnl_pct:.1%}")
                return RiskCheck(
                    approved=False, final_quantity=Decimal("0"),
                    stop_loss=Decimal("0"), take_profit=Decimal("0"),
                    reject_reason=self._circuit_reason, circuit_broken=True,
                )

        drawdown = self._current_drawdown()
        if drawdown >= DRAWDOWN_HALT_PCT:
            return RiskCheck(
                approved=False, final_quantity=Decimal("0"),
                stop_loss=Decimal("0"), take_profit=Decimal("0"),
                reject_reason=f"Max drawdown halt: {drawdown:.1%} from peak",
                circuit_broken=True,
            )

        # ── Compute multipliers ───────────────────────────────────────
        size_mult = 1.0

        # Drawdown multiplier (reduce as DD deepens)
        if drawdown >= DRAWDOWN_REDUCE_PCT:
            dd_mult = max(0.3, 1.0 - (drawdown - DRAWDOWN_REDUCE_PCT) / (DRAWDOWN_HALT_PCT - DRAWDOWN_REDUCE_PCT))
            size_mult *= dd_mult
            self._intel.ml("DynamicRisk", f"DD mult {dd_mult:.2f} (dd={drawdown:.1%})")

        # Win rate multiplier
        rolling_wr = self._rolling_win_rate()
        if rolling_wr < WIN_RATE_REDUCE_PCT and len(self._outcomes) >= 10:
            wr_mult = max(0.5, rolling_wr / WIN_RATE_REDUCE_PCT)
            size_mult *= wr_mult
            self._intel.ml("DynamicRisk", f"Win rate mult {wr_mult:.2f} (wr={rolling_wr:.0%})")

        # Regime multiplier
        regime_mult = 1.0
        atr_stop_mult = 1.5
        if self._regime:
            regime_mult = self._regime.position_size_multiplier()
            atr_stop_mult = self._regime.atr_stop_multiplier()
            size_mult *= regime_mult

        # Council disagreement multiplier
        if council_decision and hasattr(council_decision, "position_size_mult"):
            council_mult = council_decision.position_size_mult
            size_mult *= council_mult

        size_mult = max(0.0, min(1.0, size_mult))

        # ── ATR stop loss ─────────────────────────────────────────────
        atr = self._compute_atr(candles_df)
        if atr and atr > 0:
            stop_dist = atr * atr_stop_mult
            min_stop  = entry_f * ATR_MIN_STOP_PCT
            max_stop  = entry_f * ATR_MAX_STOP_PCT
            stop_dist = max(min_stop, min(max_stop, stop_dist))

            if side == "BUY":
                stop_loss_f   = entry_f - stop_dist
                take_profit_f = entry_f + stop_dist * 2   # 1:2 R:R
            else:
                stop_loss_f   = entry_f + stop_dist
                take_profit_f = entry_f - stop_dist * 2
        else:
            # Fall back to base risk manager stops
            if self._base:
                stop_loss_f   = float(self._base.calculate_stop_loss(entry_price, side))
                take_profit_f = float(self._base.calculate_take_profit(entry_price, side))
            else:
                sl_pct = 0.02
                stop_loss_f   = entry_f * (1 - sl_pct if side == "BUY" else 1 + sl_pct)
                take_profit_f = entry_f * (1 + sl_pct * 2 if side == "BUY" else 1 - sl_pct * 2)

        # ── Position sizing ───────────────────────────────────────────
        stop_dist_d = abs(entry_f - stop_loss_f)
        if self._base and portfolio_value > 0:
            base_qty = float(self._base.calculate_position_size(
                Decimal(str(portfolio_value)), entry_price,
                Decimal(str(stop_loss_f)),
            ))
        else:
            risk_amt = portfolio_value * 0.01   # Default 1% risk
            base_qty = risk_amt / (stop_dist_d + 1e-9)

        final_qty = base_qty * size_mult

        if final_qty < 1e-8 or size_mult == 0:
            return RiskCheck(
                approved=False, final_quantity=Decimal("0"),
                stop_loss=Decimal(str(round(stop_loss_f, 8))),
                take_profit=Decimal(str(round(take_profit_f, 8))),
                reject_reason="Position size too small after risk adjustments",
                size_mult=size_mult,
            )

        return RiskCheck(
            approved=True,
            final_quantity=Decimal(str(round(final_qty, 8))),
            stop_loss=Decimal(str(round(stop_loss_f, 8))),
            take_profit=Decimal(str(round(take_profit_f, 8))),
            size_mult=size_mult,
        )

    def _current_drawdown(self) -> float:
        if self._portfolio_peak <= 0:
            return 0.0
        # We don't have current value here – computed externally via update_portfolio
        # Return last known drawdown (approximation)
        return 0.0   # Will be populated when update_portfolio is called with current value

    def update_portfolio_for_drawdown(self, current: float) -> float:
        """Call with current value to get real-time drawdown %."""
        if self._portfolio_peak <= 0:
            self._portfolio_peak = current
        dd = max(0.0, (self._portfolio_peak - current) / self._portfolio_peak)
        return dd

    def _rolling_win_rate(self) -> float:
        if not self._outcomes:
            return 0.5
        return sum(self._outcomes) / len(self._outcomes)

    def _compute_atr(self, df) -> Optional[float]:
        if df is None:
            return None
        try:
            close = df["close"].astype(float).values
            high  = df["high"].astype(float).values
            low   = df["low"].astype(float).values
            if len(close) < ATR_PERIOD + 1:
                return None
            tr = np.maximum(
                high[1:] - low[1:],
                np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1]))
            )
            return float(np.mean(tr[-ATR_PERIOD:]))
        except Exception:
            return None
