"""
Arbitrage Auto Trader — Executes detected arbitrage opportunities automatically.

When ArbitrageDetector emits a high-confidence opportunity the auto trader:
  1. Calculates position sizes (configurable USDT budget per trade)
  2. Places simultaneous market/limit orders on both legs via TradingEngine
  3. Monitors spread z-score every MONITOR_INTERVAL_SEC for exit signal
  4. Closes both legs when z-score reverts to Z_EXIT_THRESHOLD
  5. Hard-stops if z-score expands past Z_STOP_THRESHOLD (runaway spread)
  6. Records P&L back to ArbitrageDetector for ML confidence updates

Paper mode: mirrors all logic but calls engine.paper_buy/paper_sell if available,
            otherwise logs trades without sending orders.

Active position structure:
    {
        "pair_key":     "(BTCUSDT, ETHUSDT)",
        "buy_symbol":   "BTCUSDT",
        "sell_symbol":  "ETHUSDT",
        "buy_qty":      0.001,
        "sell_qty":     0.1,
        "buy_price":    65000.0,
        "sell_price":   3500.0,
        "hedge_ratio":  0.9234,
        "entry_z":      2.15,
        "entry_time":   "2025-01-01T12:00:00+00:00",
        "opportunity":  ArbitrageOpportunity,
        "buy_order_id":  "...",
        "sell_order_id": "...",
    }
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Optional

import numpy as np
from loguru import logger
from utils.logger import get_intel_logger


# ── Constants ──────────────────────────────────────────────────────────────────

MONITOR_INTERVAL_SEC = 5          # How often active positions are checked
Z_EXIT_THRESHOLD     = 0.5        # Close when |z| reverts to this
Z_STOP_THRESHOLD     = 3.8        # Emergency close if spread keeps widening
MAX_HOLD_SECONDS     = 3600       # Force-close any position open > 1 hour
BUDGET_USDT          = 100.0      # Default USDT budget per arb leg
BINANCE_FEE_PCT      = 0.001      # 0.1% per leg

# ── Minimum transaction size (UK regulatory / practical floor) ─────────────────
MIN_TRADE_GBP        = 12.0       # £12 minimum per arb leg (UK floor)
GBP_USDT_RATE        = 1.27       # Static GBP/USDT fallback rate
MIN_QTY_USDT         = MIN_TRADE_GBP * GBP_USDT_RATE   # ≈ 15.24 USDT minimum

# ── Cooldown / rate-limit guards ───────────────────────────────────────────────
PAIR_COOLDOWN_SEC    = 300        # Min gap between positions on the same pair (5 min)
API_CALL_DELAY_SEC   = 0.25       # Min delay between successive Binance order calls


class ArbitrageAutoTrader:
    """
    Bridges ArbitrageDetector → TradingEngine.
    Automatically opens and closes pairs-trade positions.
    """

    def __init__(
        self,
        detector=None,          # ArbitrageDetector
        engine=None,            # TradingEngine
        trade_journal=None,     # TradeJournal
        budget_usdt: float = BUDGET_USDT,
        paper: bool = True,     # Paper mode by default for safety
    ) -> None:
        self._det     = detector
        self._engine  = engine
        self._journal = trade_journal
        self._budget  = budget_usdt
        self._paper   = paper
        self._intel   = get_intel_logger()

        self._active: dict[str, dict] = {}    # pair_key → position dict
        self._lock    = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: list[Callable[[dict], None]] = []

        # Cooldown tracking — prevent hammering the same pair repeatedly
        self._pair_cooldowns: dict[str, float] = {}   # pair_key → last close timestamp
        self._last_order_time: float = 0.0            # last Binance order call timestamp

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def active_positions(self) -> list[dict]:
        with self._lock:
            return list(self._active.values())

    @property
    def budget_usdt(self) -> float:
        return self._budget

    @budget_usdt.setter
    def budget_usdt(self, value: float) -> None:
        self._budget = max(MIN_QTY_USDT, float(value))

    @property
    def paper_mode(self) -> bool:
        return self._paper

    @paper_mode.setter
    def paper_mode(self, value: bool) -> None:
        self._paper = value

    def on_trade(self, cb: Callable[[dict], None]) -> None:
        """Register callback invoked on every open/close event."""
        self._callbacks.append(cb)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Subscribe to detector opportunities
        if self._det:
            self._det.on_opportunity(self._on_opportunity)
        # Start position monitor thread
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="arb-auto-trader"
        )
        self._thread.start()
        mode = "PAPER" if self._paper else "LIVE"
        self._intel.ml("ArbitrageAutoTrader",
                       f"Started in {mode} mode  budget=${self._budget:.0f}/trade")

    def stop(self) -> None:
        self._running = False
        self._intel.ml("ArbitrageAutoTrader", "Stopping — closing all open positions")
        with self._lock:
            keys = list(self._active.keys())
        for key in keys:
            self._close_position(key, reason="SHUTDOWN")

    def close_position(self, pair_key: str, reason: str = "MANUAL") -> None:
        """Manually close a specific active position."""
        self._close_position(pair_key, reason=reason)

    # ── Opportunity handler ────────────────────────────────────────────────────

    def _on_opportunity(self, opp) -> None:
        """Called by ArbitrageDetector when a new opportunity is found."""
        # Build a stable pair key (alphabetical order)
        pair_key = f"({min(opp.leg_buy, opp.leg_sell)},{max(opp.leg_buy, opp.leg_sell)})"

        with self._lock:
            if pair_key in self._active:
                return   # Already have a position for this pair

            # Enforce per-pair cooldown after a recent close
            last_close = self._pair_cooldowns.get(pair_key, 0.0)
            elapsed    = time.time() - last_close
            if elapsed < PAIR_COOLDOWN_SEC:
                remaining = PAIR_COOLDOWN_SEC - elapsed
                logger.debug(
                    f"ArbitrageAutoTrader: {pair_key} in cooldown "
                    f"({remaining:.0f}s remaining) — skipping"
                )
                return

        self._open_position(opp, pair_key)

    # ── Position lifecycle ─────────────────────────────────────────────────────

    def _open_position(self, opp, pair_key: str) -> None:
        """Open a new arbitrage position: BUY one leg, SELL the other."""
        buy_sym  = opp.leg_buy
        sell_sym = opp.leg_sell

        # Get current prices from detector price buffers
        buy_price  = self._get_price(buy_sym)
        sell_price = self._get_price(sell_sym)
        if buy_price is None or sell_price is None or buy_price <= 0 or sell_price <= 0:
            logger.warning(f"ArbitrageAutoTrader: price not available for {pair_key}")
            return

        # Compute quantities so both legs ≈ BUDGET_USDT
        buy_qty  = self._budget / buy_price
        # Adjust sell qty by hedge ratio so legs are properly balanced
        sell_qty = (self._budget * opp.hedge_ratio) / sell_price

        # Enforce minimum order size (£12 GBP floor)
        buy_notional  = buy_qty  * buy_price
        sell_notional = sell_qty * sell_price
        if buy_notional < MIN_QTY_USDT or sell_notional < MIN_QTY_USDT:
            logger.warning(
                f"ArbitrageAutoTrader: order below £{MIN_TRADE_GBP:.2f} GBP minimum "
                f"for {pair_key} "
                f"(buy={buy_notional:.2f} USDT, sell={sell_notional:.2f} USDT, "
                f"min={MIN_QTY_USDT:.2f} USDT)"
            )
            return

        buy_order_id  = None
        sell_order_id = None

        if self._paper:
            # Paper mode — simulate order fills instantly at current price
            buy_order_id  = f"PAPER_BUY_{int(time.time()*1000)}"
            sell_order_id = f"PAPER_SELL_{int(time.time()*1000)}"
            self._intel.trade(
                "ArbitrageAutoTrader",
                f"[PAPER] OPEN {opp.arb_type}: "
                f"BUY {buy_qty:.6f} {buy_sym} @ {buy_price:.4f}  "
                f"SELL {sell_qty:.6f} {sell_sym} @ {sell_price:.4f}  "
                f"z={opp.spread_z:+.3f}"
            )
        else:
            # Live mode — place real orders via TradingEngine
            if not self._engine:
                logger.warning("ArbitrageAutoTrader: no engine attached for live trading")
                return
            try:
                # Respect minimum inter-order delay to avoid rate-limit spikes
                gap = time.time() - self._last_order_time
                if gap < API_CALL_DELAY_SEC:
                    time.sleep(API_CALL_DELAY_SEC - gap)

                buy_result = self._engine.manual_buy(
                    symbol=buy_sym,
                    quantity=Decimal(str(round(buy_qty, 6))),
                    price=Decimal(str(round(buy_price, 8))),
                )
                self._last_order_time = time.time()

                # Small gap between the two legs
                time.sleep(API_CALL_DELAY_SEC)

                sell_result = self._engine.manual_sell(
                    symbol=sell_sym,
                    quantity=Decimal(str(round(sell_qty, 6))),
                    price=Decimal(str(round(sell_price, 8))),
                )
                self._last_order_time = time.time()

                buy_order_id  = (buy_result  or {}).get("orderId", "")
                sell_order_id = (sell_result or {}).get("orderId", "")
                self._intel.trade(
                    "ArbitrageAutoTrader",
                    f"[LIVE] OPEN {opp.arb_type}: "
                    f"BUY {buy_qty:.6f} {buy_sym} @ {buy_price:.4f}  "
                    f"SELL {sell_qty:.6f} {sell_sym} @ {sell_price:.4f}"
                )
            except Exception as exc:
                logger.error(
                    f"ArbitrageAutoTrader: order placement failed for {pair_key}: {exc!r}"
                )
                return

        position = {
            "pair_key":      pair_key,
            "arb_type":      opp.arb_type,
            "buy_symbol":    buy_sym,
            "sell_symbol":   sell_sym,
            "buy_qty":       buy_qty,
            "sell_qty":      sell_qty,
            "buy_price":     buy_price,
            "sell_price":    sell_price,
            "hedge_ratio":   opp.hedge_ratio,
            "entry_z":       opp.spread_z,
            "entry_time":    datetime.now(timezone.utc).isoformat(),
            "opportunity":   opp,
            "buy_order_id":  buy_order_id,
            "sell_order_id": sell_order_id,
        }

        with self._lock:
            self._active[pair_key] = position

        self._emit_event("OPEN", position)

    def _close_position(self, pair_key: str, reason: str = "Z_REVERT") -> None:
        """Close both legs of an active arbitrage position."""
        with self._lock:
            position = self._active.pop(pair_key, None)
            # Record close timestamp for cooldown — prevent immediately re-entering
            self._pair_cooldowns[pair_key] = time.time()
        if not position:
            return

        buy_sym  = position["buy_symbol"]
        sell_sym = position["sell_symbol"]
        buy_qty  = position["buy_qty"]
        sell_qty = position["sell_qty"]

        # Current prices for exit
        exit_buy  = self._get_price(buy_sym)  or position["buy_price"]
        exit_sell = self._get_price(sell_sym) or position["sell_price"]

        if self._paper:
            self._intel.trade(
                "ArbitrageAutoTrader",
                f"[PAPER] CLOSE {reason}: "
                f"SELL {buy_qty:.6f} {buy_sym} @ {exit_buy:.4f}  "
                f"BUY  {sell_qty:.6f} {sell_sym} @ {exit_sell:.4f}"
            )
        else:
            # Reverse both legs
            if self._engine:
                try:
                    gap = time.time() - self._last_order_time
                    if gap < API_CALL_DELAY_SEC:
                        time.sleep(API_CALL_DELAY_SEC - gap)

                    self._engine.manual_sell(
                        buy_sym, Decimal(str(round(buy_qty, 6))),
                        Decimal(str(round(exit_buy, 8)))
                    )
                    self._last_order_time = time.time()
                    time.sleep(API_CALL_DELAY_SEC)

                    self._engine.manual_buy(
                        sell_sym, Decimal(str(round(sell_qty, 6))),
                        Decimal(str(round(exit_sell, 8)))
                    )
                    self._last_order_time = time.time()
                except Exception as exc:
                    logger.error(
                        f"ArbitrageAutoTrader: close order failed for {pair_key} "
                        f"[{reason}]: {exc!r}"
                    )

        # P&L calculation
        entry_buy_val  = position["buy_price"]  * buy_qty
        entry_sell_val = position["sell_price"] * sell_qty
        exit_buy_val   = exit_buy  * buy_qty
        exit_sell_val  = exit_sell * sell_qty

        pnl_buy  = exit_buy_val  - entry_buy_val    # profit on long leg
        pnl_sell = entry_sell_val - exit_sell_val    # profit on short leg
        gross_pnl = pnl_buy + pnl_sell
        total_fees = BINANCE_FEE_PCT * (entry_buy_val + entry_sell_val
                                        + exit_buy_val  + exit_sell_val)
        net_pnl = gross_pnl - total_fees

        # Record result to detector for ML weight update
        # Always use normalised (alphabetical) pair key so it matches _pair_stats
        pair = (min(buy_sym, sell_sym), max(buy_sym, sell_sym))
        if self._det:
            try:
                self._det.record_result(pair, net_pnl)
            except Exception:
                pass

        entry_time = position.get("entry_time", "")
        hold_secs = 0.0
        try:
            from datetime import datetime, timezone
            entry_dt = datetime.fromisoformat(entry_time)
            hold_secs = (datetime.now(timezone.utc) - entry_dt).total_seconds()
        except Exception:
            pass

        self._intel.ml(
            "ArbitrageAutoTrader",
            f"CLOSED [{reason}]  {buy_sym}/{sell_sym}  "
            f"gross={gross_pnl:+.4f}  fees=-{total_fees:.4f}  net={net_pnl:+.4f}  "
            f"held={hold_secs:.0f}s"
        )

        close_event = dict(position)
        close_event.update({
            "exit_buy_price":  exit_buy,
            "exit_sell_price": exit_sell,
            "gross_pnl":       gross_pnl,
            "net_pnl":         net_pnl,
            "fees":            total_fees,
            "hold_seconds":    hold_secs,
            "close_reason":    reason,
        })
        self._emit_event("CLOSE", close_event)

    # ── Position monitor ───────────────────────────────────────────────────────

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._monitor_positions()
            except Exception as exc:
                logger.warning(f"ArbitrageAutoTrader monitor error: {exc}")
            time.sleep(MONITOR_INTERVAL_SEC)

    def _monitor_positions(self) -> None:
        with self._lock:
            keys = list(self._active.keys())

        for key in keys:
            with self._lock:
                pos = self._active.get(key)
            if not pos:
                continue

            # Check age
            try:
                entry_dt  = datetime.fromisoformat(pos["entry_time"])
                hold_secs = (datetime.now(timezone.utc) - entry_dt).total_seconds()
            except Exception:
                hold_secs = 0.0

            if hold_secs > MAX_HOLD_SECONDS:
                self._close_position(key, reason="MAX_HOLD")
                continue

            # Check z-score reversion
            if self._det:
                current_z = self._get_current_z(pos)
                if current_z is not None:
                    if abs(current_z) <= Z_EXIT_THRESHOLD:
                        self._close_position(key, reason="Z_REVERT")
                    elif abs(current_z) >= Z_STOP_THRESHOLD:
                        self._close_position(key, reason="Z_STOP")

    def _get_current_z(self, position: dict) -> Optional[float]:
        """Read latest z-score for this position's pair from detector."""
        if not self._det:
            return None
        buy_sym  = position["buy_symbol"]
        sell_sym = position["sell_symbol"]
        buf_a = np.array(self._det.get_price_buffer(buy_sym),  dtype=float)
        buf_b = np.array(self._det.get_price_buffer(sell_sym), dtype=float)
        if len(buf_a) < 5 or len(buf_b) < 5:
            return None
        # Recompute spread z-score using log prices
        from core.arbitrage_detector import _rolling_ols_beta, _spread_zscore
        log_a = np.log(np.where(buf_a > 0, buf_a, 1e-10))
        log_b = np.log(np.where(buf_b > 0, buf_b, 1e-10))
        beta = _rolling_ols_beta(log_a, log_b)
        return _spread_zscore(log_a, log_b, beta)

    # ── Price helper ───────────────────────────────────────────────────────────

    def _get_price(self, symbol: str) -> Optional[float]:
        if self._det:
            price = self._det.get_latest_price(symbol)
            if price is not None:
                return price
        if self._engine:
            try:
                ticker = self._engine._client.get_symbol_ticker(symbol=symbol)
                return float(ticker["price"])
            except Exception:
                pass
        return None

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def _emit_event(self, event_type: str, position: dict) -> None:
        event = {"type": event_type, **position}
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass
