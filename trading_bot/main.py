#!/usr/bin/env python3
"""
BinanceML Pro – Main Application Entry Point
=============================================
Professional AI-powered Binance trading platform for Mac Mini M4.

Startup sequence:
  1. Logger initialisation
  2. Encryption + settings load
  3. First-run setup wizard (if needed)
  4. Database initialisation (PostgreSQL + Redis)
  5. Core service setup (Binance client, trading engine, ML predictor)
  6. ML data integrity pre-check
  7. Background services start (trading engine, continuous learner, API server)
  8. PyQt6 UI launch
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

# ── Ensure the project root is on sys.path ──────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Logging (before imports that use logger) ────────────────────────────────
from utils.logger import setup_logger, get_intel_logger
setup_logger("INFO")
intel = get_intel_logger()

from loguru import logger

# ── Qt (check before anything else) ─────────────────────────────────────────
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox, QSplashScreen
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QPixmap, QFont, QColor
except ImportError as e:
    print(f"PyQt6 not available: {e}")
    print("Install with: pip install PyQt6 PyQt6-Qt6")
    sys.exit(1)


def create_splash(app: QApplication) -> QSplashScreen:
    """Simple splash screen while services start."""
    pixmap = QPixmap(600, 300)
    pixmap.fill(QColor("#0A0A12"))
    splash = QSplashScreen(pixmap, Qt.WindowType.WindowStaysOnTopHint)
    splash.showMessage(
        "BinanceML Pro  ·  Starting…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#00D4FF"),
    )
    splash.show()
    app.processEvents()
    return splash


def init_databases() -> tuple[bool, str]:
    """Initialise PostgreSQL and Redis connections."""
    from config import get_settings
    settings = get_settings()
    try:
        from db.postgres import init_db
        init_db(
            settings.db_url,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
        )
        intel.system("Startup", "PostgreSQL connected.")
    except Exception as exc:
        logger.warning(f"PostgreSQL unavailable ({exc}) – running in offline mode")
        intel.warning("Startup", f"PostgreSQL unavailable: {exc} – offline mode")

    try:
        from db.redis_client import init_redis
        init_redis(
            host=settings.redis.host,
            port=settings.redis.port,
            db=settings.redis.db,
            password=settings.redis.password,
            max_connections=settings.redis.max_connections,
        )
        intel.system("Startup", "Redis connected.")
    except Exception as exc:
        logger.warning(f"Redis unavailable ({exc}) – caching disabled")
        intel.warning("Startup", f"Redis unavailable: {exc} – caching disabled")

    return True, ""


def build_services(settings):
    """Instantiate and wire all application services."""
    from config import get_settings
    from core.binance_client import BinanceClient
    from core.trading_engine import TradingEngine
    from core.order_manager import OrderManager
    from core.portfolio import PortfolioManager
    from core.risk_manager import RiskManager
    from ml.trainer import MLTrainer
    from ml.predictor import MLPredictor
    from ml.continuous_learner import ContinuousLearner
    from tax.uk_tax import UKTaxCalculator

    intel.system("Startup", "Initialising Binance client…")
    binance = BinanceClient()

    intel.system("Startup", "Setting up trading engine…")
    risk  = RiskManager()
    portfolio = PortfolioManager(binance_client=binance)
    user_id = "default"   # Will be replaced once DB has user record
    orders = OrderManager(binance_client=binance, portfolio_manager=portfolio)
    engine = TradingEngine(
        binance_client=binance,
        order_manager=orders,
        portfolio_manager=portfolio,
        risk_manager=risk,
        user_id=user_id,
    )

    intel.system("Startup", "Initialising ML predictor…")
    trainer   = MLTrainer(binance_client=binance)
    predictor = MLPredictor()

    intel.system("Startup", "Initialising continuous learner…")
    cl = ContinuousLearner(
        trainer=trainer,
        predictor=predictor,
        binance_client=binance,
    )

    intel.system("Startup", "Initialising tax calculator…")
    tax_calc = UKTaxCalculator()

    intel.system("Startup", "Initialising whale watcher…")
    from ml.whale_watcher import WhaleWatcher
    whale_watcher = WhaleWatcher(binance_client=binance)

    intel.system("Startup", "Initialising per-token ML manager…")
    from ml.token_ml_task import TokenMLManager
    token_ml = TokenMLManager(binance_client=binance, max_workers=4)

    intel.system("Startup", "Initialising sentiment analyser…")
    from ml.sentiment import SentimentAnalyser
    sentiment = SentimentAnalyser()

    intel.system("Startup", "Initialising portfolio optimiser…")
    from core.portfolio_optimiser import PortfolioOptimiser
    port_opt = PortfolioOptimiser()

    intel.system("Startup", "Initialising backtester…")
    from ml.backtester import Backtester
    backtester = Backtester(predictor=predictor)

    intel.system("Startup", "Initialising voice alerts…")
    from core.voice_alerts import VoiceAlerts
    voice = VoiceAlerts()

    intel.system("Startup", "Initialising Telegram bot…")
    from core.telegram_bot import TelegramBot
    telegram = TelegramBot(engine=engine, portfolio=portfolio)

    intel.system("Startup", "Initialising Discord notifier…")
    from alerts.discord_notifier import get_discord_notifier
    discord = get_discord_notifier()

    intel.system("Startup", "Initialising Slack notifier…")
    from alerts.slack_notifier import get_slack_notifier
    slack = get_slack_notifier()

    intel.system("Startup", "Initialising Email notifier…")
    from alerts.email_notifier import get_email_notifier
    email_notifier = get_email_notifier()

    intel.system("Startup", "Initialising new token launch watcher…")
    from ml.new_token_watcher import NewTokenWatcher
    new_token_watcher = NewTokenWatcher(binance_client=binance)

    # ── Advanced intelligence layer ───────────────────────────────────
    intel.system("Startup", "Initialising market regime detector…")
    from ml.regime_detector import RegimeDetector
    regime_detector = RegimeDetector()

    intel.system("Startup", "Initialising MTF confluence filter…")
    from ml.mtf_confluence import MTFConfluenceFilter
    mtf_filter = MTFConfluenceFilter(predictor=predictor, token_ml_manager=token_ml)

    intel.system("Startup", "Initialising signal council…")
    from ml.signal_council import SignalCouncil
    signal_council = SignalCouncil()

    intel.system("Startup", "Initialising ensemble aggregator…")
    from ml.ensemble import EnsembleAggregator
    ensemble = EnsembleAggregator(
        regime_detector=regime_detector,
        mtf_filter=mtf_filter,
        sentiment_analyser=sentiment,
    )

    intel.system("Startup", "Initialising dynamic risk manager…")
    from core.dynamic_risk import DynamicRiskManager
    dynamic_risk = DynamicRiskManager(base_risk_manager=risk,
                                       regime_detector=regime_detector)

    intel.system("Startup", "Initialising Monte Carlo simulator…")
    from ml.monte_carlo import MonteCarloSimulator
    monte_carlo = MonteCarloSimulator()

    intel.system("Startup", "Initialising walk-forward validator…")
    from ml.walk_forward import WalkForwardValidator
    walk_forward = WalkForwardValidator(predictor=predictor, token_ml_manager=token_ml)

    intel.system("Startup", "Initialising trade journal…")
    from core.trade_journal import TradeJournal
    trade_journal = TradeJournal(ensemble=ensemble, dynamic_risk=dynamic_risk)

    intel.system("Startup", "Initialising market pulse monitor…")
    from ml.market_pulse import MarketPulse
    from db.redis_client import RedisClient
    market_pulse = MarketPulse(
        redis_client=RedisClient(),
        binance_client=binance,
    )

    intel.system("Startup", "Initialising forecast tracker…")
    from ml.forecast_tracker import ForecastTracker
    forecast_tracker = ForecastTracker()

    intel.system("Startup", "Initialising archive downloader…")
    from ml.archive_downloader import BinanceArchiveDownloader
    archive_downloader = BinanceArchiveDownloader()

    intel.system("Startup", "Initialising data collector…")
    from ml.data_collector import DataCollector
    data_collector = DataCollector(binance_client=binance)

    intel.system("Startup", "Initialising market scanner…")
    from ml.market_scanner import MarketScanner
    market_scanner = MarketScanner(
        binance_client=binance,
        regime_detector=regime_detector,
        mtf_filter=mtf_filter,
        signal_council=signal_council,
        ensemble=ensemble,
        token_ml=token_ml,
        dynamic_risk=dynamic_risk,
        predictor=predictor,
    )

    intel.system("Startup", "Initialising strategy manager…")
    from core.strategy_manager import StrategyManager
    strategy_manager = StrategyManager(
        regime_detector=regime_detector,
        ensemble=ensemble,
        trade_journal=trade_journal,
    )

    intel.system("Startup", "Initialising ping-pong range trader…")
    from core.ping_pong_trader import PingPongTrader
    ping_pong = PingPongTrader(
        engine=engine,
        regime_detector=regime_detector,
        dynamic_risk=dynamic_risk,
        trade_journal=trade_journal,
        binance_client=binance,
    )

    intel.system("Startup", "Initialising arbitrage detector…")
    from core.arbitrage_detector import ArbitrageDetector
    arb_detector = ArbitrageDetector(
        binance_client=binance,
        trade_journal=trade_journal,
    )

    intel.system("Startup", "Initialising arbitrage auto-trader…")
    from core.arbitrage_auto_trader import ArbitrageAutoTrader
    arb_trader = ArbitrageAutoTrader(
        detector=arb_detector,
        engine=engine,
        trade_journal=trade_journal,
        budget_usdt=100.0,
        paper=True,    # paper mode by default; user can toggle in UI
    )

    intel.system("Startup", "Initialising multi-timeframe trend scanner…")
    from ml.trend_scanner import TrendScanner
    trend_scanner = TrendScanner(binance_client=binance)

    intel.system("Startup", "Initialising pair discovery scanner…")
    from ml.pair_scanner import PairScanner
    pair_scanner = PairScanner(binance_client=binance)

    intel.system("Startup", "Initialising pair ML cross-reference analyzer…")
    from ml.pair_ml_analyzer import PairMLAnalyzer
    pair_ml_analyzer = PairMLAnalyzer(
        pair_scanner=pair_scanner,
        trend_scanner=trend_scanner,
        predictor=predictor,
        whale_watcher=whale_watcher,
        sentiment=sentiment,
        regime_detector=regime_detector,
        arb_detector=arb_detector,
    )

    intel.system("Startup", "Initialising MetaMask wallet bridge (optional)…")
    from core.metamask_wallet import MetaMaskWallet
    metamask_wallet = MetaMaskWallet(
        binance_client=binance,
        address=getattr(settings, "metamask_address", ""),
        network=getattr(settings, "metamask_network", "bsc"),
        auto_transfer=getattr(settings, "metamask_auto_transfer", False),
        threshold_usdt=getattr(settings, "metamask_threshold_usdt", 100.0),
    )

    intel.system("Startup", "Initialising accumulation detector…")
    from ml.accumulation_detector import AccumulationDetector
    accumulation_detector = AccumulationDetector(
        binance_client=binance,
        pair_scanner=pair_scanner,
    )

    intel.system("Startup", "Initialising liquidity depth analyzer…")
    from ml.liquidity_depth_analyzer import LiquidityDepthAnalyzer
    liquidity_analyzer = LiquidityDepthAnalyzer(
        binance_client=binance,
        pair_scanner=pair_scanner,
    )

    intel.system("Startup", "Initialising volume breakout detector…")
    from ml.volume_breakout_detector import VolumeBreakoutDetector
    breakout_detector = VolumeBreakoutDetector(
        binance_client=binance,
        pair_scanner=pair_scanner,
    )

    intel.system("Startup", "Initialising gap detector (gap up/down ML scanner)…")
    from ml.gap_detector import GapDetector
    gap_detector = GapDetector(
        binance_client=binance,
        pair_scanner=pair_scanner,
    )

    intel.system("Startup", "Initialising large candle watcher (rapid expansion alerts)…")
    from ml.large_candle_watcher import LargeCandleWatcher
    large_candle_watcher = LargeCandleWatcher(
        binance_client=binance,
        pair_scanner=pair_scanner,
    )

    intel.system("Startup", "Initialising ML central command (unified signal pipeline)…")
    from ml.ml_central_command import MLCentralCommand
    ml_central = MLCentralCommand()

    intel.system("Startup", "Initialising auto-trader…")
    from core.auto_trader import AutoTrader
    auto_trader = AutoTrader(
        engine=engine,
        scanner=market_scanner,
        dynamic_risk=dynamic_risk,
        trade_journal=trade_journal,
        binance_client=binance,
    )

    intel.system("Startup", "Initialising safety analysis suite…")
    from safety.contract_analyzer import ContractAnalyzer
    from safety.honeypot_detector import HoneypotDetector
    from safety.liquidity_lock_analyzer import LiquidityLockAnalyzer
    from safety.wallet_graph_analyzer import WalletGraphAnalyzer
    from safety.rugpull_scorer import RugPullScorer
    contract_analyzer = ContractAnalyzer()
    honeypot_detector = HoneypotDetector()
    liq_lock_analyzer = LiquidityLockAnalyzer()
    wallet_graph_analyzer = WalletGraphAnalyzer()
    rugpull_scorer = RugPullScorer(
        contract_analyzer=contract_analyzer,
        honeypot_detector=honeypot_detector,
        liquidity_analyzer=liq_lock_analyzer,
        wallet_analyzer=wallet_graph_analyzer,
    )

    intel.system("Startup", "Initialising token launch signal engine…")
    from ml.token_launch_signal import TokenLaunchSignalEngine
    launch_signal = TokenLaunchSignalEngine(
        contract_analyzer=contract_analyzer,
        honeypot_detector=honeypot_detector,
        liquidity_analyzer=liq_lock_analyzer,
        rugpull_scorer=rugpull_scorer,
    )

    intel.system("Startup", "Initialising live simulation twin…")
    from ml.live_simulation_twin import LiveSimulationTwin
    sim_twin = LiveSimulationTwin()

    intel.system("Startup", "Initialising strategy mutation lab…")
    from ml.strategy_mutation_lab import StrategyMutationLab, ParameterSpace
    from core.strategy_registry import StrategyRegistry
    _param_space = ParameterSpace({
        "rsi_period":    {"type": "int",   "min": 5,   "max": 30,  "default": 14},
        "ema_fast":      {"type": "int",   "min": 5,   "max": 50,  "default": 12},
        "ema_slow":      {"type": "int",   "min": 20,  "max": 200, "default": 26},
        "atr_multiplier":{"type": "float", "min": 0.5, "max": 4.0, "default": 2.0},
        "threshold":     {"type": "float", "min": 0.1, "max": 2.0, "default": 0.5},
        "use_volume":    {"type": "bool",                           "default": True},
    })
    mutation_lab = StrategyMutationLab(
        parameter_space=_param_space,
        registry=StrategyRegistry(),
    )

    # Wire whale watcher + token ML into trading engine
    engine.set_whale_watcher(whale_watcher)
    engine.set_token_ml_manager(token_ml)
    engine.set_sentiment_analyser(sentiment)

    # Wire advanced intelligence into trading engine
    engine.set_regime_detector(regime_detector)
    engine.set_ensemble(ensemble)
    engine.set_signal_council(signal_council)
    engine.set_mtf_filter(mtf_filter)
    engine.set_dynamic_risk(dynamic_risk)
    engine.set_trade_journal(trade_journal)

    # Feed LSTM predictor signals through ensemble
    predictor.on_signal(lambda s: ensemble.feed("lstm_predictor", {
        "symbol": s.get("symbol", ""),
        "signal": s.get("action", "HOLD"),
        "confidence": s.get("confidence", 0.5),
    }))

    return {
        "binance": binance,
        "engine": engine,
        "orders": orders,
        "portfolio": portfolio,
        "risk": risk,
        "trainer": trainer,
        "predictor": predictor,
        "continuous_learner": cl,
        "tax_calc": tax_calc,
        "whale_watcher": whale_watcher,
        "token_ml": token_ml,
        "sentiment": sentiment,
        "port_opt": port_opt,
        "backtester": backtester,
        "voice": voice,
        "telegram": telegram,
        "new_token_watcher": new_token_watcher,
        "regime_detector": regime_detector,
        "mtf_filter": mtf_filter,
        "signal_council": signal_council,
        "ensemble": ensemble,
        "dynamic_risk": dynamic_risk,
        "monte_carlo": monte_carlo,
        "walk_forward": walk_forward,
        "trade_journal": trade_journal,
        "market_scanner": market_scanner,
        "auto_trader": auto_trader,
        "market_pulse": market_pulse,
        "forecast_tracker": forecast_tracker,
        "archive_downloader": archive_downloader,
        "data_collector": data_collector,
        "ping_pong": ping_pong,
        "strategy_manager": strategy_manager,
        "arb_detector":   arb_detector,
        "arb_trader":     arb_trader,
        "trend_scanner":       trend_scanner,
        "pair_scanner":        pair_scanner,
        "pair_ml_analyzer":    pair_ml_analyzer,
        "accumulation_detector": accumulation_detector,
        "liquidity_analyzer":  liquidity_analyzer,
        "breakout_detector":   breakout_detector,
        "gap_detector":        gap_detector,
        "large_candle_watcher": large_candle_watcher,
        "ml_central":           ml_central,
        "metamask_wallet":     metamask_wallet,
        "contract_analyzer":   contract_analyzer,
        "honeypot_detector":   honeypot_detector,
        "liq_lock_analyzer":   liq_lock_analyzer,
        "wallet_graph_analyzer": wallet_graph_analyzer,
        "rugpull_scorer":      rugpull_scorer,
        "launch_signal":       launch_signal,
        "sim_twin":            sim_twin,
        "mutation_lab":        mutation_lab,
        "discord":             discord,
        "slack":               slack,
        "email_notifier":      email_notifier,
    }


def start_background_services(services: dict, settings) -> None:
    """Start all background threads and services."""
    from utils.threading_manager import get_thread_manager
    from utils.memory_manager import get_memory_manager

    thread_mgr = get_thread_manager()
    mem_mgr    = get_memory_manager()
    mem_mgr.start_monitoring(interval_sec=30.0)
    intel.system("Startup", "Memory monitor started.")

    engine = services["engine"]
    engine.start()
    intel.system("Startup", "Trading engine started.")

    predictor = services["predictor"]
    predictor.start()
    intel.system("Startup", "ML predictor started.")

    # Subscribe default symbols
    default_symbols = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]
    for sym in default_symbols:
        engine.add_symbol(sym)
        predictor.add_symbol(sym)

    # Continuous learner
    cl = services["continuous_learner"]
    cl.start(default_symbols)
    intel.system("Startup", f"Continuous learner started | {len(default_symbols)} symbols")

    # Regime detector
    regime = services.get("regime_detector")
    if regime:
        regime.start(default_symbols)
        intel.system("Startup", "Market regime detector started")

    # Whale watcher
    whale = services.get("whale_watcher")
    if whale:
        whale.start(default_symbols)
        intel.system("Startup", f"Whale watcher started | {len(default_symbols)} symbols")

    # Sentiment analyser
    sentiment = services.get("sentiment")
    if sentiment:
        sentiment.start(default_symbols)
        intel.system("Startup", "Sentiment analyser started")

    # Voice alerts
    voice = services.get("voice")
    if voice:
        voice.start()

    # Telegram bot – inject full services dict so ML layer commands work
    telegram = services.get("telegram")
    if telegram:
        telegram.set_services(services)
        telegram.start()

    # Discord, Slack, Email notifiers
    discord_ref      = services.get("discord")
    slack_ref        = services.get("slack")
    email_ref        = services.get("email_notifier")
    if discord_ref:
        discord_ref.start()
    if slack_ref:
        slack_ref.start()
    if email_ref:
        email_ref.start()

    # Wire trade alerts → voice + telegram + discord + slack + email
    engine_ref = engine
    voice_ref  = voice
    tg_ref     = telegram
    def _on_trade(trade):
        try:
            side   = trade.get("side", "")
            symbol = trade.get("symbol", "")
            price  = float(trade.get("price", 0))
            qty    = float(trade.get("qty", 0))
            pnl    = trade.get("pnl")
            if voice_ref:
                voice_ref.speak_trade(side, symbol, price, pnl)
            if tg_ref:
                tg_ref.send_trade_alert(side, symbol, price, qty, pnl)
            if discord_ref:
                discord_ref.send_trade_alert(side, symbol, price, qty, pnl)
            if slack_ref:
                slack_ref.send_trade_alert(side, symbol, price, qty, pnl)
            if email_ref and pnl is not None:
                email_ref.send_trade_alert(side, symbol, price, qty, pnl)
        except Exception:
            pass
    engine.on("trade", _on_trade)

    # Wire whale events → voice + telegram + discord + slack
    def _on_whale(event):
        try:
            ev_type    = getattr(event, "event_type", "")
            symbol     = getattr(event, "symbol", "")
            volume_usd = getattr(event, "volume_usd", 0)
            confidence = getattr(event, "confidence", 0)
            if voice_ref:
                voice_ref.speak_whale_event(ev_type, symbol, volume_usd)
            if confidence >= 0.75:
                if tg_ref:
                    tg_ref.send_whale_alert(ev_type, symbol, volume_usd, confidence)
                if discord_ref:
                    discord_ref.send_whale_alert(ev_type, symbol, volume_usd, confidence)
                if slack_ref:
                    slack_ref.send_whale_alert(ev_type, symbol, volume_usd, confidence)
        except Exception:
            pass
    engine.on("whale", _on_whale)

    # Strategy manager (ML auto-selection)
    strat_mgr = services.get("strategy_manager")
    if strat_mgr:
        strat_mgr.start()
        intel.system("Startup", "Strategy manager started (ML auto-selection active)")

    # Arbitrage detector (scanner only — auto-trader starts on demand via UI)
    arb_det = services.get("arb_detector")
    if arb_det:
        arb_det.start()
        intel.system("Startup", "Arbitrage detector started")

    # Multi-timeframe trend scanner
    trend_scanner = services.get("trend_scanner")
    if trend_scanner:
        trend_scanner.start()
        intel.system("Startup", "Trend scanner started (7 timeframes × all pairs)")

    # Pair discovery scanner — wire callbacks to propagate top pairs to all modules
    pair_scanner  = services.get("pair_scanner")
    arb_det_ref   = services.get("arb_detector")
    trend_ref     = trend_scanner
    engine_ref2   = engine
    predictor_ref = services.get("predictor")

    def _on_pairs_updated(pairs):
        """
        Called after each pair-scanner refresh.
        Propagates top pairs to ArbitrageDetector, TrendScanner,
        TradingEngine, and MLPredictor so they always have the full universe.
        """
        try:
            high_syms    = [p.symbol for p in pairs if p.priority == "HIGH"]
            medium_syms  = [p.symbol for p in pairs if p.priority == "MEDIUM"]
            all_watch    = high_syms + medium_syms          # HIGH + MEDIUM → trend scanner
            top_50       = [p.symbol for p in pairs[:50]]  # top-50 → engine / predictor

            # Trend scanner: add all HIGH + MEDIUM symbols
            if trend_ref:
                for sym in all_watch:
                    try:
                        trend_ref.add_symbol(sym)
                    except Exception:
                        pass

            # Arbitrage detector: add top-20 HIGH pairs (combined with BTCUSDT base)
            if arb_det_ref:
                for sym in high_syms[:20]:
                    try:
                        # Only add USDT pairs as stat-arb pairs against each other
                        if sym.endswith("USDT"):
                            arb_det_ref.add_pair(sym, "BTCUSDT")
                    except Exception:
                        pass

            # Engine: subscribe top-50 symbols for live WS feeds
            if engine_ref2:
                for sym in top_50:
                    try:
                        engine_ref2.add_symbol(sym)
                    except Exception:
                        pass

            # Predictor: add symbols for ML signal generation
            if predictor_ref:
                for sym in top_50:
                    try:
                        predictor_ref.add_symbol(sym)
                    except Exception:
                        pass

        except Exception as exc:
            logger.warning(f"Pair propagation error: {exc!r}")

    if pair_scanner:
        pair_scanner.on_update(_on_pairs_updated)

        # Wire pre-trading callback — log and broadcast new upcoming pair announcements
        def _on_pre_trading(pre_pairs):
            """Called when Binance lists new PRE_TRADING (upcoming) pairs."""
            try:
                syms = [p.symbol for p in pre_pairs]
                intel.ml(
                    "PairScanner",
                    f"UPCOMING PAIRS announced ({len(syms)}): "
                    + ", ".join(syms[:8]) + ("…" if len(syms) > 8 else ""),
                )
            except Exception as exc:
                logger.warning(f"Pre-trading callback error: {exc!r}")

        pair_scanner.on_pre_trading(_on_pre_trading)

        # Wire new-listing callback — fires when PRE_TRADING → TRADING (token goes live)
        _ntw_ref = services.get("new_token_watcher")

        def _on_new_listing(symbols):
            """
            Called by PairScanner when a symbol transitions PRE_TRADING → TRADING.
            This fires before the first tick data is available — earliest possible signal.
            """
            try:
                intel.ml(
                    "PairScanner",
                    f"NEW LISTING LIVE ({len(symbols)}): " + ", ".join(symbols[:8]),
                )
                # Kick off launch tracking in NewTokenWatcher for each new listing
                if _ntw_ref:
                    import threading as _thr
                    for sym in symbols:
                        try:
                            t = _thr.Thread(
                                target=_ntw_ref._track_launch,
                                args=(sym,),
                                daemon=True,
                                name=f"launch-{sym}",
                            )
                            t.start()
                        except Exception:
                            pass
            except Exception as exc:
                logger.warning(f"New listing callback error: {exc!r}")

        pair_scanner.on_new_listing(_on_new_listing)

        pair_scanner.start()
        intel.system("Startup", "Pair scanner started (all pairs + upcoming detection)")

    # Pair ML cross-reference analyzer (every 5 min after pair scanner warms up)
    pair_ml_ana = services.get("pair_ml_analyzer")
    if pair_ml_ana:
        pair_ml_ana.start()
        intel.system("Startup", "Pair ML analyzer started (cross-references all ML tools)")

    # Accumulation detector (stealth collecting — scans LOW+MEDIUM every 30 min)
    accum_det = services.get("accumulation_detector")
    if accum_det:
        accum_det.start()
        intel.system("Startup", "Accumulation detector started (stealth accumulation signals)")

    # Liquidity depth analyzer (order-book depth — scans HIGH+MEDIUM every 10 min)
    liq_ana = services.get("liquidity_analyzer")
    if liq_ana:
        liq_ana.start()
        intel.system("Startup", "Liquidity depth analyzer started (order-book depth scoring)")

    # Volume breakout detector (4-stage pattern — scans HIGH+MEDIUM every 15 min)
    brk_det = services.get("breakout_detector")
    if brk_det:
        brk_det.start()
        intel.system("Startup", "Volume breakout detector started (4-stage breakout patterns)")

    # Gap detector (gap up/down ML scanner — scans HIGH+MEDIUM every 15 min)
    gap_det = services.get("gap_detector")
    if gap_det:
        gap_det.start()
        intel.system("Startup", "Gap detector started (gap up=BUY, gap down=WATCH on 1d+4h)")

        # Broadcast GAP UP events to the entire ML pipeline for elevated monitoring.
        # When a gap up is detected the symbol is tagged so other tools increase attention.
        _gap_ensemble_ref   = services.get("ensemble")
        _gap_signal_council = services.get("signal_council")
        _gap_trend_ref      = trend_scanner
        _gap_predictor_ref  = predictor_ref
        _gap_engine_ref     = engine_ref2
        _gap_market_scanner = services.get("market_scanner")

        def _on_gap_up_watch(gaps):
            """
            Called by GapDetector whenever new GAP UP (WATCH) signals are found.
            Tags affected symbols for elevated attention across the whole ML pipeline.
            """
            try:
                open_gaps = [g for g in gaps if g.state == "OPEN"]
                if not open_gaps:
                    return
                symbols = list({g.symbol for g in open_gaps})

                intel.ml(
                    "GapDetector",
                    f"GAP UP watch broadcast → elevated monitoring on {len(symbols)} symbol(s): "
                    + ", ".join(symbols[:8]) + ("…" if len(symbols) > 8 else ""),
                )

                # Trend scanner — add symbols for multi-TF momentum tracking
                if _gap_trend_ref:
                    for sym in symbols:
                        try:
                            _gap_trend_ref.add_symbol(sym)
                        except Exception:
                            pass

                # Predictor — add symbols so ML model generates fresh signals
                if _gap_predictor_ref:
                    for sym in symbols:
                        try:
                            _gap_predictor_ref.add_symbol(sym)
                        except Exception:
                            pass

                # Engine — subscribe live WS feed for order-book + tick data
                if _gap_engine_ref:
                    for sym in symbols:
                        try:
                            _gap_engine_ref.add_symbol(sym)
                        except Exception:
                            pass

                # Ensemble — feed gap-up signals so confidence weighting increases
                if _gap_ensemble_ref:
                    for g in open_gaps:
                        try:
                            _gap_ensemble_ref.feed("gap_up_watch", {
                                "symbol":     g.symbol,
                                "signal":     "WATCH",
                                "confidence": g.gap_score,
                                "note": (
                                    f"GAP_UP {g.gap_pct:+.2f}%  tf={g.timeframe}  "
                                    f"fill_prob={g.fill_probability:.2f}"
                                ),
                            })
                        except Exception:
                            pass

                # Signal council — register as a watch signal for vote weighting
                if _gap_signal_council:
                    for g in open_gaps:
                        try:
                            _gap_signal_council.register_signal(
                                source="gap_up_watch",
                                symbol=g.symbol,
                                signal="WATCH",
                                confidence=g.gap_score,
                            )
                        except Exception:
                            pass

            except Exception as exc:
                logger.warning(f"Gap-up watch broadcast error: {exc!r}")

        gap_det.on_gap_up_watch(_on_gap_up_watch)

    # Large candle watcher (1m/5m/15m rapid expansion alerts — scans every 60 s)
    lcw = services.get("large_candle_watcher")
    if lcw:
        lcw.start()
        intel.system("Startup", "Large candle watcher started (expansion alerts on 1m/5m/15m)")

        # Feed STRONG/ALERT candle events into the ML pipeline for elevated attention
        _lcw_ensemble = services.get("ensemble")
        _lcw_council  = services.get("signal_council")

        def _on_large_candle(results):
            try:
                for r in results:
                    if r.label == "NONE":
                        continue
                    if _lcw_ensemble:
                        try:
                            _lcw_ensemble.feed("large_candle_watch", {
                                "symbol":     r.symbol,
                                "signal":     "WATCH",
                                "confidence": r.candle_score,
                                "note": (
                                    f"LARGE_CANDLE {r.label} {r.direction} "
                                    f"×{r.expansion_ratio:.1f} on {r.timeframe}"
                                ),
                            })
                        except Exception:
                            pass
                    if _lcw_council and r.label in ("ALERT", "STRONG"):
                        try:
                            _lcw_council.register_signal(
                                source="large_candle_watch",
                                symbol=r.symbol,
                                signal="WATCH",
                                confidence=r.candle_score,
                            )
                        except Exception:
                            pass
            except Exception as exc:
                logger.warning(f"Large candle broadcast error: {exc!r}")

        lcw.on_alert(_on_large_candle)

    # Market pulse broad monitor
    market_pulse = services.get("market_pulse")
    if market_pulse:
        market_pulse.start()
        intel.system("Startup", "Market pulse monitor started (5-min broad scan)")

    # Market scanner (background 5-min cycle)
    market_scanner = services.get("market_scanner")
    if market_scanner:
        market_scanner.start(interval_sec=300)
        intel.system("Startup", "Market scanner started (every 5 min)")

    # Auto-trader (defaults to SEMI_AUTO – human presses Take Aim to confirm)
    auto_trader = services.get("auto_trader")
    if auto_trader:
        auto_trader.start()
        intel.system("Startup", "AutoTrader started (SEMI_AUTO mode)")

    # New token launch watcher
    ntw = services.get("new_token_watcher")
    if ntw:
        ntw.start()
        intel.system("Startup", "New token launch watcher started")

    # Live simulation twin
    sim_twin = services.get("sim_twin")
    if sim_twin:
        sim_twin.start()
        intel.system("Startup", "Live simulation twin started")

    # Token launch signal engine (event-driven, no background thread needed)
    if services.get("launch_signal"):
        intel.system("Startup", "Token launch signal engine ready (event-driven)")

    # ── ML Central Command ──────────────────────────────────────────────────────
    # Wire all ML tools to feed their signals into the central pipeline aggregator.
    ml_central = services.get("ml_central")
    if ml_central:
        ml_central.start()
        intel.system("Startup", "ML central command started (unified signal pipeline)")

        _central = ml_central   # closure capture

        # 1. Predictor (LSTM/Transformer) signals
        pred_ref = services.get("predictor")
        if pred_ref:
            try:
                pred_ref.on_signal(lambda s: _central.feed(
                    "lstm_predictor",
                    symbol     = s.get("symbol", ""),
                    signal     = s.get("action", "HOLD"),
                    confidence = s.get("confidence", 0.5),
                    note       = s.get("note", ""),
                ))
            except Exception:
                pass

        # 2. Ensemble aggregator signals
        ens_ref = services.get("ensemble")
        if ens_ref:
            try:
                ens_ref.on_signal(lambda s: _central.feed(
                    "ensemble",
                    symbol     = s.get("symbol", ""),
                    signal     = s.get("signal", "HOLD"),
                    confidence = s.get("confidence", 0.5),
                    note       = s.get("note", ""),
                ))
            except Exception:
                pass

        # 3. Signal council votes
        sc_ref = services.get("signal_council")
        if sc_ref:
            try:
                sc_ref.on_decision(lambda s: _central.feed(
                    "signal_council",
                    symbol     = s.get("symbol", ""),
                    signal     = s.get("signal", "HOLD"),
                    confidence = s.get("confidence", 0.5),
                    note       = s.get("note", ""),
                ))
            except Exception:
                pass

        # 4. Gap detector — both BUY and WATCH signals
        gap_ref = services.get("gap_detector")
        if gap_ref:
            try:
                gap_ref.on_gap_up(lambda gaps: [
                    _central.feed(
                        "gap_down_buy",
                        symbol     = g.symbol,
                        signal     = "BUY",
                        confidence = g.gap_score,
                        note       = f"GAP_DOWN {g.gap_pct:+.2f}% tf={g.timeframe}",
                    ) for g in gaps
                ])
            except Exception:
                pass
            try:
                gap_ref.on_gap_up_watch(lambda gaps: [
                    _central.feed(
                        "gap_up_watch",
                        symbol     = g.symbol,
                        signal     = "WATCH",
                        confidence = g.gap_score,
                        note       = f"GAP_UP {g.gap_pct:+.2f}% tf={g.timeframe}",
                    ) for g in gaps
                ])
            except Exception:
                pass

        # 5. Accumulation detector signals
        accum_ref = services.get("accumulation_detector")
        if accum_ref:
            try:
                accum_ref.on_alert(lambda results: [
                    _central.feed(
                        "accumulation",
                        symbol     = r.symbol,
                        signal     = "BUY" if r.label in ("ALERT", "STRONG") else "WATCH",
                        confidence = r.accumulation_score,
                        note       = f"ACCUM {r.label}",
                    ) for r in results if r.label != "NONE"
                ])
            except Exception:
                pass

        # 6. Volume breakout detector signals
        brk_ref = services.get("breakout_detector")
        if brk_ref:
            try:
                brk_ref.on_breakout(lambda results: [
                    _central.feed(
                        "breakout",
                        symbol     = r.symbol,
                        signal     = "BUY" if r.stage >= 3 else "WATCH",
                        confidence = r.breakout_score,
                        note       = f"BREAKOUT stage={r.stage}",
                    ) for r in results if r.stage >= 2
                ])
            except Exception:
                pass

        # 7. Large candle watcher signals
        lcw_ref = services.get("large_candle_watcher")
        if lcw_ref:
            try:
                lcw_ref.on_alert(lambda results: [
                    _central.feed(
                        "large_candle_watch",
                        symbol     = r.symbol,
                        signal     = "WATCH",
                        confidence = r.candle_score,
                        note       = f"LARGE_CANDLE {r.label} {r.direction} ×{r.expansion_ratio:.1f}",
                    ) for r in results if r.label != "NONE"
                ])
            except Exception:
                pass

        # 8. Whale watcher events
        whale_ref = services.get("whale_watcher")
        if whale_ref:
            try:
                whale_ref.on_event(lambda ev: _central.feed(
                    "whale_watcher",
                    symbol     = getattr(ev, "symbol", ""),
                    signal     = "WATCH",
                    confidence = getattr(ev, "confidence", 0.5),
                    note       = f"WHALE {getattr(ev, 'event_type', '')}",
                ))
            except Exception:
                pass

        intel.system("Startup", "ML central command fully wired to all ML sources")

    # Start REST API server
    try:
        from api.server import get_api_server
        api_srv = get_api_server()
        api_srv.start(
            engine=engine,
            portfolio=services["portfolio"],
            predictor=predictor,
            order_manager=services["orders"],
            tax_calc=services["tax_calc"],
            services=services,
        )
        intel.api("Startup", f"REST API server: {api_srv.base_url}")
    except Exception as exc:
        intel.warning("Startup", f"API server failed to start: {exc}")

    # Check if first training is needed
    try:
        from sqlalchemy import select
        from db.postgres import get_db
        from db.models import MLModel
        with get_db() as db:
            has_model = db.execute(select(MLModel).filter_by(is_active=True)).scalar_one_or_none()
        if not has_model and settings.ml.training_hours > 0:
            intel.ml("Startup", "No trained model found – scheduling initial 48h training session…")
            def _deferred_training():
                time.sleep(5)   # Let UI load first
                services["trainer"].run_training_session()
            thread_mgr.submit_ml(_deferred_training)
    except Exception:
        pass

    intel.success("Startup", "All background services started successfully ✅")


def run_first_time_setup(app: QApplication, settings) -> bool:
    """Run setup wizard on first launch. Returns True if setup completed."""
    from ui.setup_wizard import SetupWizard
    completed = threading.Event()
    result = {"ok": False}

    def on_complete(data):
        result["ok"] = True
        completed.set()

    wizard = SetupWizard()
    wizard.setup_complete.connect(on_complete)
    wizard.show()

    # Block until wizard finishes
    while not completed.is_set() and wizard.isVisible():
        app.processEvents()
        time.sleep(0.05)

    return result["ok"] or not wizard.isVisible()


def main() -> int:
    # ── Qt application ────────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setApplicationName("BinanceML Pro")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("BinanceMLPro")

    # High-DPI support
    from ui.styles import apply_theme, DEFAULT_THEME
    # Load saved theme preference (falls back to DEFAULT_THEME = bitnfloat)
    _saved_theme = DEFAULT_THEME
    try:
        from config import get_settings as _gs
        _saved_theme = getattr(_gs(), "ui_theme", DEFAULT_THEME) or DEFAULT_THEME
    except Exception:
        pass
    apply_theme(app, _saved_theme)

    # Font
    font = QFont("SF Pro Display", 13)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)

    splash = create_splash(app)
    intel.system("Startup", "BinanceML Pro starting…")

    # ── Settings ──────────────────────────────────────────────────────
    from config import get_settings
    settings = get_settings()

    # Attempt to load config (may fail on first run)
    try:
        from config.encryption import EncryptionManager
        enc = EncryptionManager()
        # Try with empty password (unencrypted plain config)
        try:
            enc.initialise("placeholder")
        except Exception:
            pass
        settings.load()
    except Exception as exc:
        logger.debug(f"Config load: {exc}")

    # ── First-run setup ────────────────────────────────────────────────
    if settings.first_run:
        splash.hide()
        ok = run_first_time_setup(app, settings)
        if not ok:
            return 0
        settings.load()
        splash.show()

    # ── Database init ──────────────────────────────────────────────────
    splash.showMessage("Connecting to databases…", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, QColor("#00D4FF"))
    app.processEvents()
    init_databases()

    # ── Services ───────────────────────────────────────────────────────
    splash.showMessage("Starting trading services…", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, QColor("#00D4FF"))
    app.processEvents()

    try:
        services = build_services(settings)
    except Exception as exc:
        logger.error(f"Service build failed: {exc}")
        intel.error("Startup", f"Service build failed: {exc} – launching in demo mode")
        services = {
            "binance": None, "engine": None, "orders": None,
            "portfolio": None, "risk": None, "trainer": None,
            "predictor": None, "continuous_learner": None, "tax_calc": None,
        }

    # ── Background services ────────────────────────────────────────────
    splash.showMessage("Starting background services…", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, QColor("#00D4FF"))
    app.processEvents()

    try:
        start_background_services(services, settings)
    except Exception as exc:
        logger.warning(f"Some background services failed: {exc}")

    # ── Main window ────────────────────────────────────────────────────
    splash.showMessage("Loading UI…", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, QColor("#00D4FF"))
    app.processEvents()

    from ui.main_window import MainWindow
    window = MainWindow(
        engine=services.get("engine"),
        portfolio=services.get("portfolio"),
        predictor=services.get("predictor"),
        order_manager=services.get("orders"),
        trainer=services.get("trainer"),
        tax_calc=services.get("tax_calc"),
        continuous_learner=services.get("continuous_learner"),
        whale_watcher=services.get("whale_watcher"),
        token_ml=services.get("token_ml"),
        sentiment=services.get("sentiment"),
        port_opt=services.get("port_opt"),
        backtester=services.get("backtester"),
        voice=services.get("voice"),
        telegram=services.get("telegram"),
        new_token_watcher=services.get("new_token_watcher"),
        regime_detector=services.get("regime_detector"),
        mtf_filter=services.get("mtf_filter"),
        signal_council=services.get("signal_council"),
        ensemble=services.get("ensemble"),
        dynamic_risk=services.get("dynamic_risk"),
        monte_carlo=services.get("monte_carlo"),
        walk_forward=services.get("walk_forward"),
        trade_journal=services.get("trade_journal"),
        market_scanner=services.get("market_scanner"),
        auto_trader=services.get("auto_trader"),
        market_pulse=services.get("market_pulse"),
        forecast_tracker=services.get("forecast_tracker"),
        archive_downloader=services.get("archive_downloader"),
        data_collector=services.get("data_collector"),
        ping_pong=services.get("ping_pong"),
        strategy_manager=services.get("strategy_manager"),
        arb_detector=services.get("arb_detector"),
        arb_trader=services.get("arb_trader"),
        trend_scanner=services.get("trend_scanner"),
        pair_scanner=services.get("pair_scanner"),
        pair_ml_analyzer=services.get("pair_ml_analyzer"),
        accumulation_detector=services.get("accumulation_detector"),
        liquidity_analyzer=services.get("liquidity_analyzer"),
        breakout_detector=services.get("breakout_detector"),
        gap_detector=services.get("gap_detector"),
        large_candle_watcher=services.get("large_candle_watcher"),
        ml_central=services.get("ml_central"),
        metamask_wallet=services.get("metamask_wallet"),
        sim_twin=services.get("sim_twin"),
        mutation_lab=services.get("mutation_lab"),
        contract_analyzer=services.get("contract_analyzer"),
        honeypot_detector=services.get("honeypot_detector"),
        liq_lock_analyzer=services.get("liq_lock_analyzer"),
        wallet_graph_analyzer=services.get("wallet_graph_analyzer"),
        rugpull_scorer=services.get("rugpull_scorer"),
        launch_signal=services.get("launch_signal"),
        discord=services.get("discord"),
        slack=services.get("slack"),
        email_notifier=services.get("email_notifier"),
    )
    splash.finish(window)
    window.showMaximized()

    intel.success("Startup", "BinanceML Pro ready ✅")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
