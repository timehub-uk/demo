"""
Main application window – the primary UI container.

Layout:
  ┌─────────────────────────────────────────────────────────────┐
  │  Menu Bar                                                   │
  ├─────────────────────────────────────────────────────────────┤
  │  Status Bar (ticker strip – live prices)                    │
  ├────────────────────────────────────────────────────────────-┤
  │ ┌─────────────────────────────┐ ┌────────────────────────┐  │
  │ │  Chart Widget               │ │  Order Book (L1/L2)    │  │
  │ │                             │ │                        │  │
  │ ├─────────────────────────────┤ ├────────────────────────┤  │
  │ │  Trading Panel              │ │  ML Signals / Training │  │
  │ └─────────────────────────────┘ └────────────────────────┘  │
  ├─────────────────────────────────────────────────────────────┤
  │  Intel Log (bottom, collapsible)                            │
  └─────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QAction, QFont, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QLabel, QStatusBar, QToolBar, QMenuBar, QMenu,
    QFrame, QPushButton, QComboBox, QSizePolicy, QMessageBox,
    QDockWidget,
)

from config import get_settings
from utils.logger import get_intel_logger, setup_logger
from ui.styles import ACCENT, GREEN, RED, YELLOW, BG0, BG1, BG2, BG3, BG4, BORDER, FG0, FG1, FG2
from ui.chart_widget import ChartWidget
from ui.orderbook_widget import OrderBookWidget
from ui.trading_panel import TradingPanel
from ui.ml_training_widget import MLTrainingWidget
from ui.intel_log_widget import IntelLogWidget


# ── Ticker strip widget ───────────────────────────────────────────────────────

class TickerStrip(QWidget):
    """Scrolling ticker with live price updates."""

    def __init__(self, symbols: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setStyleSheet(f"background:{BG0}; border-bottom:1px solid {BORDER};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(20)
        self._labels: dict[str, QLabel] = {}
        for sym in symbols:
            lbl = QLabel(f"{sym}  —")
            lbl.setStyleSheet(f"font-size:11px; color:{FG1}; font-family:monospace;")
            layout.addWidget(lbl)
            self._labels[sym] = lbl
        layout.addStretch()
        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

    def _refresh(self) -> None:
        try:
            from db.redis_client import RedisClient
            rc = RedisClient()
            for sym, lbl in self._labels.items():
                data = rc.get_ticker(sym)
                if data:
                    price = float(data.get("price", 0))
                    chg = float(data.get("change_pct", 0))
                    colour = GREEN if chg >= 0 else RED
                    sign = "+" if chg >= 0 else ""
                    lbl.setText(f"{sym}  {price:,.4f}  <span style='color:{colour};'>{sign}{chg:.2f}%</span>")
        except Exception:
            pass


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """BinanceML Pro – main application window."""

    def __init__(
        self,
        engine=None,
        portfolio=None,
        predictor=None,
        order_manager=None,
        trainer=None,
        tax_calc=None,
        continuous_learner=None,
        whale_watcher=None,
        token_ml=None,
        sentiment=None,
        port_opt=None,
        backtester=None,
        voice=None,
        telegram=None,
        new_token_watcher=None,
        regime_detector=None,
        ensemble=None,
        dynamic_risk=None,
        monte_carlo=None,
        walk_forward=None,
        trade_journal=None,
        market_scanner=None,
        auto_trader=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._portfolio = portfolio
        self._predictor = predictor
        self._order_manager = order_manager
        self._trainer = trainer
        self._tax_calc = tax_calc
        self._cl = continuous_learner
        self._whale_watcher = whale_watcher
        self._token_ml = token_ml
        self._sentiment = sentiment
        self._port_opt = port_opt
        self._backtester = backtester
        self._voice = voice
        self._telegram = telegram
        self._new_token_watcher = new_token_watcher
        self._regime_detector = regime_detector
        self._ensemble = ensemble
        self._dynamic_risk = dynamic_risk
        self._monte_carlo = monte_carlo
        self._walk_forward = walk_forward
        self._trade_journal = trade_journal
        self._market_scanner = market_scanner
        self._auto_trader = auto_trader
        self._settings = get_settings()
        self._intel = get_intel_logger()

        self._current_symbol = "BTCUSDT"
        self._active_symbols = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]

        self.setWindowTitle("BinanceML Pro  ·  Professional AI Trading Platform")
        self.setMinimumSize(1400, 900)
        self._setup_menu()
        self._setup_toolbar()
        self._setup_central()
        self._setup_statusbar()
        self._connect_signals()
        self._start_timers()
        self._intel.system("MainWindow", "Application started successfully.")

    # ── Menu bar ───────────────────────────────────────────────────────
    def _setup_menu(self) -> None:
        menubar = self.menuBar()

        # File
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self._action("Settings", self._open_settings, "Ctrl+,"))
        file_menu.addSeparator()
        file_menu.addAction(self._action("Exit", self.close, "Ctrl+Q"))

        # Trading
        trade_menu = menubar.addMenu("&Trading")
        trade_menu.addAction(self._action("Manual Mode",
            lambda: self._set_engine_mode("manual")))
        trade_menu.addAction(self._action("Auto Mode",
            lambda: self._set_engine_mode("auto")))
        trade_menu.addAction(self._action("Hybrid Mode",
            lambda: self._set_engine_mode("hybrid")))
        trade_menu.addAction(self._action("Paper Trading (Simulated)",
            lambda: self._set_engine_mode("paper")))
        trade_menu.addSeparator()
        trade_menu.addAction(self._action("Pause Engine",
            lambda: self._set_engine_mode("paused")))
        trade_menu.addSeparator()
        trade_menu.addAction(self._action("Cancel All Orders",
            self._cancel_all_orders))

        # ML
        ml_menu = menubar.addMenu("&Machine Learning")
        ml_menu.addAction(self._action("Start 48h Training", self._start_training))
        ml_menu.addAction(self._action("Stop Training", self._stop_training))
        ml_menu.addSeparator()
        ml_menu.addAction(self._action("Run Data Integrity Check", self._run_integrity_check))
        ml_menu.addAction(self._action("Reload Model", self._reload_model))

        # Tax
        tax_menu = menubar.addMenu("&Tax")
        tax_menu.addAction(self._action("Generate Monthly Report", self._generate_tax_report))
        tax_menu.addAction(self._action("Annual CGT Summary", self._generate_annual_tax))
        tax_menu.addAction(self._action("Send Tax Email Now", self._send_tax_email))

        # API
        api_menu = menubar.addMenu("&API")
        api_menu.addAction(self._action("Start REST API Server", self._start_api_server))
        api_menu.addAction(self._action("View API Docs", self._show_api_docs))
        api_menu.addSeparator()
        api_menu.addAction(self._action("Manage Webhooks", self._show_webhooks))

        # View
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self._action("Toggle Intel Log", self._toggle_intel_log, "Ctrl+L"))
        view_menu.addAction(self._action("Toggle Order Book", self._toggle_order_book))
        view_menu.addAction(self._action("Toggle ML Panel", self._toggle_ml_panel))

        # Help
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(self._action("About", self._show_about))
        help_menu.addAction(self._action("Check for Updates", lambda: None))

    @staticmethod
    def _action(label: str, fn, shortcut: str | None = None) -> QAction:
        act = QAction(label)
        act.triggered.connect(fn)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        return act

    # ── Toolbar ────────────────────────────────────────────────────────
    def _setup_toolbar(self) -> None:
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False)
        tb.setStyleSheet(f"background:{BG0}; border-bottom:1px solid {BORDER}; spacing:6px;")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        # Symbol selector
        self.sym_combo = QComboBox()
        self.sym_combo.setFixedWidth(130)
        for s in self._active_symbols:
            self.sym_combo.addItem(s)
        self.sym_combo.currentTextChanged.connect(self._on_symbol_changed)
        tb.addWidget(QLabel("  Symbol: "))
        tb.addWidget(self.sym_combo)
        tb.addSeparator()

        # Engine mode indicator
        self.mode_indicator = QLabel("⬤ MANUAL")
        self.mode_indicator.setStyleSheet(f"color:{YELLOW}; font-weight:700; font-size:12px;")
        tb.addWidget(self.mode_indicator)
        tb.addSeparator()

        # Quick mode buttons
        for label, mode, colour in [
            ("AUTO", "auto", GREEN),
            ("MANUAL", "manual", YELLOW),
            ("HYBRID", "hybrid", ACCENT),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setFixedWidth(70)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:{BG3}; color:{colour};
                    border:1px solid {colour}55; border-radius:4px; font-weight:600;
                }}
                QPushButton:hover {{ background:{colour}22; }}
            """)
            btn.clicked.connect(lambda _, m=mode: self._set_engine_mode(m))
            tb.addWidget(btn)

        tb.addSeparator()

        # System stats
        self.cpu_lbl = QLabel("CPU: —")
        self.cpu_lbl.setStyleSheet(f"color:{FG1}; font-size:11px;")
        tb.addWidget(self.cpu_lbl)
        self.mem_lbl = QLabel("MEM: —")
        self.mem_lbl.setStyleSheet(f"color:{FG1}; font-size:11px;")
        tb.addWidget(self.mem_lbl)

        # Ticker strip (second toolbar)
        ticker_tb = QToolBar("Ticker")
        ticker_tb.setMovable(False)
        ticker_tb.setStyleSheet(f"background:{BG0}; border-bottom:1px solid {BORDER};")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, ticker_tb)
        self.insertToolBarBreak(ticker_tb)
        self.ticker_strip = TickerStrip(self._active_symbols)
        ticker_tb.addWidget(self.ticker_strip)

    # ── Central widget ─────────────────────────────────────────────────
    def _setup_central(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Main horizontal splitter (chart+trading | orderbook+ml)
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setChildrenCollapsible(False)
        main_layout.addWidget(self._main_splitter, 1)

        # ── Left pane: chart + trading ──────────────────────────────────
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.setChildrenCollapsible(False)

        self.chart_widget = ChartWidget()
        self.chart_widget.symbol_changed.connect(self._on_symbol_changed)
        left_splitter.addWidget(self.chart_widget)

        self.trading_panel = TradingPanel()
        self.trading_panel.order_submitted.connect(self._on_order_submitted)
        self.trading_panel.cancel_requested.connect(self._on_cancel_requested)
        left_splitter.addWidget(self.trading_panel)
        left_splitter.setSizes([600, 350])
        self._main_splitter.addWidget(left_splitter)

        # ── Right pane: order book + tabs (ML / signals / etc) ────────────
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        self.orderbook_widget = OrderBookWidget(self._current_symbol)
        right_splitter.addWidget(self.orderbook_widget)

        right_tabs = QTabWidget()
        right_tabs.setStyleSheet(
            f"QTabBar::tab {{ color:{FG1}; background:{BG2}; padding:4px 10px; }}"
            f"QTabBar::tab:selected {{ background:{BG3}; color:{ACCENT}; }}"
        )
        self.ml_widget = MLTrainingWidget(trainer=self._trainer)
        right_tabs.addTab(self.ml_widget, "🤖 ML Training")

        # Data Integrity tab
        self.integrity_widget = self._build_integrity_widget()
        right_tabs.addTab(self.integrity_widget, "🔍 Data Integrity")

        # Backtest tab
        try:
            from ui.backtest_widget import BacktestWidget
            self.backtest_widget = BacktestWidget(backtester=self._backtester)
            right_tabs.addTab(self.backtest_widget, "📊 Backtest")
        except Exception:
            self.backtest_widget = None

        # Strategy builder tab
        try:
            from ui.strategy_builder import StrategyBuilderWidget
            self.strategy_widget = StrategyBuilderWidget(backtester=self._backtester)
            self.strategy_widget.backtest_requested.connect(
                lambda d: self._intel.ml("StrategyBuilder", f"Backtest requested: {d.get('name')}")
            )
            right_tabs.addTab(self.strategy_widget, "⚙️ Strategies")
        except Exception:
            self.strategy_widget = None

        right_splitter.addWidget(right_tabs)
        right_splitter.setSizes([420, 430])
        self._main_splitter.addWidget(right_splitter)
        self._main_splitter.setSizes([1000, 400])

        # Wire whale events → ML widget
        if self._whale_watcher:
            try:
                self._whale_watcher.on_event(
                    lambda ev: self.ml_widget.add_whale_event(ev)
                )
            except Exception:
                pass

        # Wire token ML signals → ML widget
        if self._token_ml:
            try:
                self._token_ml.on_signal(
                    lambda sig: self.ml_widget.add_signal({**sig, "source": "TokenML"})
                )
            except Exception:
                pass

        # Wire new token launch signals → intel log + voice
        if self._new_token_watcher:
            try:
                def _on_launch_signal(sig):
                    self._intel.ml("NewTokenWatcher",
                        f"🚀 {sig.symbol} bar {sig.bar_num}: {sig.action} ({sig.confidence:.0%}) – {sig.reason}")
                    if self._voice and sig.action in ("ENTER_LONG", "EXIT_LONG"):
                        self._voice.speak_alert(
                            f"Launch signal: {sig.action.replace('_',' ')} {sig.symbol}"
                        )
                self._new_token_watcher.on_signal(_on_launch_signal)
            except Exception:
                pass

        # Risk Dashboard tab
        try:
            from ui.risk_dashboard import RiskDashboard
            self.risk_dashboard = RiskDashboard(
                dynamic_risk=self._dynamic_risk,
                regime_detector=self._regime_detector,
                ensemble=self._ensemble,
                trade_journal=self._trade_journal,
                monte_carlo=self._monte_carlo,
                walk_forward=self._walk_forward,
                engine=self._engine,
            )
            right_tabs.addTab(self.risk_dashboard, "⚡ Risk")
        except Exception:
            self.risk_dashboard = None

        # ── Intel Log (bottom dock) ──────────────────────────────────────
        self.intel_dock = QDockWidget("Intel Log", self)
        self.intel_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.intel_log = IntelLogWidget()
        self.intel_dock.setWidget(self.intel_log)
        self.intel_dock.setMinimumHeight(180)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.intel_dock)

    def _build_integrity_widget(self) -> QWidget:
        """Simple integrity check status display."""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        header = QLabel("🔍 ML Data Integrity Monitor")
        header.setStyleSheet(f"color:{ACCENT}; font-size:12px; font-weight:700;")
        layout.addWidget(header)

        info = QLabel(
            f"Automatic integrity checks run every 25 minutes.\n"
            f"Checks: Row count • OHLC validity • NULL columns\n"
            f"        Timestamp gaps • Volume validity"
        )
        info.setStyleSheet(f"color:{FG1}; font-size:11px;")
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        run_btn = QPushButton("▶ Run Check Now")
        run_btn.setObjectName("btn_primary")
        run_btn.clicked.connect(self._run_integrity_check)
        btn_row.addWidget(run_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.integrity_status_lbl = QLabel("Last check: Not run yet")
        self.integrity_status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        layout.addWidget(self.integrity_status_lbl)

        from PyQt6.QtWidgets import QTextEdit
        self.integrity_log = QTextEdit()
        self.integrity_log.setReadOnly(True)
        self.integrity_log.setStyleSheet(f"""
            QTextEdit {{
                background:{BG2}; color:{FG0}; font-size:11px;
                font-family: monospace; border:none;
            }}
        """)
        layout.addWidget(self.integrity_log, 1)
        return w

    # ── Status bar ─────────────────────────────────────────────────────
    def _setup_statusbar(self) -> None:
        sb = self.statusBar()
        self.sb_mode_lbl   = QLabel("Mode: MANUAL")
        self.sb_trades_lbl = QLabel("Trades today: 0")
        self.sb_pnl_lbl    = QLabel("P&L: $0.00")
        self.sb_api_lbl    = QLabel("API: ⬤ Connected")
        self.sb_api_lbl.setStyleSheet(f"color:{GREEN};")
        self.sb_time_lbl   = QLabel("")
        for w in [self.sb_mode_lbl, self.sb_trades_lbl, self.sb_pnl_lbl, self.sb_api_lbl]:
            sb.addWidget(w)
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.VLine)
            sep.setStyleSheet(f"color:{BORDER};")
            sb.addWidget(sep)
        sb.addPermanentWidget(self.sb_time_lbl)

    # ── Signal connections ──────────────────────────────────────────────
    def _connect_signals(self) -> None:
        if self._engine:
            self._engine.on("heartbeat", self._on_heartbeat)
            self._engine.on("trade", self._on_trade_event)
            self._engine.on("signal", self._on_signal_event)
            self._engine.on("mode_change", self._on_mode_change)
        if self._predictor:
            self._predictor.on_signal(self._on_ml_signal)

    # ── Timers ─────────────────────────────────────────────────────────
    def _start_timers(self) -> None:
        # Clock
        clock_timer = QTimer(self)
        clock_timer.timeout.connect(self._update_clock)
        clock_timer.start(1000)

        # System stats
        stats_timer = QTimer(self)
        stats_timer.timeout.connect(self._update_stats)
        stats_timer.start(5000)

        # Orders refresh
        orders_timer = QTimer(self)
        orders_timer.timeout.connect(self._refresh_orders)
        orders_timer.start(3000)

    # ── Event handlers ─────────────────────────────────────────────────
    def _on_heartbeat(self, data: dict) -> None:
        metrics = data.get("metrics", {})
        self.trading_panel.update_pnl(metrics)
        self.sb_trades_lbl.setText(f"Trades today: {metrics.get('trades_today',0)}")
        pnl = metrics.get("pnl_today", 0)
        colour = GREEN if pnl >= 0 else RED
        self.sb_pnl_lbl.setStyleSheet(f"color:{colour};")
        self.sb_pnl_lbl.setText(f"P&L: ${pnl:+,.2f}")

    def _on_trade_event(self, trade: dict) -> None:
        self._intel.trade("TradingEngine",
            f"{trade.get('side')} {trade.get('quantity')} {trade.get('symbol')} @ {trade.get('price')}", trade)
        from api.webhooks import get_webhook_manager
        get_webhook_manager().emit_trade(trade)

    def _on_signal_event(self, signal: dict) -> None:
        pass  # Handled via predictor callback

    def _on_mode_change(self, data: dict) -> None:
        mode = str(data.get("new","")).upper()
        colour = {
            "AUTO": GREEN, "MANUAL": YELLOW,
            "HYBRID": ACCENT, "PAUSED": RED
        }.get(mode, FG1)
        self.mode_indicator.setText(f"⬤ {mode}")
        self.mode_indicator.setStyleSheet(f"color:{colour}; font-weight:700; font-size:12px;")
        self.sb_mode_lbl.setText(f"Mode: {mode}")
        self._intel.system("TradingEngine", f"Engine mode changed to {mode}")

    def _on_ml_signal(self, signal: dict) -> None:
        self.ml_widget.add_signal(signal)
        action = signal.get("action","")
        conf = signal.get("confidence", 0)
        sym = signal.get("symbol","")
        colour = GREEN if action == "BUY" else RED if action == "SELL" else YELLOW
        self._intel.signal("MLPredictor",
            f"{action} signal for {sym} | Confidence: {conf:.1%} | Price: {signal.get('price',0):,.4f}", signal)
        from api.webhooks import get_webhook_manager
        get_webhook_manager().emit_signal(signal)

    def _on_symbol_changed(self, symbol: str) -> None:
        self._current_symbol = symbol
        self.orderbook_widget.set_symbol(symbol)
        self.chart_widget.set_symbol(symbol)
        if self._predictor:
            self._predictor.add_symbol(symbol)
        if self._engine:
            self._engine.add_symbol(symbol)

    def _on_order_submitted(self, order: dict) -> None:
        if not self._order_manager:
            self._intel.warning("MainWindow", "Order manager not available – demo mode")
            return
        side = order["side"]
        if side == "BUY":
            result = self._engine.manual_buy(
                order["symbol"],
                Decimal(str(order["quantity"])),
                Decimal(str(order["price"])),
            ) if self._engine else None
        else:
            result = self._engine.manual_sell(
                order["symbol"],
                Decimal(str(order["quantity"])),
                Decimal(str(order["price"])),
            ) if self._engine else None
        if result:
            self._intel.trade("MainWindow",
                f"Manual order submitted: {side} {order['quantity']} {order['symbol']}", order)

    def _on_cancel_requested(self, symbol: str, order_id: str) -> None:
        if self._engine:
            ok = self._engine.manual_cancel(symbol, order_id)
            self._intel.trade("MainWindow",
                f"Order {'cancelled' if ok else 'cancel failed'}: {order_id}")

    # ── Toolbar actions ────────────────────────────────────────────────
    def _set_engine_mode(self, mode: str) -> None:
        if self._engine:
            from core.trading_engine import EngineMode
            self._engine.set_mode(EngineMode(mode))

    def _cancel_all_orders(self) -> None:
        reply = QMessageBox.question(
            self, "Cancel All Orders",
            "Cancel ALL open orders for all symbols?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self._order_manager:
                self._order_manager.cancel_all(self._current_symbol)
                self._intel.trade("MainWindow", "All orders cancelled by user")

    def _start_training(self) -> None:
        self.ml_widget._start_training()

    def _stop_training(self) -> None:
        self.ml_widget._stop_training()

    def _run_integrity_check(self) -> None:
        def _run():
            if self._cl:
                results = self._cl.integrity_checker.run_check(
                    ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"],
                    intervals=["1h","4h"],
                )
                QTimer.singleShot(0, lambda: self._show_integrity_results(results))
            else:
                self._intel.warning("MainWindow", "Continuous learner not available")
        threading.Thread(target=_run, daemon=True).start()

    def _show_integrity_results(self, results: dict) -> None:
        self.integrity_status_lbl.setText(
            f"Last check: {results.get('timestamp','')[:19]} | "
            f"{results.get('passed',0)} OK | {results.get('warnings',0)} warnings | {results.get('errors',0)} errors"
        )
        lines = []
        for d in results.get("details", []):
            status = d.get("status","")
            icon = "✅" if status == "OK" else "⚠️" if status == "WARNING" else "❌"
            lines.append(f"{icon} {d.get('symbol')}/{d.get('interval')} – {d.get('row_count')} rows – {', '.join(d.get('issues',[]) or ['OK'])}")
        self.integrity_log.setPlainText("\n".join(lines))

    def _reload_model(self) -> None:
        if self._predictor:
            ok = self._predictor.reload_model()
            self._intel.ml("MainWindow", f"Model reload {'succeeded' if ok else 'failed – no active model'}")

    def _generate_tax_report(self) -> None:
        if not self._tax_calc:
            return
        now = time.localtime()
        from tax.email_report import TaxEmailReporter
        reporter = TaxEmailReporter()
        path = reporter._generate_pdf(now.tm_year, now.tm_mon, self._tax_calc.monthly_summary(now.tm_year, now.tm_mon))
        self._intel.tax("MainWindow", f"Monthly tax report generated: {path}")

    def _generate_annual_tax(self) -> None:
        if not self._tax_calc:
            return
        from tax.uk_tax import UKTaxCalculator
        tax_year = UKTaxCalculator.current_tax_year()
        from tax.email_report import TaxEmailReporter
        path = TaxEmailReporter().generate_annual_report(tax_year)
        self._intel.tax("MainWindow", f"Annual CGT report generated: {path}")

    def _send_tax_email(self) -> None:
        self._intel.tax("MainWindow", "Sending monthly tax email…")
        now = time.localtime()
        from tax.email_report import TaxEmailReporter
        ok = TaxEmailReporter().generate_and_send_monthly(now.tm_year, now.tm_mon)
        self._intel.tax("MainWindow", f"Tax email {'sent' if ok else 'failed'}")

    def _start_api_server(self) -> None:
        from api.server import get_api_server
        srv = get_api_server()
        srv.start(
            engine=self._engine, portfolio=self._portfolio,
            predictor=self._predictor, order_manager=self._order_manager,
            tax_calc=self._tax_calc,
        )
        self._intel.api("MainWindow", f"REST API server started at {srv.base_url}")
        QMessageBox.information(self, "API Server", f"REST API running at:\n{srv.base_url}\n\nBrowse /health to verify.")

    def _show_api_docs(self) -> None:
        from api.server import get_api_server
        url = get_api_server().base_url + "/api/v1/status"
        self._intel.api("MainWindow", f"API docs: {url}")
        QMessageBox.information(self, "API Docs",
            f"Base URL: {get_api_server().base_url}\n\nKey Endpoints:\n"
            "  GET  /api/v1/status\n  GET  /api/v1/portfolio\n"
            "  GET  /api/v1/signals?symbol=BTCUSDT\n"
            "  POST /api/v1/order\n  GET  /api/v1/log\n"
            "  POST /api/v1/webhook/register\n\n"
            "Auth: Bearer <first 16 chars of Binance API key>")

    def _show_webhooks(self) -> None:
        from api.webhooks import get_webhook_manager
        hooks = get_webhook_manager().list_webhooks()
        msg = "Registered webhooks:\n\n" + ("\n".join(f"• {h['url']} [{','.join(h['events'])}]" for h in hooks) or "None")
        QMessageBox.information(self, "Webhooks", msg)

    def _open_settings(self) -> None:
        self._intel.system("MainWindow", "Settings panel opened")

    def _toggle_intel_log(self) -> None:
        self.intel_dock.setVisible(not self.intel_dock.isVisible())

    def _toggle_order_book(self) -> None:
        self.orderbook_widget.setVisible(not self.orderbook_widget.isVisible())

    def _toggle_ml_panel(self) -> None:
        self.ml_widget.setVisible(not self.ml_widget.isVisible())

    def _show_about(self) -> None:
        QMessageBox.about(self, "About BinanceML Pro",
            "<b>BinanceML Pro</b><br/>"
            "Version 1.0.0<br/><br/>"
            "Professional AI-powered crypto trading platform.<br/>"
            "• LSTM + Transformer ML models<br/>"
            "• UK HMRC CGT tax reporting<br/>"
            "• Continuous learning engine<br/>"
            "• REST API & webhooks<br/>"
            "• Data integrity checks every 25 minutes<br/><br/>"
            "Optimised for Apple Silicon (Mac Mini M4).")

    # ── Background refresh ─────────────────────────────────────────────
    def _refresh_orders(self) -> None:
        if self._order_manager:
            orders = self._order_manager.get_open_orders()
            self.trading_panel.update_active_orders(orders)

    def _update_clock(self) -> None:
        self.sb_time_lbl.setText(time.strftime("  %H:%M:%S  %Z  |  %d %b %Y"))

    def _update_stats(self) -> None:
        from utils.threading_manager import get_thread_manager
        stats = get_thread_manager().system_stats()
        self.cpu_lbl.setText(f"  CPU: {stats['cpu_pct']:.0f}%")
        self.mem_lbl.setText(f"  MEM: {stats['mem_pct']:.0f}%  ({stats['mem_used_gb']:.1f}/{stats['mem_total_gb']:.0f}GB)")

    # ── Close event ────────────────────────────────────────────────────
    def closeEvent(self, event) -> None:
        reply = QMessageBox.question(
            self, "Exit",
            "Stop trading engine and exit?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self._engine:
                self._engine.stop()
            if self._predictor:
                self._predictor.stop()
            if self._cl:
                self._cl.stop()
            self._intel.system("MainWindow", "Application closed.")
            event.accept()
        else:
            event.ignore()
