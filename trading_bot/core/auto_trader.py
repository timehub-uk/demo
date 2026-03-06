"""
AutoTrader – Aim, Execute, Monitor, Profit, Repeat.

Runs a fully autonomous trading cycle:

  ┌─────────────────────────────────────────────────────────┐
  │  SCANNING  → MarketScanner produces ScanSummary        │
  │      ↓                                                  │
  │  AIMING    → User confirms OR auto-approve fires        │
  │      ↓                                                  │
  │  ENTERING  → DynamicRisk sizes position, places order   │
  │      ↓                                                  │
  │  MONITORING → Watches price tick-by-tick vs SL/TP       │
  │      ↓                                                  │
  │  EXITING   → TP hit → log win; SL hit → log loss        │
  │      ↓                                                  │
  │  COOLDOWN  → Optional pause after loss (15 min)         │
  │      ↓                                                  │
  │  back to SCANNING                                       │
  └─────────────────────────────────────────────────────────┘

AutoTrader can operate in two modes:
  - SEMI_AUTO: presents recommendation, waits for human "take aim" approval
  - FULL_AUTO: executes automatically when confidence ≥ auto_threshold

Safety guards applied at every entry:
  - DynamicRisk circuit breaker check
  - Min confidence threshold per-trade
  - Max simultaneous positions (default 1 at a time from scanner)
  - Cool-off period after stop-loss hit
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from ml.market_scanner import PairScore, ScanSummary

from loguru import logger
from utils.logger import get_intel_logger


class AutoTraderMode(str, Enum):
    SEMI_AUTO = "semi_auto"   # Requires human "take aim" press
    FULL_AUTO = "full_auto"   # Executes automatically


class CycleState(str, Enum):
    IDLE      = "idle"
    SCANNING  = "scanning"
    AIMING    = "aiming"       # Waiting for approval
    ENTERING  = "entering"
    MONITORING = "monitoring"
    EXITING   = "exiting"
    COOLDOWN  = "cooldown"


@dataclass
class ActiveTrade:
    symbol: str
    side: str
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    confidence: float
    trade_id: str = ""
    open_time: str = ""
    paper: bool = False
    expected_rr: float = 2.0
    source_scan_score: float = 0.0


@dataclass
class CycleResult:
    cycle_num: int
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    exit_reason: str          # TP | SL | MANUAL | TIMEOUT
    duration_sec: float
    scan_to_entry_sec: float
    timestamp: str = ""


class AutoTrader:
    """
    Autonomous scan→trade→monitor→repeat loop.

    Usage:
        at = AutoTrader(engine, scanner, dynamic_risk, trade_journal)
        at.set_mode(AutoTraderMode.SEMI_AUTO)
        at.on_state_change(my_ui_callback)
        at.on_recommendation(my_ui_callback)
        at.start()
        # In SEMI_AUTO: call at.take_aim() when user approves
        # In FULL_AUTO: runs completely autonomously
    """

    DEFAULT_AUTO_THRESHOLD   = 0.72    # Min confidence for FULL_AUTO
    MONITOR_INTERVAL_SEC     = 2       # Price check frequency
    SCAN_INTERVAL_SEC        = 300     # Re-scan every 5 minutes
    COOLDOWN_AFTER_LOSS_SEC  = 900     # 15 min cool-off after stop hit
    TIMEOUT_TRADE_SEC        = 4 * 3600  # Close after 4 hours regardless
    MAX_SIMULTANEOUS         = 1       # Max concurrent scanner-initiated positions

    def __init__(
        self,
        engine=None,
        scanner=None,
        dynamic_risk=None,
        trade_journal=None,
        binance_client=None,
    ) -> None:
        self._engine   = engine
        self._scanner  = scanner
        self._drm      = dynamic_risk
        self._journal  = trade_journal
        self._client   = binance_client
        self._intel    = get_intel_logger()

        self._mode     = AutoTraderMode.SEMI_AUTO
        self._state    = CycleState.IDLE
        self._running  = False
        self._auto_threshold = self.DEFAULT_AUTO_THRESHOLD

        self._active_trade: Optional[ActiveTrade] = None
        self._pending_recommendation = None   # ScanSummary recommendation
        self._cycle_num  = 0
        self._cycle_results: list[CycleResult] = []
        self._cooldown_until: float = 0.0
        self._last_scan_time: float = 0.0

        self._state_callbacks:  list[Callable] = []
        self._rec_callbacks:    list[Callable] = []
        self._result_callbacks: list[Callable] = []
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    # ── Configuration ──────────────────────────────────────────────────

    def set_mode(self, mode: AutoTraderMode) -> None:
        self._mode = mode
        self._intel.ml("AutoTrader", f"Mode set to {mode.value}")

    def set_auto_threshold(self, threshold: float) -> None:
        self._auto_threshold = max(0.60, min(0.99, threshold))

    # ── Callbacks ──────────────────────────────────────────────────────

    def on_state_change(self, cb: Callable[[str], None]) -> None:
        self._state_callbacks.append(cb)

    def on_recommendation(self, cb: "Callable[[PairScore, ScanSummary], None]") -> None:
        """Called when a scan produces a recommendation – pass to UI."""
        self._rec_callbacks.append(cb)

    def on_cycle_result(self, cb: Callable[[CycleResult], None]) -> None:
        self._result_callbacks.append(cb)

    # ── Control ────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._cycle_loop, daemon=True, name="auto-trader"
        )
        self._thread.start()
        self._intel.ml("AutoTrader",
            f"🤖 AutoTrader started | mode={self._mode.value} | "
            f"auto_threshold={self._auto_threshold:.0%} | "
            f"scan_every={self.SCAN_INTERVAL_SEC}s")

    def stop(self) -> None:
        self._running = False
        self._intel.ml("AutoTrader", "AutoTrader stopped")

    def take_aim(self) -> bool:
        """
        In SEMI_AUTO mode: human presses "Take Aim" to approve the recommendation.
        Returns True if a trade was initiated.
        """
        with self._lock:
            if self._state != CycleState.AIMING or not self._pending_recommendation:
                return False
            rec = self._pending_recommendation
        self._intel.ml("AutoTrader",
            f"🎯 Take Aim approved by user: {rec.ensemble_signal} {rec.symbol}")
        self._set_state(CycleState.ENTERING)
        threading.Thread(
            target=self._enter_trade, args=(rec,), daemon=True
        ).start()
        return True

    def manual_exit(self) -> None:
        """Force-close the active trade immediately."""
        if self._active_trade:
            self._intel.ml("AutoTrader", "🛑 Manual exit requested")
            self._exit_trade("MANUAL")

    @property
    def state(self) -> CycleState:
        return self._state

    @property
    def active_trade(self) -> Optional[ActiveTrade]:
        return self._active_trade

    @property
    def cycle_results(self) -> list[CycleResult]:
        return list(self._cycle_results)

    @property
    def stats(self) -> dict:
        results = self._cycle_results
        wins = [r for r in results if r.pnl > 0]
        return {
            "total_cycles":  self._cycle_num,
            "total_trades":  len(results),
            "wins":          len(wins),
            "losses":        len(results) - len(wins),
            "win_rate":      len(wins) / max(1, len(results)),
            "total_pnl":     sum(r.pnl for r in results),
            "best_trade":    max((r.pnl_pct for r in results), default=0),
            "worst_trade":   min((r.pnl_pct for r in results), default=0),
            "avg_duration_min": (
                sum(r.duration_sec for r in results) / max(1, len(results)) / 60
            ),
        }

    # ── Main cycle loop ────────────────────────────────────────────────

    def _cycle_loop(self) -> None:
        while self._running:
            try:
                self._run_one_cycle()
            except Exception as exc:
                logger.error(f"AutoTrader cycle error: {exc}")
                time.sleep(10)

    def _run_one_cycle(self) -> None:
        # Don't cycle if already in a trade
        if self._state in (CycleState.MONITORING, CycleState.ENTERING, CycleState.EXITING):
            time.sleep(5)
            return

        # Cool-off period
        if time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            self._set_state(CycleState.COOLDOWN)
            self._intel.ml("AutoTrader", f"⏳ Cool-off: {remaining}s remaining")
            time.sleep(min(30, remaining))
            return

        # Check circuit breaker
        if self._drm and self._drm.circuit_broken:
            self._intel.ml("AutoTrader",
                f"⛔ Circuit breaker active: {self._drm.status['circuit_reason']} – waiting…")
            self._set_state(CycleState.IDLE)
            time.sleep(60)
            return

        # Scan
        since_last = time.time() - self._last_scan_time
        if since_last < self.SCAN_INTERVAL_SEC and self._last_scan_time > 0:
            time.sleep(5)
            return

        self._set_state(CycleState.SCANNING)
        self._last_scan_time = time.time()

        if self._scanner:
            summary = self._scanner.scan_now()
        else:
            time.sleep(5)
            return

        rec = summary.recommendation
        if not rec:
            self._intel.ml("AutoTrader", "📭 No recommendation from scan – waiting")
            self._set_state(CycleState.IDLE)
            time.sleep(30)
            return

        # Emit recommendation to UI
        with self._lock:
            self._pending_recommendation = rec
        for cb in self._rec_callbacks:
            try:
                cb(rec, summary)
            except Exception:
                pass

        # Decide whether to act
        if self._mode == AutoTraderMode.FULL_AUTO:
            if rec.ensemble_confidence >= self._auto_threshold:
                self._intel.ml("AutoTrader",
                    f"🤖 FULL_AUTO: auto-firing on {rec.symbol} conf={rec.ensemble_confidence:.0%}")
                self._set_state(CycleState.ENTERING)
                self._enter_trade(rec)
            else:
                self._intel.ml("AutoTrader",
                    f"🔕 Confidence {rec.ensemble_confidence:.0%} < threshold "
                    f"{self._auto_threshold:.0%} – waiting for next scan")
                self._set_state(CycleState.IDLE)
                time.sleep(self.SCAN_INTERVAL_SEC)
        else:
            # SEMI_AUTO: present to user, wait for take_aim()
            self._set_state(CycleState.AIMING)
            self._intel.ml("AutoTrader",
                f"🎯 AIMING: {rec.direction_emoji} {rec.ensemble_signal} {rec.symbol} "
                f"conf={rec.ensemble_confidence:.0%} RR={rec.rr_ratio:.1f} "
                f"EV={rec.expected_value:.2f} – awaiting approval")
            # Wait up to scan_interval for approval
            deadline = time.time() + self.SCAN_INTERVAL_SEC
            while time.time() < deadline and self._running:
                if self._state != CycleState.AIMING:
                    return  # take_aim() was called
                time.sleep(1)
            # No approval → scan again
            if self._state == CycleState.AIMING:
                self._intel.ml("AutoTrader", "⏰ Approval timeout – rescanning")
                with self._lock:
                    self._pending_recommendation = None
                self._set_state(CycleState.IDLE)

    # ── Trade execution ────────────────────────────────────────────────

    def _enter_trade(self, rec) -> None:
        self._cycle_num += 1
        self._intel.ml("AutoTrader",
            f"▶ Entering trade #{self._cycle_num}: {rec.ensemble_signal} {rec.symbol} "
            f"@ {rec.current_price:.4f}")
        self._set_state(CycleState.ENTERING)

        try:
            # Get current price
            price = self._get_live_price(rec.symbol) or rec.current_price
            if price <= 0:
                raise ValueError(f"Cannot get live price for {rec.symbol}")

            # Compute ATR stops
            atr_pct = rec.atr_pct or 0.02
            if rec.ensemble_signal == "BUY":
                sl_price = price * (1 - atr_pct * 1.5)
                tp_price = price * (1 + atr_pct * 3.0)   # 1:2 minimum R:R
            else:
                sl_price = price * (1 + atr_pct * 1.5)
                tp_price = price * (1 - atr_pct * 3.0)

            # Get portfolio value
            portfolio_value = self._get_portfolio_value()
            if portfolio_value <= 0:
                portfolio_value = 10_000.0

            # Dynamic risk check
            quantity = 0.0
            if self._drm:
                check = self._drm.evaluate_trade(
                    symbol=rec.symbol, side=rec.ensemble_signal,
                    entry_price=Decimal(str(price)),
                    confidence=rec.ensemble_confidence,
                    portfolio_value=portfolio_value,
                )
                if not check.approved:
                    raise ValueError(f"DynamicRisk rejected: {check.reject_reason}")
                quantity  = float(check.final_quantity)
                sl_price  = float(check.stop_loss)
                tp_price  = float(check.take_profit)
            else:
                # Fallback sizing: 1% risk
                risk_amt = portfolio_value * 0.01
                sl_dist  = abs(price - sl_price)
                quantity = risk_amt / (sl_dist + 1e-9)

            if quantity <= 0:
                raise ValueError("Calculated quantity is zero")

            # Use paper mode check from engine
            is_paper = False
            if self._engine:
                from core.trading_engine import EngineMode
                is_paper = self._engine.mode == EngineMode.PAPER

            trade = ActiveTrade(
                symbol=rec.symbol,
                side=rec.ensemble_signal,
                entry_price=price,
                quantity=quantity,
                stop_loss=sl_price,
                take_profit=tp_price,
                confidence=rec.ensemble_confidence,
                open_time=datetime.now(timezone.utc).isoformat(),
                paper=is_paper,
                expected_rr=rec.rr_ratio,
                source_scan_score=rec.combined_score,
            )

            # Log in journal
            if self._journal:
                from dataclasses import asdict as _asdict
                trade_id = self._journal.open_trade(
                    symbol=rec.symbol, side=rec.ensemble_signal,
                    entry_price=price, quantity=quantity,
                    stop_loss=sl_price, take_profit=tp_price,
                    paper=is_paper,
                    source_signals={"market_scanner": {
                        "signal": rec.ensemble_signal,
                        "confidence": rec.ensemble_confidence,
                    }},
                )
                trade.trade_id = trade_id

            # Execute via engine or paper
            if self._engine and not is_paper:
                self._engine.on_ml_signal({
                    "symbol": rec.symbol,
                    "action": rec.ensemble_signal,
                    "confidence": rec.ensemble_confidence,
                    "price": price,
                    "source": "market_scanner",
                    "_council": None,
                    "_sources": {},
                })
            elif self._engine and is_paper:
                if rec.ensemble_signal == "BUY":
                    self._engine.paper_buy(rec.symbol, price, quantity, rec.ensemble_confidence)
                else:
                    self._engine.paper_sell(rec.symbol, price)

            with self._lock:
                self._active_trade = trade
                self._pending_recommendation = None
                # Exclude this symbol from scanner while in position
                if self._scanner:
                    self._scanner.set_excluded({rec.symbol})

            self._intel.ml("AutoTrader",
                f"✅ Entered {rec.ensemble_signal} {rec.symbol} "
                f"qty={quantity:.6f} @ {price:.4f} | "
                f"SL={sl_price:.4f} TP={tp_price:.4f} | "
                f"{'PAPER' if is_paper else 'LIVE'}")

            self._set_state(CycleState.MONITORING)
            self._monitor_trade()

        except Exception as exc:
            self._intel.warning("AutoTrader",
                f"❌ Entry failed for {rec.symbol}: {exc}")
            self._set_state(CycleState.IDLE)

    def _monitor_trade(self) -> None:
        """Watch the open position tick by tick until SL/TP/timeout."""
        trade = self._active_trade
        if not trade:
            return

        deadline = time.time() + self.TIMEOUT_TRADE_SEC
        entry_time = time.time()

        while self._running and time.time() < deadline:
            if not self._active_trade:
                return   # Cleared externally (manual exit)

            price = self._get_live_price(trade.symbol)
            if not price:
                time.sleep(self.MONITOR_INTERVAL_SEC)
                continue

            # Check SL
            sl_hit = (trade.side == "BUY"  and price <= trade.stop_loss) or \
                     (trade.side == "SELL" and price >= trade.stop_loss)
            # Check TP
            tp_hit = (trade.side == "BUY"  and price >= trade.take_profit) or \
                     (trade.side == "SELL" and price <= trade.take_profit)

            if tp_hit:
                self._exit_trade("TP")
                return
            if sl_hit:
                self._exit_trade("SL")
                return

            time.sleep(self.MONITOR_INTERVAL_SEC)

        # Timeout
        self._exit_trade("TIMEOUT")

    def _exit_trade(self, reason: str) -> None:
        with self._lock:
            trade = self._active_trade
            if not trade:
                return
            self._active_trade = None

        self._set_state(CycleState.EXITING)
        exit_price = self._get_live_price(trade.symbol) or trade.entry_price

        # Close in engine
        if self._engine:
            from core.trading_engine import EngineMode
            if self._engine.mode == EngineMode.PAPER and trade.side == "BUY":
                self._engine.paper_sell(trade.symbol, exit_price)

        # Close in journal
        if self._journal and trade.trade_id:
            entry = self._journal.close_trade(trade.trade_id, exit_price, reason)

        # Compute P&L
        if trade.side == "BUY":
            pnl     = (exit_price - trade.entry_price) * trade.quantity
        else:
            pnl     = (trade.entry_price - exit_price) * trade.quantity
        pnl_pct = pnl / (trade.entry_price * trade.quantity + 1e-9) * 100

        result = CycleResult(
            cycle_num=self._cycle_num,
            symbol=trade.symbol,
            side=trade.side,
            entry_price=trade.entry_price,
            exit_price=exit_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            duration_sec=0.0,
            scan_to_entry_sec=0.0,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._cycle_results.append(result)

        emoji = "✅" if pnl >= 0 else "❌"
        self._intel.ml("AutoTrader",
            f"{emoji} CLOSED {trade.side} {trade.symbol} @ {exit_price:.4f} | "
            f"PnL: {pnl:+.4f} ({pnl_pct:+.1f}%) | {reason}")

        for cb in self._result_callbacks:
            try:
                cb(result)
            except Exception:
                pass

        # Update dynamic risk
        if self._drm:
            self._drm.record_outcome(pnl >= 0, pnl)

        # Cool-off after stop hit
        if reason == "SL":
            self._cooldown_until = time.time() + self.COOLDOWN_AFTER_LOSS_SEC
            self._intel.ml("AutoTrader",
                f"⏳ SL hit – cool-off for {self.COOLDOWN_AFTER_LOSS_SEC//60} minutes")

        # Clear scanner exclusion
        if self._scanner:
            self._scanner.set_excluded(set())

        self._set_state(CycleState.IDLE)

    # ── Helpers ────────────────────────────────────────────────────────

    def _get_live_price(self, symbol: str) -> Optional[float]:
        try:
            from db.redis_client import RedisClient
            t = RedisClient().get_ticker(symbol)
            if t:
                return float(t.get("price", 0))
        except Exception:
            pass
        try:
            if self._client:
                t = self._client.get_ticker(symbol)
                if t:
                    return float(t.get("price", 0) or t.get("lastPrice", 0))
        except Exception:
            pass
        return None

    def _get_portfolio_value(self) -> float:
        try:
            if self._engine and self._engine._portfolio:
                snap = self._engine._portfolio.get_snapshot()
                return float(snap.get("total_usdt", 10_000) if isinstance(snap, dict) else snap.total_usdt)
        except Exception:
            pass
        return 10_000.0

    def _set_state(self, state: CycleState) -> None:
        self._state = state
        for cb in self._state_callbacks:
            try:
                cb(state)
            except Exception:
                pass
