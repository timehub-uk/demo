"""
Main trading engine – orchestrates auto / manual trading,
integrates ML signals, risk management, and order execution.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from enum import Enum
from typing import Callable, Optional

from loguru import logger

from config import get_settings
from .binance_client import BinanceClient
from .order_manager import OrderManager
from .portfolio import PortfolioManager
from .risk_manager import RiskManager, RiskMetrics, TradeProposal
from db.redis_client import RedisClient


class EngineMode(str, Enum):
    MANUAL = "manual"
    AUTO = "auto"
    HYBRID = "hybrid"
    PAUSED = "paused"
    PAPER = "paper"     # Simulated trading – no real orders sent


class TradingEngine:
    """
    Central trading orchestrator.

    Responsibilities:
    - Subscribe to real-time market data
    - Receive ML signals and evaluate them through risk manager
    - Execute approved orders via OrderManager
    - Maintain engine state (mode, heartbeat, metrics)
    - Emit events to UI via callbacks
    """

    def __init__(
        self,
        binance_client: BinanceClient,
        order_manager: OrderManager,
        portfolio_manager: PortfolioManager,
        risk_manager: RiskManager,
        user_id: str,
    ) -> None:
        self._client = binance_client
        self._orders = order_manager
        self._portfolio = portfolio_manager
        self._risk = risk_manager
        self._redis = RedisClient()
        self._settings = get_settings()
        self._user_id = user_id

        self._mode = EngineMode(self._settings.trading.mode)
        self._running = False
        self._heartbeat_thread: threading.Thread | None = None
        self._sync_thread: threading.Thread | None = None
        self._active_symbols: set[str] = set()
        self._callbacks: dict[str, list[Callable]] = {
            "trade": [], "signal": [], "mode_change": [],
            "error": [], "heartbeat": [], "whale": [], "token_signal": [],
        }
        self._metrics: dict = {
            "trades_today": 0, "wins_today": 0, "losses_today": 0,
            "pnl_today": 0.0, "signals_processed": 0, "orders_rejected": 0,
        }

        # Paper trading state
        self._paper_capital: float = 10_000.0
        self._paper_positions: dict[str, dict] = {}   # symbol → {qty, entry_price, side}
        self._paper_trades: list[dict] = []

        # Pluggable signal sources
        self._whale_watcher = None       # Set via set_whale_watcher()
        self._token_ml_manager = None    # Set via set_token_ml_manager()
        self._sentiment_analyser = None  # Set via set_sentiment_analyser()

        # Advanced intelligence layer
        self._regime_detector = None     # Set via set_regime_detector()
        self._ensemble = None            # Set via set_ensemble()
        self._signal_council = None      # Set via set_signal_council()
        self._mtf_filter = None          # Set via set_mtf_filter()
        self._dynamic_risk = None        # Set via set_dynamic_risk()
        self._trade_journal = None       # Set via set_trade_journal()

        # Candle cache per symbol for ATR computation (last 30 candles)
        self._candle_cache: dict[str, list[dict]] = {}
        self._open_trade_ids: dict[str, str] = {}   # symbol → journal trade_id

    # ── Lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="engine-heartbeat"
        )
        self._heartbeat_thread.start()
        self._sync_thread = threading.Thread(
            target=self._sync_loop, daemon=True, name="engine-sync"
        )
        self._sync_thread.start()
        logger.info(f"TradingEngine started – mode: {self._mode}")

    def stop(self) -> None:
        self._running = False
        logger.info("TradingEngine stopped.")

    # ── Mode management ────────────────────────────────────────────────
    @property
    def mode(self) -> EngineMode:
        return self._mode

    def set_mode(self, mode: EngineMode) -> None:
        old = self._mode
        self._mode = mode
        logger.info(f"Engine mode changed: {old} → {mode}")
        self._emit("mode_change", {"old": old, "new": mode})

    def pause(self) -> None:
        self.set_mode(EngineMode.PAUSED)

    def resume(self) -> None:
        self.set_mode(EngineMode(self._settings.trading.mode))

    # ── Symbol management ──────────────────────────────────────────────
    def add_symbol(self, symbol: str) -> None:
        if symbol in self._active_symbols:
            return
        self._active_symbols.add(symbol)
        self._client.subscribe_kline(symbol, "1m", self._on_kline)
        self._client.subscribe_depth(symbol, self._on_depth)
        self._client.subscribe_ticker(symbol, self._on_ticker)
        logger.debug(f"Subscribed to {symbol}")

    def remove_symbol(self, symbol: str) -> None:
        self._active_symbols.discard(symbol)

    # ── Pluggable service injection ────────────────────────────────────
    def set_whale_watcher(self, watcher) -> None:
        self._whale_watcher = watcher
        watcher.on_event(self._on_whale_event)

    def set_token_ml_manager(self, manager) -> None:
        self._token_ml_manager = manager
        manager.on_signal(self._on_token_signal)

    def set_sentiment_analyser(self, analyser) -> None:
        self._sentiment_analyser = analyser

    def set_regime_detector(self, detector) -> None:
        self._regime_detector = detector
        detector.on_regime_change(self._on_regime_change)

    def set_ensemble(self, ensemble) -> None:
        self._ensemble = ensemble
        ensemble.on_signal(self._on_ensemble_signal)

    def set_signal_council(self, council) -> None:
        self._signal_council = council

    def set_mtf_filter(self, mtf) -> None:
        self._mtf_filter = mtf

    def set_dynamic_risk(self, drm) -> None:
        self._dynamic_risk = drm

    def set_trade_journal(self, journal) -> None:
        self._trade_journal = journal

    # ── Paper trading ──────────────────────────────────────────────────
    def enable_paper_trading(self, initial_capital: float = 10_000.0) -> None:
        self._paper_capital = initial_capital
        self._paper_positions.clear()
        self._paper_trades.clear()
        self.set_mode(EngineMode.PAPER)
        logger.info(f"Paper trading enabled – virtual capital: ${initial_capital:,.2f}")

    def paper_buy(self, symbol: str, price: float, qty: float, confidence: float) -> dict:
        cost = price * qty
        if cost > self._paper_capital:
            qty = self._paper_capital * 0.95 / price
            cost = price * qty
        self._paper_capital -= cost * 1.001  # fee simulation
        self._paper_positions[symbol] = {"qty": qty, "entry_price": price, "side": "BUY"}
        trade = {"symbol": symbol, "side": "BUY", "price": price, "qty": qty,
                 "time": time.time(), "paper": True, "confidence": confidence}
        self._paper_trades.append(trade)
        logger.info(f"[PAPER] BUY {symbol} {qty:.6f} @ {price:.4f} | capital: ${self._paper_capital:,.2f}")
        self._emit("trade", trade)
        return trade

    def paper_sell(self, symbol: str, price: float) -> dict:
        pos = self._paper_positions.pop(symbol, None)
        if not pos:
            return {}
        qty = pos["qty"]
        proceeds = price * qty * 0.999  # fee simulation
        pnl = proceeds - pos["entry_price"] * qty
        self._paper_capital += proceeds
        trade = {"symbol": symbol, "side": "SELL", "price": price, "qty": qty,
                 "pnl": pnl, "time": time.time(), "paper": True}
        self._paper_trades.append(trade)
        self._metrics["pnl_today"] += pnl
        logger.info(f"[PAPER] SELL {symbol} @ {price:.4f} | PnL: {pnl:+.4f} | capital: ${self._paper_capital:,.2f}")
        self._emit("trade", trade)
        return trade

    @property
    def paper_capital(self) -> float:
        return self._paper_capital

    @property
    def paper_positions(self) -> dict:
        return dict(self._paper_positions)

    @property
    def paper_trades(self) -> list:
        return list(self._paper_trades)

    # ── Whale + token signal handlers ─────────────────────────────────
    def _on_whale_event(self, event) -> None:
        """Receive whale event and optionally act on it."""
        self._emit("whale", event)
        if self._mode not in (EngineMode.AUTO, EngineMode.PAPER):
            return
        try:
            signal = None
            if hasattr(self._whale_watcher, "get_whale_signal") and event.whale_id:
                sig = self._whale_watcher.get_whale_signal(
                    event.symbol, event.event_type, event.whale_id
                )
                if sig.get("signal") in ("BUY", "SELL") and sig.get("confidence", 0) >= 0.6:
                    signal = sig
            if signal:
                logger.info(f"Whale signal: {signal} for {event.symbol}")
                self.on_ml_signal({
                    "symbol": event.symbol,
                    "action": signal["signal"],
                    "confidence": signal["confidence"],
                    "source": "whale",
                })
        except Exception as exc:
            logger.debug(f"Whale signal processing error: {exc}")

    def _on_token_signal(self, signal: dict) -> None:
        """Receive per-token model signal."""
        self._emit("token_signal", signal)
        if self._mode not in (EngineMode.AUTO, EngineMode.PAPER):
            return
        if signal.get("confidence", 0) >= 0.65 and signal.get("signal") in ("BUY", "SELL"):
            self.on_ml_signal({
                "symbol": signal.get("symbol", ""),
                "action": signal["signal"],
                "confidence": signal["confidence"],
                "source": "token_model",
            })

    # ── Advanced intelligence pipeline ────────────────────────────────
    def _on_regime_change(self, snapshot) -> None:
        regime = snapshot.regime.value
        self._intel_log(f"Regime changed → {regime} (conf {snapshot.confidence:.0%})")
        self._emit("signal", {"type": "regime_change", "regime": regime,
                               "confidence": snapshot.confidence})

    def _on_ensemble_signal(self, ens_signal) -> None:
        """Called by EnsembleAggregator when consensus is reached."""
        if ens_signal.final_signal == "HOLD":
            return
        # Feed into the main signal pipeline as a first-class signal
        self.on_ml_signal({
            "symbol":     ens_signal.symbol,
            "action":     ens_signal.final_signal,
            "confidence": ens_signal.final_confidence,
            "price":      self._get_last_price(ens_signal.symbol),
            "source":     "ensemble",
        })

    def _feed_ensemble(self, source: str, symbol: str, signal: str, confidence: float) -> None:
        """Route a raw signal from any source through the ensemble aggregator."""
        if self._ensemble:
            self._ensemble.feed(source, {
                "symbol": symbol, "signal": signal, "confidence": confidence
            })

    def _get_last_price(self, symbol: str) -> float:
        try:
            from db.redis_client import RedisClient
            t = RedisClient().get_ticker(symbol)
            return float(t.get("price", 0)) if t else 0.0
        except Exception:
            return 0.0

    def _intel_log(self, msg: str) -> None:
        logger.info(f"[TradingEngine] {msg}")

    # ── ML Signal handling ─────────────────────────────────────────────
    def on_ml_signal(self, signal: dict) -> None:
        """
        Main signal ingestion point.
        Runs the full intelligence pipeline:
          1. Regime gate (RegimeDetector)
          2. Multi-timeframe confluence (MTFConfluenceFilter)
          3. Signal Council deliberation (SignalCouncil)
          4. Dynamic risk sizing (DynamicRiskManager)
          5. Trade execution / paper trade
        """
        self._metrics["signals_processed"] += 1
        self._emit("signal", signal)

        if self._mode == EngineMode.PAPER:
            # Route through full pipeline for realism
            symbol = signal.get("symbol", "")
            side   = signal.get("action", "")
            price  = float(signal.get("price", 0))
            conf   = signal.get("confidence", 0.0)

            # Still gate through regime + MTF even in paper mode
            side, conf = self._run_intelligence_pipeline(symbol, side, conf, signal)

            if side == "BUY" and symbol not in self._paper_positions and price > 0:
                qty = self._paper_capital * 0.95 / price
                self.paper_buy(symbol, price, qty, conf)
            elif side == "SELL" and symbol in self._paper_positions and price > 0:
                self.paper_sell(symbol, price)
            return

        if self._mode not in (EngineMode.AUTO, EngineMode.HYBRID):
            return

        symbol = signal.get("symbol", "")
        side = signal.get("action", "")
        confidence = signal.get("confidence", 0.0)

        # ── Intelligence pipeline ──────────────────────────────────────
        side, confidence = self._run_intelligence_pipeline(symbol, side, confidence, signal)
        if side == "HOLD":
            return

        price = Decimal(str(signal.get("price", 0)))

        if side not in ("BUY", "SELL") or price <= 0:
            return

        portfolio = self._portfolio.get_snapshot()
        portfolio_value_f = portfolio.get("total_usdt", 0) if isinstance(portfolio, dict) else float(portfolio.total_usdt)
        portfolio_value = Decimal(str(portfolio_value_f))
        price_f = float(price)

        # ── Dynamic risk evaluation ────────────────────────────────────
        candles_df = self._get_candles_df(symbol)
        council_decision = signal.get("_council")   # Attached by _run_intelligence_pipeline
        if self._dynamic_risk:
            # Update portfolio peak/drawdown
            self._dynamic_risk.update_portfolio(portfolio_value_f)
            check = self._dynamic_risk.evaluate_trade(
                symbol=symbol, side=side,
                entry_price=price, confidence=confidence,
                portfolio_value=portfolio_value_f,
                candles_df=candles_df,
                council_decision=council_decision,
            )
            if not check.approved:
                self._metrics["orders_rejected"] += 1
                logger.debug(f"DynamicRisk rejected [{symbol}]: {check.reject_reason}")
                return
            qty       = check.final_quantity
            stop_loss = check.stop_loss
            take_profit = check.take_profit
            size_mult = check.size_mult
        else:
            # Fallback to base risk manager
            stop_loss   = self._risk.calculate_stop_loss(price, side)
            take_profit = self._risk.calculate_take_profit(price, side)
            qty         = self._risk.calculate_position_size(portfolio_value, price, stop_loss)
            size_mult   = 1.0

            proposal = TradeProposal(
                symbol=symbol, side=side, entry_price=price,
                quantity=qty, stop_loss=stop_loss, take_profit=take_profit,
                confidence=confidence,
            )
            metrics = RiskMetrics(
                portfolio_value=portfolio_value,
                open_trades=len(self._orders.get_open_orders()),
            )
            proposal = self._risk.evaluate(proposal, metrics)
            if not proposal.approved:
                self._metrics["orders_rejected"] += 1
                logger.debug(f"Signal rejected [{symbol}]: {proposal.reject_reason}")
                return
            qty = proposal.quantity
            stop_loss = proposal.stop_loss
            take_profit = proposal.take_profit

        order = self._orders.place_limit_order(
            symbol=symbol,
            side=side,
            quantity=qty,
            price=price,
            user_id=self._user_id,
            stop_price=stop_loss,
            is_automated=True,
            ml_signal=side,
            ml_confidence=confidence,
        )
        if order:
            self._metrics["trades_today"] += 1
            self._emit("trade", order)

            # Log to trade journal
            if self._trade_journal:
                regime = ""
                if self._regime_detector:
                    snap = self._regime_detector.current
                    regime = snap.regime.value
                mtf_score = getattr(signal.get("_mtf"), "confluence_pct", 0.0)
                trade_id = self._trade_journal.open_trade(
                    symbol=symbol, side=side,
                    entry_price=price_f, quantity=float(qty),
                    stop_loss=float(stop_loss), take_profit=float(take_profit),
                    regime=regime, mtf_score=mtf_score,
                    council_decision=council_decision,
                    source_signals=signal.get("_sources", {}),
                    size_mult=size_mult,
                )
                self._open_trade_ids[symbol] = trade_id

    # ── Intelligence pipeline ──────────────────────────────────────────
    def _run_intelligence_pipeline(
        self, symbol: str, side: str, confidence: float, signal: dict
    ) -> tuple[str, float]:
        """
        Run signal through regime → MTF → council deliberation.
        Returns (final_side, final_confidence). Side may become "HOLD" if rejected.
        """
        if side not in ("BUY", "SELL"):
            return "HOLD", 0.0

        # ── 1. Regime gate ─────────────────────────────────────────────
        if self._regime_detector:
            ok, reason = self._regime_detector.filter_signal(side, confidence)
            if not ok:
                logger.debug(f"[{symbol}] Regime blocked: {reason}")
                return "HOLD", 0.0
            # Scale confidence by regime confidence
            confidence *= self._regime_detector.current.confidence or 0.8

        # ── 2. MTF confluence gate ─────────────────────────────────────
        mtf_result = None
        if self._mtf_filter:
            mtf_result = self._mtf_filter.check(symbol, side, confidence)
            signal["_mtf"] = mtf_result
            if not mtf_result.passes_filter:
                logger.debug(f"[{symbol}] MTF blocked: {mtf_result.reject_reason}")
                return "HOLD", 0.0
            # Blend confidence with MTF score
            confidence = min(0.95, (confidence + mtf_result.confidence) / 2)

        # ── 3. Signal council deliberation ────────────────────────────
        council = None
        if self._signal_council:
            # Gather all source signals available for this symbol
            sources = {signal.get("source", "lstm_predictor"): {
                "signal": side, "confidence": confidence
            }}
            if self._whale_watcher:
                try:
                    profiles = self._whale_watcher.get_profiles()
                    for p in (profiles or []):
                        if getattr(p, "symbol", "") == symbol:
                            bias = getattr(p, "signal_bias", "HOLD")
                            bias_conf = getattr(p, "bias_confidence", 0.5)
                            if bias in ("BUY", "SELL"):
                                sources["whale_signal"] = {"signal": bias, "confidence": bias_conf}
                except Exception:
                    pass
            if self._sentiment_analyser:
                try:
                    sent = self._sentiment_analyser.get(symbol)
                    if sent and abs(sent.score) > 0.2:
                        sources["sentiment"] = {
                            "signal": "BUY" if sent.score > 0 else "SELL",
                            "confidence": min(0.75, abs(sent.score)),
                        }
                except Exception:
                    pass

            regime_str = ""
            if self._regime_detector:
                snap = self._regime_detector.current
                regime_str = snap.regime.value if hasattr(snap.regime, "value") else str(snap.regime)

            council = self._signal_council.deliberate(sources, symbol=symbol, regime=regime_str)
            signal["_council"] = council
            signal["_sources"] = sources

            if council.final_signal == "HOLD":
                logger.debug(f"[{symbol}] Council returned HOLD (disagreement={council.disagreement_score:.2f})")
                return "HOLD", 0.0
            if council.vetoed_by:
                logger.debug(f"[{symbol}] Council vetoed by: {council.vetoed_by}")
                return "HOLD", 0.0
            side       = council.final_signal
            confidence = council.final_confidence

        # ── 4. Feed into ensemble (non-blocking, for weight adaptation) ─
        if self._ensemble:
            self._ensemble.feed(
                signal.get("source", "lstm_predictor"),
                {"symbol": symbol, "signal": side, "confidence": confidence}
            )

        return side, confidence

    def _get_candles_df(self, symbol: str):
        """Return a small DataFrame of recent candles for ATR computation."""
        try:
            cache = self._candle_cache.get(symbol, [])
            if len(cache) >= 20:
                import pandas as pd
                return pd.DataFrame(cache[-50:])
            from db.redis_client import RedisClient
            candles = RedisClient().get_candles(symbol, "1h")
            if candles:
                import pandas as pd
                return pd.DataFrame(candles[-50:])
        except Exception:
            pass
        return None

    # ── Manual trading ─────────────────────────────────────────────────
    def manual_buy(self, symbol: str, quantity: Decimal, price: Decimal) -> Optional[dict]:
        return self._orders.place_limit_order(
            symbol=symbol, side="BUY", quantity=quantity, price=price,
            user_id=self._user_id, is_automated=False,
        )

    def manual_sell(self, symbol: str, quantity: Decimal, price: Decimal) -> Optional[dict]:
        return self._orders.place_limit_order(
            symbol=symbol, side="SELL", quantity=quantity, price=price,
            user_id=self._user_id, is_automated=False,
        )

    def manual_cancel(self, symbol: str, order_id: str) -> bool:
        return self._orders.cancel_order(symbol, order_id)

    # ── WebSocket handlers ─────────────────────────────────────────────
    def _on_kline(self, data: dict) -> None:
        k = data.get("k", {})
        symbol = k.get("s", "")
        if symbol:
            candle_row = {
                "open": float(k.get("o", 0)), "high": float(k.get("h", 0)),
                "low": float(k.get("l", 0)), "close": float(k.get("c", 0)),
                "volume": float(k.get("v", 0)),
            }
            cache = self._candle_cache.setdefault(symbol, [])
            cache.append(candle_row)
            if len(cache) > 200:
                self._candle_cache[symbol] = cache[-200:]

        if k.get("x"):   # candle closed
            self._emit("signal", {
                "type": "candle_close",
                "symbol": symbol,
                "data": k,
            })

    def _on_depth(self, data: dict) -> None:
        symbol = data.get("s", "")
        if symbol:
            self._redis.cache_orderbook(symbol, data)

    def _on_ticker(self, data: dict) -> None:
        symbol = data.get("s", "")
        if symbol:
            self._redis.cache_ticker(symbol, {
                "price": data.get("c", 0),
                "change_pct": data.get("P", 0),
                "volume": data.get("v", 0),
            })

    # ── Background loops ───────────────────────────────────────────────
    def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                self._portfolio.refresh()
                self._emit("heartbeat", {
                    "mode": self._mode,
                    "metrics": self._metrics,
                    "active_symbols": list(self._active_symbols),
                })
            except Exception as exc:
                logger.error(f"Heartbeat error: {exc}")
            time.sleep(10)

    def _sync_loop(self) -> None:
        while self._running:
            try:
                self._orders.sync_orders()
            except Exception as exc:
                logger.error(f"Sync error: {exc}")
            time.sleep(30)

    # ── Event emission ─────────────────────────────────────────────────
    def on(self, event: str, callback: Callable) -> None:
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _emit(self, event: str, data) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception as exc:
                logger.error(f"Callback error [{event}]: {exc}")

    @property
    def metrics(self) -> dict:
        return self._metrics.copy()
