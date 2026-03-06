"""
Ping-Pong Trader – Sideways Market Range Strategy.

Automatically buys near the range low (support) and sells near the range
high (resistance) when the market is detected to be in a RANGING regime.

Strategy logic:
  1. RegimeDetector must report RANGING or VOLATILE (no clear trend).
  2. Calculate the trading range using a rolling Bollinger Band (20-bar, 2σ)
     plus a Donchian channel (highest high / lowest low of last N bars).
  3. Divide the range into three zones:
       BUY ZONE   ≤ lower 25% of range   (near support)
       SELL ZONE  ≥ upper 25% of range   (near resistance)
       NEUTRAL    middle 50%
  4. If price enters the BUY ZONE and no long is open → place BUY.
     TP = midpoint of range or upper band.  SL = just below the range low.
  5. If price enters the SELL ZONE and long position open → close/flip to SELL.
     TP = midpoint of range or lower band.  SL = just above the range high.
  6. Circuit breaker: if 3 consecutive losses are recorded → pause for
     PAUSE_BARS bars and wait for a fresh range to establish.
  7. Auto-disables when RegimeDetector switches to TRENDING_UP / TRENDING_DOWN.

Thread model:
  - Main loop runs in a daemon thread checking prices every POLL_INTERVAL_SEC.
  - All state mutations protected by a lock.
  - Emits callbacks on trade open/close/state change.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

import numpy as np
from loguru import logger

from utils.logger import get_intel_logger


# ── Constants ──────────────────────────────────────────────────────────────────

POLL_INTERVAL_SEC   = 5        # Price polling interval
RANGE_LOOKBACK      = 20       # Bars used for Bollinger / Donchian
ZONE_PCT            = 0.25     # Bottom/top 25% of range is a trigger zone
BB_STD              = 2.0      # Bollinger band std multiplier
DEFAULT_RISK_PCT    = 0.01     # 1% of portfolio per trade
MIN_RANGE_PCT       = 0.005    # Minimum 0.5% range to trade (avoid flat noise)
CONSECUTIVE_LOSS_LIMIT = 3     # Pause after this many consecutive losses
PAUSE_BARS          = 10       # Bars to sit out after consecutive losses
SL_BUFFER           = 0.003    # SL placed 0.3% beyond range extremes


class PPState(str, Enum):
    IDLE       = "idle"
    WATCHING   = "watching"
    LONG       = "long"
    SHORT      = "short"
    PAUSED     = "paused"
    DISABLED   = "disabled"


@dataclass
class PPTrade:
    symbol: str
    side: str                     # BUY | SELL
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    entry_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    exit_price: float = 0.0
    exit_time: str = ""
    pnl: float = 0.0
    exit_reason: str = ""


@dataclass
class PPStatus:
    symbol: str
    state: PPState
    regime: str
    range_low: float
    range_high: float
    range_pct: float
    current_price: float
    zone: str                     # BUY_ZONE | SELL_ZONE | NEUTRAL
    active_trade: Optional[PPTrade]
    consecutive_losses: int
    total_trades: int
    total_pnl: float


class PingPongTrader:
    """
    Buys at range lows, sells at range highs in sideways markets.

    Works alongside (not inside) AutoTrader – PingPong runs independently
    on its own thread and is designed for RANGING regime only.

    Wire into the main app:
        pp = PingPongTrader(engine=engine, regime_detector=regime, ...)
        pp.on_state_change(my_ui_callback)
        pp.on_trade(my_ui_callback)
        pp.start(symbol="BTCUSDT")
    """

    def __init__(
        self,
        engine=None,
        regime_detector=None,
        dynamic_risk=None,
        trade_journal=None,
        binance_client=None,
    ) -> None:
        self._engine         = engine
        self._regime         = regime_detector
        self._drm            = dynamic_risk
        self._journal        = trade_journal
        self._client         = binance_client
        self._intel          = get_intel_logger()

        self._symbol:  str         = "BTCUSDT"
        self._state:   PPState     = PPState.IDLE
        self._running: bool        = False
        self._active_trade: Optional[PPTrade] = None
        self._history:  list[PPTrade]         = []

        self._range_low:  float = 0.0
        self._range_high: float = 0.0
        self._price_history: list[float] = []   # rolling close prices
        self._pause_counter: int  = 0
        self._consecutive_losses: int = 0
        self._total_pnl: float = 0.0

        self._enabled_regimes = {"RANGING", "VOLATILE"}   # activate in these
        self._risk_pct   = DEFAULT_RISK_PCT
        self._lock       = threading.Lock()
        self._thread: Optional[threading.Thread] = None

        self._state_cbs: list[Callable] = []
        self._trade_cbs: list[Callable] = []

    # ── Configuration ──────────────────────────────────────────────────────────

    def set_symbol(self, symbol: str) -> None:
        with self._lock:
            self._symbol = symbol

    def set_risk_pct(self, pct: float) -> None:
        """Set fraction of portfolio risked per trade (default 1%)."""
        self._risk_pct = max(0.001, min(0.05, pct))

    def set_enabled_regimes(self, regimes: set[str]) -> None:
        """Override which regimes allow ping-pong trading."""
        self._enabled_regimes = {r.upper() for r in regimes}

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def on_state_change(self, cb: Callable[[PPStatus], None]) -> None:
        self._state_cbs.append(cb)

    def on_trade(self, cb: Callable[[PPTrade], None]) -> None:
        self._trade_cbs.append(cb)

    # ── Control ────────────────────────────────────────────────────────────────

    def start(self, symbol: str = "BTCUSDT") -> None:
        if self._running:
            return
        self._symbol  = symbol
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="ping-pong-trader"
        )
        self._thread.start()
        self._intel.ml("PingPong", f"Started on {symbol}")

    def stop(self) -> None:
        self._running = False
        self._intel.ml("PingPong", "Stopped")

    def set_symbol_live(self, symbol: str) -> None:
        """Hot-switch symbol while running."""
        with self._lock:
            if symbol != self._symbol:
                self._symbol = symbol
                self._price_history.clear()
                self._range_low = self._range_high = 0.0
                self._active_trade = None
                self._set_state(PPState.WATCHING)
                self._intel.ml("PingPong", f"Symbol changed to {symbol}")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def status(self) -> PPStatus:
        with self._lock:
            price = self._price_history[-1] if self._price_history else 0.0
            return PPStatus(
                symbol=self._symbol,
                state=self._state,
                regime=self._current_regime(),
                range_low=self._range_low,
                range_high=self._range_high,
                range_pct=self._range_pct(),
                current_price=price,
                zone=self._classify_zone(price),
                active_trade=self._active_trade,
                consecutive_losses=self._consecutive_losses,
                total_trades=len(self._history),
                total_pnl=self._total_pnl,
            )

    # ── Main loop ──────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        self._set_state(PPState.WATCHING)
        while self._running:
            try:
                self._tick()
            except Exception as exc:
                logger.warning(f"PingPong tick error: {exc}")
            time.sleep(POLL_INTERVAL_SEC)
        self._set_state(PPState.IDLE)

    def _tick(self) -> None:
        regime = self._current_regime()

        # Check if regime allows trading
        if regime not in self._enabled_regimes:
            if self._state not in (PPState.IDLE, PPState.DISABLED):
                self._intel.ml("PingPong",
                    f"Regime {regime} – suspending ping-pong (not RANGING)")
                self._close_active_trade("REGIME_CHANGE")
                self._set_state(PPState.WATCHING)
            return

        # Fetch current price
        price = self._fetch_price(self._symbol)
        if price <= 0:
            return

        with self._lock:
            # Accumulate price history
            self._price_history.append(price)
            if len(self._price_history) > RANGE_LOOKBACK * 3:
                self._price_history.pop(0)

            if len(self._price_history) < RANGE_LOOKBACK:
                return   # Not enough history yet

            # Recalculate range
            self._update_range()

            rng_pct = self._range_pct()
            if rng_pct < MIN_RANGE_PCT:
                return   # Market is too flat to trade

            # Paused mode
            if self._state == PPState.PAUSED:
                self._pause_counter -= 1
                if self._pause_counter <= 0:
                    self._set_state(PPState.WATCHING)
                    self._consecutive_losses = 0
                    self._intel.ml("PingPong", "Pause over – resuming")
                return

            zone = self._classify_zone(price)

            # ── Manage existing trade ──────────────────────────────────
            if self._active_trade:
                self._manage_open_trade(price, zone)
                return

            # ── Open new trade ─────────────────────────────────────────
            if zone == "BUY_ZONE" and self._state == PPState.WATCHING:
                self._open_trade("BUY", price)
            elif zone == "SELL_ZONE" and self._state == PPState.WATCHING:
                self._open_trade("SELL", price)

    # ── Trade management ───────────────────────────────────────────────────────

    def _open_trade(self, side: str, price: float) -> None:
        tp = self._range_high - (self._range_high - self._range_low) * 0.1  \
             if side == "BUY" else \
             self._range_low  + (self._range_high - self._range_low) * 0.1
        sl = self._range_low  * (1 - SL_BUFFER) if side == "BUY" else \
             self._range_high * (1 + SL_BUFFER)

        qty = self._calc_quantity(price, sl)
        if qty <= 0:
            return

        trade = PPTrade(
            symbol=self._symbol, side=side,
            entry_price=price, quantity=qty,
            stop_loss=sl, take_profit=tp,
        )

        # Execute via engine
        executed = self._execute(side, self._symbol, qty, price)
        if not executed:
            return

        self._active_trade = trade
        self._set_state(PPState.LONG if side == "BUY" else PPState.SHORT)

        # Log to trade journal
        if self._journal:
            try:
                self._journal.open_trade(
                    symbol=self._symbol, side=side,
                    entry_price=price, quantity=qty,
                    stop_loss=sl, take_profit=tp,
                    regime=self._current_regime(),
                    source_signals={"ping_pong": 1.0},
                )
            except Exception:
                pass

        self._intel.trade("PingPong",
            f"OPEN {side} {self._symbol} @ {price:.4f}  "
            f"SL={sl:.4f}  TP={tp:.4f}  qty={qty:.6f}")
        for cb in self._trade_cbs:
            try:
                cb(trade)
            except Exception:
                pass

    def _manage_open_trade(self, price: float, zone: str) -> None:
        trade = self._active_trade
        if trade is None:
            return

        hit_sl = (trade.side == "BUY"  and price <= trade.stop_loss) or \
                 (trade.side == "SELL" and price >= trade.stop_loss)
        hit_tp = (trade.side == "BUY"  and price >= trade.take_profit) or \
                 (trade.side == "SELL" and price <= trade.take_profit)
        # Flip: price reached opposite zone while in a trade
        flip   = (trade.side == "BUY"  and zone == "SELL_ZONE") or \
                 (trade.side == "SELL" and zone == "BUY_ZONE")

        if hit_sl:
            self._close_active_trade("STOP_LOSS", price)
        elif hit_tp:
            self._close_active_trade("TAKE_PROFIT", price)
        elif flip:
            self._close_active_trade("FLIP", price)
            # Immediately open opposite side
            new_side = "SELL" if trade.side == "BUY" else "BUY"
            self._open_trade(new_side, price)

    def _close_active_trade(self, reason: str, price: float = 0.0) -> None:
        trade = self._active_trade
        if trade is None:
            return
        if price <= 0:
            price = self._fetch_price(trade.symbol)

        exit_side = "SELL" if trade.side == "BUY" else "BUY"
        self._execute(exit_side, trade.symbol, trade.quantity, price)

        trade.exit_price  = price
        trade.exit_time   = datetime.now(timezone.utc).isoformat()
        trade.exit_reason = reason
        mult = 1 if trade.side == "BUY" else -1
        trade.pnl = mult * (price - trade.entry_price) * trade.quantity

        self._total_pnl += trade.pnl
        self._history.append(trade)

        if trade.pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        self._intel.trade("PingPong",
            f"CLOSE {trade.side} {trade.symbol} @ {price:.4f}  "
            f"pnl=${trade.pnl:+,.4f}  reason={reason}")

        if self._consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
            self._intel.warning("PingPong",
                f"{self._consecutive_losses} consecutive losses – pausing {PAUSE_BARS} bars")
            self._pause_counter = PAUSE_BARS
            self._set_state(PPState.PAUSED)
        else:
            self._set_state(PPState.WATCHING)

        self._active_trade = None

        for cb in self._trade_cbs:
            try:
                cb(trade)
            except Exception:
                pass

    # ── Range calculation ──────────────────────────────────────────────────────

    def _update_range(self) -> None:
        prices = np.array(self._price_history[-RANGE_LOOKBACK:])
        mean = prices.mean()
        std  = prices.std()

        bb_lower = mean - BB_STD * std
        bb_upper = mean + BB_STD * std
        dc_lower = prices.min()
        dc_upper = prices.max()

        # Take the tighter of the two (avoid massive outlier spikes)
        self._range_low  = max(bb_lower, dc_lower)
        self._range_high = min(bb_upper, dc_upper)

        # Sanity check
        if self._range_high <= self._range_low:
            self._range_low  = dc_lower
            self._range_high = dc_upper

    def _range_pct(self) -> float:
        if self._range_low <= 0:
            return 0.0
        return (self._range_high - self._range_low) / self._range_low

    def _classify_zone(self, price: float) -> str:
        if self._range_high <= self._range_low:
            return "NEUTRAL"
        rng = self._range_high - self._range_low
        rel = (price - self._range_low) / rng
        if rel <= ZONE_PCT:
            return "BUY_ZONE"
        if rel >= (1 - ZONE_PCT):
            return "SELL_ZONE"
        return "NEUTRAL"

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _current_regime(self) -> str:
        if self._regime:
            try:
                return str(self._regime.current().regime)
            except Exception:
                pass
        return "UNKNOWN"

    def _fetch_price(self, symbol: str) -> float:
        try:
            if self._client:
                ticker = self._client.get_ticker(symbol)
                if ticker:
                    return float(ticker.get("lastPrice", 0))
        except Exception:
            pass
        # Fallback: read from Redis
        try:
            from db.redis_client import RedisClient
            d = RedisClient().get_ticker(symbol)
            if d:
                return float(d.get("price", 0))
        except Exception:
            pass
        return 0.0

    def _calc_quantity(self, price: float, stop_loss: float) -> float:
        """Kelly-inspired fixed-fractional position sizing based on risk %."""
        if price <= 0 or stop_loss <= 0:
            return 0.0
        # Use dynamic risk manager if available
        if self._drm:
            try:
                risk_pct = self._drm.position_risk_pct
                portfolio_value = self._drm.portfolio_value
                if portfolio_value and risk_pct:
                    risk_amount = portfolio_value * risk_pct
                    per_unit_risk = abs(price - stop_loss)
                    if per_unit_risk > 0:
                        return round(risk_amount / per_unit_risk, 6)
            except Exception:
                pass
        # Fallback: hard-coded small size
        return round(self._risk_pct * 100 / price, 6)

    def _execute(self, side: str, symbol: str, qty: float, price: float) -> bool:
        if not self._engine:
            return True   # Demo mode – pretend it worked
        try:
            from decimal import Decimal
            if side == "BUY":
                result = self._engine.manual_buy(symbol, Decimal(str(qty)), Decimal(str(price)))
            else:
                result = self._engine.manual_sell(symbol, Decimal(str(qty)), Decimal(str(price)))
            return result is not None
        except Exception as exc:
            logger.warning(f"PingPong execute error: {exc}")
            return False

    def _set_state(self, state: PPState) -> None:
        if self._state == state:
            return
        self._state = state
        st = self.status
        for cb in self._state_cbs:
            try:
                cb(st)
            except Exception:
                pass
