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

    intel.system("Startup", "Initialising auto-trader…")
    from core.auto_trader import AutoTrader
    auto_trader = AutoTrader(
        engine=engine,
        scanner=market_scanner,
        dynamic_risk=dynamic_risk,
        trade_journal=trade_journal,
        binance_client=binance,
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

    # Telegram bot
    telegram = services.get("telegram")
    if telegram:
        telegram.start()

    # Wire trade alerts → voice + telegram
    engine_ref = engine
    voice_ref  = voice
    tg_ref     = telegram
    def _on_trade(trade):
        try:
            if voice_ref:
                pnl = trade.get("pnl")
                voice_ref.speak_trade(trade.get("side",""), trade.get("symbol",""), float(trade.get("price",0)), pnl)
            if tg_ref:
                tg_ref.send_trade_alert(trade.get("side",""), trade.get("symbol",""), float(trade.get("price",0)), float(trade.get("qty",0)), trade.get("pnl"))
        except Exception:
            pass
    engine.on("trade", _on_trade)

    # Wire whale events → voice + telegram
    def _on_whale(event):
        try:
            if voice_ref:
                voice_ref.speak_whale_event(getattr(event,"event_type",""), getattr(event,"symbol",""), getattr(event,"volume_usd",0))
            if tg_ref and getattr(event,"confidence",0) >= 0.75:
                tg_ref.send_whale_alert(getattr(event,"event_type",""), getattr(event,"symbol",""), getattr(event,"volume_usd",0), getattr(event,"confidence",0))
        except Exception:
            pass
    engine.on("whale", _on_whale)

    # Strategy manager (ML auto-selection)
    strat_mgr = services.get("strategy_manager")
    if strat_mgr:
        strat_mgr.start()
        intel.system("Startup", "Strategy manager started (ML auto-selection active)")

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
        )
        intel.api("Startup", f"REST API server: {api_srv.base_url}")
    except Exception as exc:
        intel.warning("Startup", f"API server failed to start: {exc}")

    # Check if first training is needed
    try:
        from db.postgres import get_db
        from db.models import MLModel
        with get_db() as db:
            has_model = db.query(MLModel).filter_by(is_active=True).first()
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
    from ui.styles import apply_theme
    apply_theme(app)

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
    )
    splash.finish(window)
    window.showMaximized()

    intel.success("Startup", "BinanceML Pro ready ✅")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
