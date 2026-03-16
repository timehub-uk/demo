"""
BinanceML Pro – Futuristic Trading Desk Main Window

Layout:
  ┌─────────────────────────────────────────────────────────────────────┐
  │  HEADER BAR:  [Logo] [Brand] [Ticker Strip]  [Health dots] [Time]  │
  ├──────┬──────────────────────────────────────────────────────────────┤
  │      │                                                               │
  │ NAV  │              STACKED CONTENT PANELS                          │
  │ SIDE │  0: Trading      1: AutoTrader   2: ML         3: Risk       │
  │ BAR  │  4: Backtest     5: Journal      6: Strategy   7: Connections│
  │      │  8: Settings     9: Help        10: Simulation 11: Reports   │
  │      │ 12: MarketWatch 13: ML Tools                                 │
  │      │                                                               │
  │      ├──────────────────────────────────────────────────────────────┤
  │      │  INTEL LOG dock (collapsible)                                 │
  └──────┴──────────────────────────────────────────────────────────────┘
  STATUS BAR: Mode | AT State | Trades | P&L | API | DB | Redis | CPU

Nav icons:  hover 5 s → tooltip    hover 10 s → contextual help popup
"""

from __future__ import annotations

import threading
import time

from PyQt6.QtCore import Qt, QTimer, QSize, QPoint, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QToolButton, QFrame, QSplitter, QSizePolicy, QStackedWidget,
    QDockWidget, QMessageBox, QComboBox, QStatusBar, QMenu,
    QTabWidget, QInputDialog,
)

from loguru import logger

from config import get_settings
from utils.logger import get_intel_logger
from ui.styles import (
    ACCENT, ACCENT2, GREEN, RED, YELLOW, PURPLE,
    BG0, BG1, BG2, BG3, BG4, BG5, BORDER, BORDER2, FG0, FG1, FG2, GLOW,
)
from ui.icons import svg_icon, svg_pixmap


# ══════════════════════════════════════════════════════════════════════════════
# PANEL HELP TEXT  (shown after 10-second hover)
# ══════════════════════════════════════════════════════════════════════════════

_PANEL_HELP: dict[int, tuple[str, str]] = {
    0: ("Trading Panel",
        "Manual order entry, active orders, trade history, portfolio and P&L.\n\n"
        "• Multi-tab charts: open any USDT pair in its own tab\n"
        "• Chart styles: Candlestick · OHLC · Heikin-Ashi · Line · Area\n"
        "• Overlays: EMA 9/20/50/200 · SMA · BB · VWAP ±σ · Ichimoku\n"
        "• Event annotations: CASCADE / WHALE / FUNDING / LEAD-LAG markers on chart\n"
        "• Session bands: Asian · London · NY coloured background regions\n"
        "• Auto S/R: swing-high/low cluster detection → resistance & support lines\n"
        "• Pair watermark: faint bold pair name centred on the price chart (WMARK)\n"
        "• Sub-panels: Volume · OBV · RSI · MACD · Stochastic · ATR · ADX\n"
        "• AI Forecast cone: BUY/SELL projection with accuracy badge (ACC)\n"
        "• Trade markers: entry/exit squares with hover P&L tooltip\n"
        "• ⎙ PDF export: white-background, print-optimised chart PDF\n"
        "• Order entry: LIMIT / MARKET / STOP / OCO with SL+TP\n"
        "• Active Orders table with one-click cancel\n"
        "• Portfolio tab shows free/locked balances in USD/GBP"),
    1: ("AutoTrader",
        "Fully autonomous scan → aim → enter → monitor → exit cycle.\n\n"
        "• SEMI_AUTO: recommendation shown, press Take Aim to fire\n"
        "• FULL_AUTO: executes automatically when confidence ≥ threshold\n"
        "• Top-5 Profit and Top-5 R:R tables from market scan\n"
        "• Active Trade panel with live P&L vs SL/TP levels\n"
        "• Cooldown 15 min after stop-loss, circuit breaker guard\n"
        "• Ping-Pong range trader, Strategy Manager, Arbitrage detector\n"
        "• Alert log for all system-generated events\n"
        "• ML signal scanners → see 'ML Tools' panel (Ctrl+Shift+M)"),
    2: ("ML Training",
        "LSTM + Transformer model training, progress monitoring and live signals.\n\n"
        "• Start/Stop 48-hour full training session  (Ctrl+T / Ctrl+Shift+T)\n"
        "• 3-phase progress: archive download → gap-fill → per-token fine-tuning\n"
        "• Continuous Learner auto-retrains every 24 hours\n"
        "• Loss and accuracy charts updated in real time\n"
        "• Live inference signal stream with confidence scores\n"
        "• Whale activity and sentiment feeds\n"
        "• See 'ML Tools' panel (Ctrl+Shift+M) for scanners and detectors"),
    3: ("Risk Dashboard",
        "Dynamic risk and portfolio analytics.\n\n"
        "• Circuit breaker: fires at −5% daily drawdown\n"
        "• Kelly-based position sizing adapts to win rate\n"
        "• Regime detector: Bull / Bear / Ranging / Volatile\n"
        "• Monte Carlo projection of future portfolio paths\n"
        "• Walk-forward validation of ML model performance"),
    4: ("Backtesting Engine",
        "Historical strategy backtesting with full performance analysis.\n\n"
        "• Select symbol, interval, date range and initial capital\n"
        "• Run ML model or custom rule-based strategies\n"
        "• Equity curve chart with drawdown overlay\n"
        "• Full trade log with entry/exit prices and P&L\n"
        "• PDF export of backtest results"),
    5: ("Trade Journal",
        "Audit trail and performance analysis of all trades.\n\n"
        "• Full history of every trade with context and reasoning\n"
        "• Win rate, average R:R, expectancy statistics\n"
        "• P&L breakdown by symbol, strategy and time period\n"
        "• Signal accuracy scores for each ML source\n"
        "• Export journal to CSV for external analysis"),
    6: ("Strategy Builder",
        "Visual rule-based strategy editor with integrated backtesting.\n\n"
        "• Drag-and-drop entry and exit condition builder\n"
        "• Supported indicators: RSI, MACD, EMA, BB, ATR, ML signals\n"
        "• Configure position sizing and SL/TP rules\n"
        "• Run backtest directly from the builder\n"
        "• Save and load named strategy profiles"),
    7: ("Connections",
        "Live health monitoring for all external services.\n\n"
        "• Binance REST API + WebSocket stream\n"
        "• PostgreSQL with connection latency\n"
        "• Redis cache ping latency\n"
        "• Telegram bot and REST API server\n"
        "• Auto-checks every 30 s, manual Check All button"),
    8: ("Settings",
        "Full system configuration.\n\n"
        "• Binance API keys, testnet toggle\n"
        "• ML hyperparameters: LSTM layers, learning rate, etc.\n"
        "• Trading risk limits and execution mode\n"
        "• UK CGT tax settings and email reports\n"
        "• UI theme, font size, accent colour"),
    9: ("Help",
        "Documentation and keyboard shortcuts.\n\n"
        "• Complete keyboard shortcut reference table\n"
        "• Architecture overview and data flow\n"
        "• Risk management rules and defaults\n"
        "• UK HMRC CGT tax reporting documentation\n"
        "• About BinanceML Pro"),
    10: ("Simulation",
        "Live Simulation Twin, Strategy Mutation Lab & Safety Scanner.\n\n"
        "• Live Simulation Twin: shadow every decision in parallel\n"
        "• Strategy Mutation Lab: automated genetic evolution of strategies\n"
        "• Safety Scanner: contract analysis, honeypot, rug-pull scoring\n"
        "• Drift detection: alert when model accuracy deviates from baseline\n"
        "• Shortcut: Ctrl+Shift+S"),
    11: ("Reports",
        "Comprehensive performance reports across every time horizon.\n\n"
        "• Daily:     today's P&L, trade log, signal attribution, risk status\n"
        "• Weekly:    7-day bar chart, day-by-day table, win-rate trend\n"
        "• Monthly:   weekly breakdown, UK CGT tax estimate, CSV / email export\n"
        "• Quarterly: Q1–Q4 bar chart, Sharpe estimate, month-by-month table\n"
        "• Ad-Hoc:    custom date range, full/P&L/attribution/forecast/risk/tax\n"
        "• Shortcut: F2"),
    13: ("ML Tools",
        "ML-powered market analysis tools and signal scanners.  Shortcut: Ctrl+Shift+M\n\n"
        "• ML Central Command — unified ranked signal pipeline from all ML sources\n"
        "• Trends — multi-timeframe trend strength and direction\n"
        "• Pairs — 1000+ pair ranking by ML tradability score\n"
        "• Accumulation — stealth accumulation stage detector (NONE/WATCH/ALERT/STRONG)\n"
        "• Liquidity — order-book depth grades per symbol\n"
        "• Breakouts — 4-stage volume breakout tracker (LAUNCH→PUMP→CONSOLIDATION→BREAKOUT)\n"
        "• Gaps — price gap detection with mean-reversion signals\n"
        "• Candles — large rapid candle expansion alerts\n"
        "• Icebergs — hidden order detection (ICEBERG_PARTS=100)"),
    12: ("Market Watch",
        "Unified real-time market surveillance dashboard.  Shortcut: Ctrl+Shift+W\n\n"
        "Toggle bar — each service can be enabled / disabled independently:\n"
        "• Funding Rate Monitor — polls perpetual futures funding rates every 5 min;\n"
        "  fires alert when rate exceeds ±0.10 % (extreme funding)\n"
        "• Order Flow (OFI) — tracks buy/sell aggressor ratio and Order Flow Imbalance\n"
        "  per symbol from aggTrade WebSocket; alerts at ≥72 % or ≤28 % (smart money)\n"
        "• Correlation Engine — lead/lag detector for BTC→ETH/BNB/SOL/XRP and ETH→BNB;\n"
        "  adaptive Welford thresholds; fires when leader moves but follower hasn't reacted\n"
        "• Cascade Detector — liquidation cascade detector; adaptive ML thresholds learn\n"
        "  normal price volatility and volume-spike distributions per symbol\n\n"
        "Tabs:\n"
        "• Volume Alerts — all alert types in one table (whale, cascade, funding, lead-lag)\n"
        "• ML Watch — live signal feed + per-symbol model confidence summary\n"
        "• Order Flow — aggressor ratio + OFI table for every subscribed symbol\n"
        "• Portfolio Heatmap — P&L colour tiles sized by position USD value\n"
        "• Regime & Cascade — market regime per symbol + liquidation event feed\n"
        "• Kill Switch — emergency halt: Cancel All / Pause AutoTrader / Paper Mode"),
}


# ══════════════════════════════════════════════════════════════════════════════
# NAV BUTTON
# ══════════════════════════════════════════════════════════════════════════════

class NavButton(QToolButton):
    """
    Sidebar navigation button — icon centred on top, label text below.
    • Mouse enter + 5 s  → QToolTip with panel title
    • Mouse enter + 10 s → contextual help QMessageBox
    • Mouse leave        → cancel both timers
    • set_alert(True)    → icon flashes RED to signal an alert
    • set_nav_disabled(True) → greyed-out inactive appearance
    """

    clicked_index = pyqtSignal(int)

    def __init__(self, index: int, icon_name: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self._index     = index
        self._icon_name = icon_name
        self._label     = label
        self._active    = False
        self._alerted   = False
        self._disabled_nav = False
        self._flash_on  = False

        self.setObjectName("nav_btn")
        self.setFixedHeight(70)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setText(label)
        self._set_icon(FG2)
        self._apply_style(False)

        # 5-second tooltip timer
        self._tip_timer = QTimer(self)
        self._tip_timer.setSingleShot(True)
        self._tip_timer.setInterval(5000)
        self._tip_timer.timeout.connect(self._show_tooltip)

        # 10-second popup timer
        self._pop_timer = QTimer(self)
        self._pop_timer.setSingleShot(True)
        self._pop_timer.setInterval(10000)
        self._pop_timer.timeout.connect(self._show_popup)

        # Alert flash timer — toggles icon colour every 600 ms
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(600)
        self._flash_timer.timeout.connect(self._on_flash_tick)

        self.clicked.connect(lambda: self.clicked_index.emit(self._index))

    def _set_icon(self, color: str) -> None:
        self.setIcon(svg_icon(self._icon_name, color, 24))
        self.setIconSize(QSize(24, 24))

    def _apply_style(self, active: bool) -> None:
        if self._disabled_nav:
            col     = FG2
            bg      = "transparent"
            top_bar = "border-top:2px solid transparent;"
            weight  = "400"
        elif self._alerted:
            col     = RED
            bg      = f"{RED}18"
            top_bar = f"border-top:2px solid {RED};"
            weight  = "700"
        else:
            col     = ACCENT if active else FG1
            bg      = BG2    if active else "transparent"
            top_bar = (f"border-top:2px solid {ACCENT};"
                       if active else "border-top:2px solid transparent;")
            weight  = "700" if active else "500"
        self.setStyleSheet(f"""
            QToolButton {{
                background:{bg}; color:{col};
                border:none; {top_bar}
                border-radius:0;
                font-size:11px; font-weight:{weight};
                padding:8px 2px 5px 2px;
            }}
            QToolButton:hover {{
                background:{BG3}; color:{FG0};
                border-top:2px solid {BORDER2};
            }}
        """)

    def set_active(self, active: bool) -> None:
        self._active = active
        if not self._alerted:
            self._set_icon(ACCENT if active else (BG4 if self._disabled_nav else FG2))
        self._apply_style(active)

    def set_alert(self, alerted: bool) -> None:
        """Flash the icon red while alerted; restore normal state when cleared."""
        self._alerted = alerted
        if alerted:
            self._flash_timer.start()
        else:
            self._flash_timer.stop()
            self._flash_on = False
            self._set_icon(ACCENT if self._active else (BG4 if self._disabled_nav else FG2))
            self._apply_style(self._active)

    def set_nav_disabled(self, disabled: bool) -> None:
        """Grey out the button to indicate the underlying service is unavailable."""
        self._disabled_nav = disabled
        icon_col = BG4 if disabled else (ACCENT if self._active else FG2)
        self._set_icon(icon_col)
        self._apply_style(self._active)

    def _on_flash_tick(self) -> None:
        self._flash_on = not self._flash_on
        self._set_icon(RED if self._flash_on else FG2)
        self._apply_style(self._active)

    def enterEvent(self, event) -> None:
        if not self._active and not self._alerted:
            self._set_icon(FG1)
        self._tip_timer.start()
        self._pop_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self._active and not self._alerted:
            self._set_icon(BG4 if self._disabled_nav else FG2)
        self._tip_timer.stop()
        self._pop_timer.stop()
        super().leaveEvent(event)

    def _show_tooltip(self) -> None:
        from PyQt6.QtWidgets import QToolTip
        title, _ = _PANEL_HELP.get(self._index, (self._label, ""))
        pos = self.mapToGlobal(QPoint(self.width() + 8, self.height() // 2))
        QToolTip.showText(pos, f"<b>{title}</b>", self)

    def _show_popup(self) -> None:
        title, body = _PANEL_HELP.get(self._index, (self._label, ""))
        dlg = QMessageBox(self.window())
        dlg.setWindowTitle(f"Help – {title}")
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.setText(f"<b style='color:{ACCENT};font-size:14px;'>{title}</b>")
        dlg.setInformativeText(body.replace("\n", "<br>"))
        dlg.setStyleSheet(f"QMessageBox {{ background:{BG3}; }} QLabel {{ color:{FG0}; }}")
        dlg.exec()


# ══════════════════════════════════════════════════════════════════════════════
# HEADER BAR
# ══════════════════════════════════════════════════════════════════════════════

class HeaderBar(QFrame):
    """☰ Toggle | Logo | Brand | Ticker strip | Health dots | Clock."""

    symbol_changed = pyqtSignal(str)
    nav_toggle     = pyqtSignal()    # emitted when hamburger is clicked

    def __init__(self, symbols: list[str], parent=None) -> None:
        super().__init__(parent)
        self._symbols = symbols
        self.setFixedHeight(52)
        self.setStyleSheet(
            f"HeaderBar {{ background:{BG0}; border-bottom:1px solid {BORDER2}; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 12, 4)
        layout.setSpacing(0)

        # Hamburger — slides the nav sidebar in/out
        self._ham_btn = QPushButton("☰")
        self._ham_btn.setFixedSize(36, 36)
        self._ham_btn.setToolTip("Toggle navigation sidebar  (Ctrl+\\)")
        self._ham_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {FG1};
                border: none; border-radius: 4px;
                font-size: 16px; font-weight: 700;
            }}
            QPushButton:hover  {{ background: {BG3}; color: {FG0}; }}
            QPushButton:pressed {{ background: {BG4}; }}
        """)
        self._ham_btn.clicked.connect(self.nav_toggle)
        layout.addWidget(self._ham_btn)

        layout.addSpacing(6)

        # Logo
        logo = QLabel()
        logo.setPixmap(svg_pixmap("logo", ACCENT, 28))
        layout.addWidget(logo)

        # Brand
        brand = QLabel(
            f"  BINANCEML <span style='color:{ACCENT2};'>PRO</span>"
        )
        brand.setTextFormat(Qt.TextFormat.RichText)
        brand.setStyleSheet(
            f"color:{FG0}; font-size:14px; font-weight:700; letter-spacing:3px;"
        )
        layout.addWidget(brand)

        layout.addWidget(_vsep())

        # Ticker labels
        self._tick_labels: dict[str, QLabel] = {}
        for sym in symbols:
            lbl = QLabel(f"{sym.replace('USDT','')}  —")
            lbl.setStyleSheet(
                f"color:{FG1}; font-size:11px; padding:0 10px; font-family:monospace;"
            )
            lbl.setTextFormat(Qt.TextFormat.RichText)
            sym_copy = sym
            lbl.mousePressEvent = lambda _e, s=sym_copy: self.symbol_changed.emit(s)
            layout.addWidget(lbl)
            self._tick_labels[sym] = lbl

        layout.addStretch()
        layout.addWidget(_vsep())

        # Health dots
        self.health_dots: dict[str, QLabel] = {}
        for svc, tip in [("api","Binance API"),("db","PostgreSQL"),
                         ("redis","Redis"),("tg","Telegram")]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{FG2}; font-size:14px; padding:0 4px;")
            dot.setToolTip(tip)
            layout.addWidget(dot)
            self.health_dots[svc] = dot

        layout.addWidget(_vsep())

        # Clock
        self.clock_lbl = QLabel("--:--:--")
        self.clock_lbl.setStyleSheet(
            f"color:{ACCENT}; font-size:13px; font-weight:700; "
            f"font-family:monospace; padding:0 14px; letter-spacing:1px;"
        )
        layout.addWidget(self.clock_lbl)

        QTimer(self, interval=2000, timeout=self._refresh_tickers).start()
        QTimer(self, interval=1000, timeout=self._update_clock).start()

    def _refresh_tickers(self) -> None:
        try:
            from db.redis_client import RedisClient
            rc = RedisClient()
            for sym, lbl in self._tick_labels.items():
                d = rc.get_ticker(sym)
                if d:
                    price = float(d.get("price", 0))
                    chg   = float(d.get("change_pct", 0))
                    col   = GREEN if chg >= 0 else RED
                    sign  = "+" if chg >= 0 else ""
                    short = sym.replace("USDT", "")
                    lbl.setText(
                        f"{short}  "
                        f"<b style='color:{FG0};'>{price:,.4f}</b>"
                        f"  <span style='color:{col};'>{sign}{chg:.2f}%</span>"
                    )
        except Exception:
            pass

    def _update_clock(self) -> None:
        self.clock_lbl.setText(time.strftime("%H:%M:%S"))

    def set_health(self, svc: str, ok: bool) -> None:
        dot = self.health_dots.get(svc)
        if dot:
            dot.setStyleSheet(
                f"color:{GREEN if ok else RED}; font-size:14px; padding:0 4px;"
            )


# ══════════════════════════════════════════════════════════════════════════════
# NAV SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

_NAV_ITEMS = [
    (0,  "trading",      "Trading"),
    (1,  "autotrader",   "AutoTrader"),
    (2,  "ml",           "ML Train"),
    (3,  "risk",         "Risk"),
    (4,  "backtest",     "Backtest"),
    (5,  "journal",      "Journal"),
    (6,  "strategy",     "Strategy"),
    (7,  "connections",  "Connections"),
    (8,  "settings",     "Settings"),
    (9,  "help",         "Help"),
    (10, "simulation",   "Simulation"),
    (11, "reports",      "Reports"),
    (12, "scan",         "Market Watch"),
    (13, "ml",           "ML Tools"),
]


class NavSidebar(QFrame):
    page_requested = pyqtSignal(int)

    _WIDTH = 92   # px — icon centred above text; enough for longest label

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Use min/max instead of setFixedWidth so we can animate the width
        self.setMinimumWidth(0)
        self.setMaximumWidth(self._WIDTH)
        self.setStyleSheet(
            f"NavSidebar {{ background:{BG0}; border-right:1px solid {BORDER}; }}"
        )

        # Build buttons in a plain container so they can scroll
        container = QWidget()
        container.setStyleSheet(f"background:{BG0};")
        btn_layout = QVBoxLayout(container)
        btn_layout.setContentsMargins(0, 8, 0, 8)
        btn_layout.setSpacing(1)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._buttons: list[NavButton] = []
        for idx, icon, label in _NAV_ITEMS:
            btn = NavButton(idx, icon, label)
            btn.clicked_index.connect(self._on_nav)
            btn_layout.addWidget(btn)   # full width — no AlignHCenter
            self._buttons.append(btn)

        btn_layout.addStretch()

        # Wrap in a scroll area so all buttons stay reachable on small screens
        from PyQt6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background:{BG1}; width:4px; }}"
            f"QScrollBar::handle:vertical {{ background:{BORDER2}; border-radius:2px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll)

    def _on_nav(self, index: int) -> None:
        for btn in self._buttons:
            btn.set_active(btn._index == index)
        self.page_requested.emit(index)

    def set_active(self, index: int) -> None:
        for btn in self._buttons:
            btn.set_active(btn._index == index)

    def set_alert(self, page_index: int, alerted: bool) -> None:
        """Flash the nav button for the given page when an alert is active."""
        for btn in self._buttons:
            if btn._index == page_index:
                btn.set_alert(alerted)
                break

    def set_nav_disabled(self, page_index: int, disabled: bool) -> None:
        """Grey out a nav button when its service is unavailable."""
        for btn in self._buttons:
            if btn._index == page_index:
                btn.set_nav_disabled(disabled)
                break


# ══════════════════════════════════════════════════════════════════════════════
# MULTI-CHART PANEL  (tabbed, multi-pair, overlay selector)
# ══════════════════════════════════════════════════════════════════════════════

class MultiChartPanel(QWidget):
    """
    Tabbed chart panel.
    • Each tab = one symbol's ChartWidget
    • Overlay pulldown menu to select/deselect indicators
    • Ctrl++ to add tab, Ctrl+W to close current, tabs are movable
    """

    symbol_changed = pyqtSignal(str)

    _OVERLAYS = [
        "EMA 9", "EMA 20", "EMA 50", "EMA 200",
        "SMA 20", "SMA 50", "SMA 200",
        "Bollinger Bands", "VWAP",
        "Volume Profile", "RSI", "MACD",
        "ATR", "Stochastic", "Ichimoku Cloud",
    ]

    def __init__(self, default_symbols: list[str], forecast_tracker=None, parent=None) -> None:
        super().__init__(parent)
        self._default_symbols = default_symbols
        self._forecast_tracker = forecast_tracker
        self._chart_widgets: dict[str, QWidget] = {}
        self._active_overlays: set[str] = {"EMA 20", "EMA 50", "Volume Profile"}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar row ───────────────────────────────────────────────
        ctrl = QFrame()
        ctrl.setFixedHeight(42)
        ctrl.setStyleSheet(
            f"background:{BG0}; border-bottom:1px solid {BORDER};"
        )
        ctl = QHBoxLayout(ctrl)
        ctl.setContentsMargins(10, 0, 10, 0)
        ctl.setSpacing(10)

        # Interval
        lbl_interval = QLabel("Interval:")
        lbl_interval.setStyleSheet(f"color:{FG1}; font-size:12px;")
        ctl.addWidget(lbl_interval)
        self.interval_combo = QComboBox()
        self.interval_combo.setFixedWidth(76)
        for iv in ["1m","3m","5m","15m","30m","1h","4h","1d","1w"]:
            self.interval_combo.addItem(iv)
        self.interval_combo.setCurrentText("1h")
        self.interval_combo.currentTextChanged.connect(self._on_interval_changed)
        ctl.addWidget(self.interval_combo)

        ctl.addWidget(_vsep())

        # Overlay pulldown
        lbl_overlays = QLabel("Overlays:")
        lbl_overlays.setStyleSheet(f"color:{FG1}; font-size:12px;")
        ctl.addWidget(lbl_overlays)
        self.overlay_btn = QPushButton("EMA20, EMA50, Volume ▾")
        self.overlay_btn.setFixedWidth(190)
        self.overlay_btn.setFixedHeight(30)
        self.overlay_btn.setStyleSheet(f"""
            QPushButton {{
                background:{BG4}; color:{FG1}; border:1px solid {BORDER2};
                border-radius:4px; font-size:12px; padding:0 10px; text-align:left;
            }}
            QPushButton:hover {{ color:{ACCENT}; border-color:{ACCENT}; }}
        """)
        self.overlay_btn.clicked.connect(self._show_overlay_menu)
        ctl.addWidget(self.overlay_btn)

        ctl.addWidget(_vsep())

        # Add tab button
        add_btn = QPushButton()
        add_btn.setIcon(svg_icon("scan", ACCENT, 14))
        add_btn.setIconSize(QSize(14, 14))
        add_btn.setFixedSize(30, 30)
        add_btn.setToolTip("Add chart tab  (Ctrl++)")
        add_btn.setStyleSheet(
            f"background:{BG4}; border:1px solid {BORDER}; border-radius:4px;"
        )
        add_btn.clicked.connect(self._prompt_add_tab)
        ctl.addWidget(add_btn)

        ctl.addWidget(_vsep())

        # Fullscreen / pop-out button
        fs_btn = QPushButton("⛶")
        fs_btn.setFixedSize(30, 30)
        fs_btn.setToolTip("Pop chart out to fullscreen  (double-click tab title)")
        fs_btn.setStyleSheet(
            f"background:{BG4}; border:1px solid {BORDER}; border-radius:4px;"
            f" color:{FG1}; font-size:15px;"
        )
        fs_btn.clicked.connect(self._open_fullscreen)
        ctl.addWidget(fs_btn)

        ctl.addStretch()

        # Current symbol label
        self.sym_lbl = QLabel("BTCUSDT")
        self.sym_lbl.setStyleSheet(
            f"color:{ACCENT}; font-weight:700; font-size:14px; "
            f"font-family:monospace; padding-right:10px;"
        )
        ctl.addWidget(self.sym_lbl)

        layout.addWidget(ctrl)

        # ── Chart tabs ────────────────────────────────────────────────
        self.chart_tabs = QTabWidget()
        self.chart_tabs.setTabsClosable(True)
        self.chart_tabs.setMovable(True)
        self.chart_tabs.tabCloseRequested.connect(self._close_tab)
        self.chart_tabs.currentChanged.connect(self._on_tab_changed)
        # Double-click on any chart tab title → fullscreen pop-out
        self.chart_tabs.tabBar().tabBarDoubleClicked.connect(
            lambda _idx: self._open_fullscreen()
        )
        layout.addWidget(self.chart_tabs, 1)

        # Load first 4 default symbols
        for sym in self._default_symbols[:4]:
            self._add_chart_tab(sym)

    def _add_chart_tab(self, symbol: str) -> None:
        # Switch to existing tab if already open
        for i in range(self.chart_tabs.count()):
            if self.chart_tabs.tabText(i) == symbol:
                self.chart_tabs.setCurrentIndex(i)
                return

        try:
            from ui.chart_widget import ChartWidget
            cw = ChartWidget(forecast_tracker=self._forecast_tracker)
            cw.set_symbol(symbol)
            if hasattr(cw, "set_overlays"):
                cw.set_overlays(list(self._active_overlays))
        except Exception:
            cw = QLabel(f"\n\n  {symbol}  chart\n")
            cw.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cw.setStyleSheet(f"color:{FG2}; font-size:18px;")

        self._chart_widgets[symbol] = cw
        idx = self.chart_tabs.addTab(cw, symbol)
        self.chart_tabs.setCurrentIndex(idx)

    def _prompt_add_tab(self) -> None:
        sym, ok = QInputDialog.getText(
            self, "Add Chart", "Symbol (e.g. ETHUSDT):"
        )
        if ok and sym.strip():
            self._add_chart_tab(sym.strip().upper())

    def _close_tab(self, index: int) -> None:
        if self.chart_tabs.count() <= 1:
            return
        sym = self.chart_tabs.tabText(index)
        self._chart_widgets.pop(sym, None)
        self.chart_tabs.removeTab(index)

    def _on_tab_changed(self, index: int) -> None:
        if index < 0:
            return
        sym = self.chart_tabs.tabText(index)
        self.sym_lbl.setText(sym)
        self.symbol_changed.emit(sym)

    def _on_interval_changed(self, interval: str) -> None:
        for cw in self._chart_widgets.values():
            if hasattr(cw, "set_interval"):
                cw.set_interval(interval)

    def _show_overlay_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background:{BG3}; border:1px solid {BORDER2};
                border-radius:8px; padding:6px;
            }}
            QMenu::item {{
                padding:6px 20px; border-radius:4px; margin:1px;
                font-size:11px; color:{FG0};
            }}
            QMenu::item:selected {{ background:{GLOW}; color:{ACCENT}; }}
        """)
        for overlay in self._OVERLAYS:
            act = menu.addAction(overlay)
            act.setCheckable(True)
            act.setChecked(overlay in self._active_overlays)
            act.triggered.connect(
                lambda checked, o=overlay: self._toggle_overlay(o, checked)
            )
        menu.addSeparator()
        menu.addAction("Clear All").triggered.connect(self._clear_overlays)

        menu.exec(self.overlay_btn.mapToGlobal(
            QPoint(0, self.overlay_btn.height())
        ))
        self._update_overlay_label()

    def _toggle_overlay(self, overlay: str, checked: bool) -> None:
        if checked:
            self._active_overlays.add(overlay)
        else:
            self._active_overlays.discard(overlay)
        self._push_overlays()

    def _clear_overlays(self) -> None:
        self._active_overlays.clear()
        self._push_overlays()
        self._update_overlay_label()

    def _push_overlays(self) -> None:
        for cw in self._chart_widgets.values():
            if hasattr(cw, "set_overlays"):
                cw.set_overlays(list(self._active_overlays))

    def _update_overlay_label(self) -> None:
        n = len(self._active_overlays)
        if n == 0:
            self.overlay_btn.setText("No Overlays ▾")
        elif n <= 2:
            self.overlay_btn.setText(", ".join(sorted(self._active_overlays)) + " ▾")
        else:
            self.overlay_btn.setText(f"{n} Overlays Active ▾")

    def current_symbol(self) -> str:
        idx = self.chart_tabs.currentIndex()
        if idx >= 0:
            return self.chart_tabs.tabText(idx)
        return self._default_symbols[0] if self._default_symbols else "BTCUSDT"

    def set_symbol(self, symbol: str) -> None:
        self._add_chart_tab(symbol)

    def _open_fullscreen(self) -> None:
        """Pop the current chart out into a maximised floating window."""
        from PyQt6.QtWidgets import QDialog
        sym = self.current_symbol()
        dlg = QDialog(self.window(), Qt.WindowType.Window)
        dlg.setWindowTitle(f"Chart – {sym}  (close to return)")
        dlg.setStyleSheet(f"background:{BG0};")
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setContentsMargins(0, 0, 0, 0)
        inner = MultiChartPanel(self._default_symbols, self._forecast_tracker)
        # Switch to the same symbol that is currently visible
        inner.set_symbol(sym)
        dlg_layout.addWidget(inner)
        dlg.showMaximized()
        dlg.exec()


# ══════════════════════════════════════════════════════════════════════════════
# DOCK HELPERS — custom title bar, TradeDock, style
# ══════════════════════════════════════════════════════════════════════════════

_INNER_WIN_STYLE = f"""
QMainWindow::separator {{
    background: {BORDER}; width: 4px; height: 4px;
}}
QMainWindow::separator:hover {{
    background: {ACCENT};
}}
QDockWidget {{
    color: {FG1}; font-size: 11px; font-weight: 600;
}}
"""

def _dock_btn(symbol: str, tip: str) -> QPushButton:
    btn = QPushButton(symbol)
    btn.setToolTip(tip)
    btn.setFixedSize(24, 24)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: transparent; color: {FG1};
            border: none; border-radius: 4px;
            font-size: 12px; padding: 0;
        }}
        QPushButton:hover  {{ background: {BG4}; color: {FG0}; }}
        QPushButton:pressed {{ background: {BG5}; }}
    """)
    return btn


class DockTitleBar(QWidget):
    """
    Custom dock title bar: ⠿ grip · title · ⧉ float · ▼ minimise · ✕ close.
    Double-click toggles floating.
    """

    minimize_requested = pyqtSignal()

    def __init__(self, title: str, dock: "TradeDock") -> None:
        super().__init__(dock)
        self._dock = dock

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 3, 6, 3)
        lay.setSpacing(6)

        grip = QLabel("⠿")
        grip.setStyleSheet(f"color:{BORDER2}; font-size:16px;")
        lay.addWidget(grip)

        self._lbl = QLabel(title)
        self._lbl.setStyleSheet(
            f"color:{FG0}; font-size:12px; font-weight:600; letter-spacing:0.4px;"
        )
        lay.addWidget(self._lbl, 1)

        btn_float = _dock_btn("⧉", "Float / re-dock  (or double-click title)")
        btn_float.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        lay.addWidget(btn_float)

        btn_min = _dock_btn("▼", "Minimise to bottom tray")
        btn_min.clicked.connect(self.minimize_requested)
        lay.addWidget(btn_min)

        btn_close = _dock_btn("✕", "Close  (restore via View ▸ Panels menu)")
        btn_close.clicked.connect(dock.close)
        lay.addWidget(btn_close)

        self.setFixedHeight(32)
        self.setStyleSheet(
            f"DockTitleBar {{ background:{BG2}; border-bottom:1px solid {BORDER2}; }}"
        )

    def set_title(self, text: str) -> None:
        self._lbl.setText(text)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._dock.setFloating(not self._dock.isFloating())
        super().mouseDoubleClickEvent(event)


class TradeDock(QDockWidget):
    """
    QDockWidget with a custom dark title bar.
    • Drag title bar  → move / re-dock
    • ⧉ button or double-click → float / re-dock
    • ▼ button        → minimise to bottom tray (emits minimize_requested)
    • ✕ button        → close (hide)
    • Resize           → drag the splitter separator between docks
    """

    minimize_requested = pyqtSignal(object)   # emits self

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(title, parent)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._title_bar = DockTitleBar(title, self)
        self._title_bar.minimize_requested.connect(
            lambda: self.minimize_requested.emit(self)
        )
        self.setTitleBarWidget(self._title_bar)

    def set_title(self, text: str) -> None:
        self._title_bar.set_title(text)
        self.setWindowTitle(text)


# ══════════════════════════════════════════════════════════════════════════════
# TRADING PAGE
# ══════════════════════════════════════════════════════════════════════════════

class TradingPage(QWidget):
    order_submitted  = pyqtSignal(dict)
    cancel_requested = pyqtSignal(str, str)
    symbol_changed   = pyqtSignal(str)

    def __init__(self, default_symbols: list[str], forecast_tracker=None, parent=None) -> None:
        super().__init__(parent)
        self._default_symbols = default_symbols
        self._forecast_tracker = forecast_tracker
        self._setup_ui()

    # ── build ──────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Inner QMainWindow — hosts chart + side docks ───────────────
        self._inner = QMainWindow()
        self._inner.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks |
            QMainWindow.DockOption.AllowTabbedDocks |
            QMainWindow.DockOption.AllowNestedDocks |
            QMainWindow.DockOption.GroupedDragging
        )
        self._inner.setStyleSheet(_INNER_WIN_STYLE)
        layout.addWidget(self._inner)

        # ── Central widget: full-width chart (always > 50 %) ──────────
        self.chart_panel = MultiChartPanel(
            self._default_symbols, forecast_tracker=self._forecast_tracker
        )
        self.chart_panel.symbol_changed.connect(self.symbol_changed)
        self._inner.setCentralWidget(self.chart_panel)

        # ── Right dock: Order Book ─────────────────────────────────────
        from ui.orderbook_widget import OrderBookWidget
        self.orderbook = OrderBookWidget(self._default_symbols[0])
        self._ob_dock = TradeDock("📋  Order Book")
        self._ob_dock.setWidget(self.orderbook)
        self._ob_dock.setMinimumWidth(240)
        self._ob_dock.minimize_requested.connect(self._minimize_to_bottom)
        self._inner.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._ob_dock)

        # ── Right dock: Trading Panel (stacked below Order Book) ───────
        from ui.trading_panel import TradingPanel
        self.trading_panel = TradingPanel()
        self.trading_panel.order_submitted.connect(self.order_submitted)
        self.trading_panel.cancel_requested.connect(self.cancel_requested)
        self._tp_dock = TradeDock("⚡  Trading")
        self._tp_dock.setWidget(self.trading_panel)
        self._tp_dock.setMinimumWidth(240)
        self._tp_dock.minimize_requested.connect(self._minimize_to_bottom)
        self._inner.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._tp_dock)

        self.symbol_changed.connect(self.orderbook.set_symbol)

        # ── Bottom tray dock — receives minimised panels as tabs ───────
        _tray_widget = QWidget()
        _tray_widget.setStyleSheet(f"background:{BG1};")
        _tray_widget.setFixedHeight(2)
        self._tray_dock = QDockWidget("Panels", self._inner)
        self._tray_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self._tray_dock.setWidget(_tray_widget)
        self._tray_dock.setTitleBarWidget(QWidget())   # hide title bar of tray itself
        self._tray_dock.hide()
        self._inner.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._tray_dock)

    # ── minimise-to-bottom ─────────────────────────────────────────────

    def _minimize_to_bottom(self, dock: QDockWidget) -> None:
        """Move dock to the bottom tray and tabify it — minimise-to-tray UX."""
        self._inner.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self._tray_dock.show()
        self._inner.tabifyDockWidget(self._tray_dock, dock)
        # Activate the tray tab so the panel appears 'behind' it (minimised)
        self._tray_dock.raise_()

    # ── public API (unchanged) ─────────────────────────────────────────

    def update_pnl(self, metrics: dict) -> None:
        self.trading_panel.update_pnl(metrics)

    def update_active_orders(self, orders: list) -> None:
        self.trading_panel.update_active_orders(orders)

    def set_current_price(self, price: float) -> None:
        self.trading_panel.set_current_price(price)

    def current_symbol(self) -> str:
        return self.chart_panel.current_symbol()


# ══════════════════════════════════════════════════════════════════════════════
# STATUS BAR
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# TOAST NOTIFICATION OVERLAY
# ══════════════════════════════════════════════════════════════════════════════

class ToastOverlay(QWidget):
    """
    Transient floating notification that auto-dismisses after 4 seconds.
    Appears in the bottom-right corner of the parent window.
    Safe to call from background threads via show_toast().
    """

    _show_requested = pyqtSignal(str, str)   # message, level

    _LEVEL_STYLE: dict[str, tuple[str, str]] = {
        # level → (border colour, icon)
        "ERROR":    (RED,    "🔴"),
        "WARNING":  (YELLOW, "🟡"),
        "SUCCESS":  (GREEN,  "🟢"),
        "INFO":     (ACCENT, "ℹ️"),
    }

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setWindowFlags(Qt.WindowType.SubWindow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        self._icon_lbl = QLabel()
        self._icon_lbl.setStyleSheet(f"font-size:14px;")

        self._msg_lbl = QLabel()
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setStyleSheet(f"color:{FG0}; font-size:12px;")
        self._msg_lbl.setMaximumWidth(340)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._icon_lbl)
        row.addWidget(self._msg_lbl, 1)
        layout.addLayout(row)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(4000)
        self._timer.timeout.connect(self.hide)

        self._show_requested.connect(self._on_show)
        self.hide()

    def show_toast(self, message: str, level: str = "ERROR") -> None:
        """Thread-safe: can be called from any thread."""
        self._show_requested.emit(message[:160], level)

    def _on_show(self, message: str, level: str) -> None:
        border, icon = self._LEVEL_STYLE.get(level, (ACCENT, "ℹ️"))
        self._icon_lbl.setText(icon)
        self._msg_lbl.setText(message)
        self.setStyleSheet(
            f"ToastOverlay {{ background:{BG3}; border:1px solid {border}; "
            f"border-radius:6px; }}"
        )
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start()

    def _reposition(self) -> None:
        p = self.parent()
        if p:
            pw, ph = p.width(), p.height()
            w, h = self.sizeHint().width(), self.sizeHint().height()
            self.setGeometry(pw - w - 16, ph - h - 40, w, h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition()


class _ClickableLabel(QLabel):
    """QLabel that emits clicked signal and shows pointer cursor on hover."""

    clicked = pyqtSignal()

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TradingStatusBar(QStatusBar):
    # Emitted when user clicks any service indicator — opens status popup
    status_popup_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(28)
        self._status_dialog = None   # lazy-created SystemStatusDialog

        def lbl(text: str, col: str = FG1) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(
                f"color:{col}; font-size:11px; padding:0 10px; font-family:monospace;"
            )
            return l

        def clbl(text: str, col: str = FG1) -> _ClickableLabel:
            """Clickable label — opens system status popup."""
            l = _ClickableLabel(text)
            l.setStyleSheet(
                f"color:{col}; font-size:11px; padding:0 10px; font-family:monospace;"
            )
            l.setToolTip("Click to open System Status dashboard")
            l.clicked.connect(self._open_status_popup)
            return l

        self.mode_lbl   = lbl("MODE: MANUAL", YELLOW)
        self.at_lbl     = lbl("AT: IDLE")
        self.trades_lbl = lbl("TRADES: 0")

        # P&L — clickable, coloured, prominent
        self.pnl_lbl = _ClickableLabel("P&L: $0.00")
        self.pnl_lbl.setStyleSheet(
            f"color:{FG2}; font-size:11px; padding:0 10px; font-family:monospace;"
        )
        self.pnl_lbl.setToolTip("Today's realised P&L — click for full report")
        self.pnl_lbl.clicked.connect(self._open_status_popup)

        self.api_lbl = clbl("● API")

        # Network status — clickable
        self.net_lbl = clbl("● NET: —", FG2)

        # DB / Redis — clickable, opens status popup
        self.db_lbl    = clbl("● DB: —",  FG2)
        self.redis_lbl = clbl("● RDS: —", FG2)

        for w in [self.net_lbl, self.db_lbl, self.redis_lbl, _vsep(),
                  self.mode_lbl, _vsep(), self.at_lbl, _vsep(),
                  self.trades_lbl, _vsep(), self.pnl_lbl, _vsep(),
                  self.api_lbl, _vsep()]:
            self.addWidget(w)

        self.cpu_lbl  = lbl("CPU: —")
        self.mem_lbl  = lbl("MEM: —")
        self.time_lbl = lbl(time.strftime("%H:%M  %d %b %Y"), ACCENT)
        for w in [self.cpu_lbl, self.mem_lbl, self.time_lbl]:
            self.addPermanentWidget(w)

        QTimer(self, interval=1000,
               timeout=lambda: self.time_lbl.setText(
                   time.strftime("%H:%M:%S  %d %b %Y")
               )).start()

        # Health-check every 30 s — runs on the UI thread via QTimer
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(30_000)
        self._health_timer.timeout.connect(self._run_health_check)

        # Network check every 15 s
        self._net_timer = QTimer(self)
        self._net_timer.setInterval(15_000)
        self._net_timer.timeout.connect(self._check_network)

    def start_health_checks(self) -> None:
        """Call once after the window is shown to begin live monitoring."""
        self._run_health_check()
        self._check_network()
        self._health_timer.start()
        self._net_timer.start()

    def _run_health_check(self) -> None:
        # PostgreSQL
        try:
            from db.postgres import get_db
            from sqlalchemy import text
            with get_db() as db:
                db.execute(text("SELECT 1"))
            self.set_service("db", True)
        except Exception:
            self.set_service("db", False)

        # Redis
        try:
            from db.redis_client import get_redis
            get_redis().ping()
            self.set_service("redis", True)
        except Exception:
            self.set_service("redis", False)

    def _check_network(self) -> None:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(2)
            sock.connect(("8.8.8.8", 53))
            self.set_service("network", True)
        except Exception:
            self.set_service("network", False)
        finally:
            sock.close()

    def _open_status_popup(self) -> None:
        """Open (or raise) the live System Status dialog."""
        try:
            from ui.system_status_widget import SystemStatusDialog
            if self._status_dialog is None or not self._status_dialog.isVisible():
                self._status_dialog = SystemStatusDialog(self.parent())
                self._status_dialog.show()
            else:
                self._status_dialog.raise_()
                self._status_dialog.activateWindow()
        except Exception as exc:
            import traceback; traceback.print_exc()

    def set_mode(self, mode: str) -> None:
        col = {"AUTO": GREEN, "MANUAL": YELLOW, "HYBRID": ACCENT,
               "PAPER": ACCENT2, "PAUSED": RED}.get(mode.upper(), FG1)
        self.mode_lbl.setText(f"MODE: {mode.upper()}")
        self.mode_lbl.setStyleSheet(
            f"color:{col}; font-size:11px; padding:0 10px; font-family:monospace;"
        )

    def set_at_state(self, state: str) -> None:
        col = {"idle": FG2, "scanning": ACCENT, "aiming": YELLOW,
               "entering": GREEN, "monitoring": GREEN,
               "exiting": YELLOW, "cooldown": RED}.get(state, FG2)
        self.at_lbl.setText(f"AT: {state.upper()}")
        self.at_lbl.setStyleSheet(
            f"color:{col}; font-size:11px; padding:0 10px; font-family:monospace;"
        )

    def set_service(self, name: str, ok: bool) -> None:
        mapping = {
            "api":     self.api_lbl,
            "db":      self.db_lbl,
            "redis":   self.redis_lbl,
            "network": self.net_lbl,
        }
        widget = mapping.get(name)
        if widget:
            col  = GREEN if ok else RED
            tags = {
                "api":     "API",
                "db":      "DB",
                "redis":   "RDS",
                "network": "NET",
            }
            short  = tags.get(name, name.upper())
            status = "ONLINE" if ok else "OFFLINE"
            widget.setText(f"● {short}: {status}")
            widget.setStyleSheet(
                f"color:{col}; font-size:11px; padding:0 10px; font-family:monospace;"
            )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    """BinanceML Pro – Futuristic AI Trading Desk."""

    _toast_signal = pyqtSignal(str, str)   # message, level – cross-thread safe

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
        mtf_filter=None,
        signal_council=None,
        ensemble=None,
        dynamic_risk=None,
        monte_carlo=None,
        walk_forward=None,
        trade_journal=None,
        market_scanner=None,
        auto_trader=None,
        market_pulse=None,
        forecast_tracker=None,
        archive_downloader=None,
        data_collector=None,
        ping_pong=None,
        strategy_manager=None,
        arb_detector=None,
        arb_trader=None,
        trend_scanner=None,
        pair_scanner=None,
        pair_ml_analyzer=None,
        accumulation_detector=None,
        liquidity_analyzer=None,
        breakout_detector=None,
        gap_detector=None,
        large_candle_watcher=None,
        iceberg_detector=None,
        ml_central=None,
        metamask_wallet=None,
        sim_twin=None,
        mutation_lab=None,
        contract_analyzer=None,
        honeypot_detector=None,
        liq_lock_analyzer=None,
        wallet_graph_analyzer=None,
        rugpull_scorer=None,
        launch_signal=None,
        discord=None,
        slack=None,
        email_notifier=None,
        funding_monitor=None,
        ofi_monitor=None,
        correlation_engine=None,
        cascade_detector=None,
        stream_deck=None,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._metamask_wallet        = metamask_wallet
        self._sim_twin               = sim_twin
        self._mutation_lab           = mutation_lab
        self._contract_analyzer      = contract_analyzer
        self._honeypot_detector      = honeypot_detector
        self._liq_lock_analyzer      = liq_lock_analyzer
        self._wallet_graph_analyzer  = wallet_graph_analyzer
        self._rugpull_scorer         = rugpull_scorer
        self._launch_signal          = launch_signal
        self._engine                 = engine
        self._portfolio              = portfolio
        self._predictor              = predictor
        self._order_manager          = order_manager
        self._trainer                = trainer
        self._tax_calc               = tax_calc
        self._cl                     = continuous_learner
        self._whale_watcher          = whale_watcher
        self._token_ml               = token_ml
        self._sentiment              = sentiment
        self._port_opt               = port_opt
        self._backtester             = backtester
        self._voice                  = voice
        self._telegram               = telegram
        self._new_token_watcher      = new_token_watcher
        self._regime_detector        = regime_detector
        self._mtf_filter             = mtf_filter
        self._signal_council         = signal_council
        self._ensemble               = ensemble
        self._dynamic_risk           = dynamic_risk
        self._monte_carlo            = monte_carlo
        self._walk_forward           = walk_forward
        self._trade_journal          = trade_journal
        self._market_scanner         = market_scanner
        self._auto_trader            = auto_trader
        self._market_pulse           = market_pulse
        self._forecast_tracker       = forecast_tracker
        self._archive_downloader     = archive_downloader
        self._data_collector         = data_collector
        self._ping_pong              = ping_pong
        self._strategy_manager       = strategy_manager
        self._arb_detector           = arb_detector
        self._arb_trader             = arb_trader
        self._trend_scanner          = trend_scanner
        self._pair_scanner           = pair_scanner
        self._pair_ml_analyzer       = pair_ml_analyzer
        self._accumulation_detector  = accumulation_detector
        self._liquidity_analyzer     = liquidity_analyzer
        self._breakout_detector      = breakout_detector
        self._gap_detector           = gap_detector
        self._large_candle_watcher   = large_candle_watcher
        self._iceberg_detector       = iceberg_detector
        self._ml_central             = ml_central

        self._discord        = discord
        self._slack          = slack
        self._email_notifier = email_notifier
        self._funding_monitor    = funding_monitor
        self._ofi_monitor        = ofi_monitor
        self._correlation_engine = correlation_engine
        self._cascade_detector   = cascade_detector
        self._stream_deck        = stream_deck

        self._settings       = get_settings()
        self._intel          = get_intel_logger()
        self._active_symbols = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]
        self._current_symbol = self._active_symbols[0]

        self.setWindowTitle("BinanceML Pro  ·  Professional AI Trading Desk")
        self.setMinimumSize(1440, 900)

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._connect_signals()
        self._start_timers()

        # Wire toast to intel logger (ERROR + WARNING entries from any thread)
        self._toast_signal.connect(self._toast.show_toast)
        self._intel.subscribe(self._on_intel_for_toast)

        self.nav.set_active(0)
        self._intel.system("MainWindow", "BinanceML Pro trading desk ready.")

        # Check Binance API key and show setup prompt if missing
        self._binance_api_ignored = False
        self._apply_api_nav_state()
        QTimer.singleShot(800, self._check_binance_api)

    # ──────────────────────────────────────────────────────────────────
    # Binance API key guard
    # ──────────────────────────────────────────────────────────────────

    def _apply_api_nav_state(self) -> None:
        """Grey out pages that require a Binance API key when none is configured."""
        has_key = bool(self._settings.binance.api_key)
        # Pages requiring live authenticated Binance access
        for page_idx in (0, 1):   # Trading Panel, AutoTrader
            self.nav.set_nav_disabled(page_idx, not has_key)

    def _check_binance_api(self) -> None:
        """Show a one-time prompt if Binance API keys are not configured."""
        if self._binance_api_ignored:
            return
        if self._settings.binance.api_key:
            return

        from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QLabel
        from PyQt6.QtCore import Qt

        dlg = QDialog(self)
        dlg.setWindowTitle("Binance API Key Not Set")
        dlg.setMinimumWidth(420)
        dlg.setStyleSheet(
            f"QDialog {{ background:{BG2}; color:{FG0}; border:1px solid {BORDER}; border-radius:8px; }}"
            f"QLabel {{ color:{FG1}; font-size:12px; }}"
        )

        layout = QVBoxLayout(dlg)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        icon_row = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(svg_pixmap("bolt", YELLOW, 28))
        icon_lbl.setFixedSize(32, 32)
        icon_row.addWidget(icon_lbl)
        title_lbl = QLabel("No Binance API Key Configured")
        title_lbl.setStyleSheet(f"color:{FG0}; font-size:14px; font-weight:700;")
        icon_row.addWidget(title_lbl)
        icon_row.addStretch()
        layout.addLayout(icon_row)

        msg = QLabel(
            "Live trading, portfolio data and order management are <b>disabled</b> "
            "until a Binance API key is provided.<br><br>"
            "You can continue in read-only / ML-only mode, or open Settings to "
            "add your Binance API key now."
        )
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color:{FG2}; font-size:11px;")
        layout.addWidget(msg)

        btns = QDialogButtonBox()
        ignore_btn = btns.addButton("Ignore", QDialogButtonBox.ButtonRole.RejectRole)
        setup_btn  = btns.addButton("Open Settings", QDialogButtonBox.ButtonRole.AcceptRole)
        ignore_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{FG2}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:6px 16px; font-size:11px; }}"
            f"QPushButton:hover {{ color:{FG0}; border-color:{BORDER2}; }}"
        )
        setup_btn.setStyleSheet(
            f"QPushButton {{ background:{ACCENT}; color:#000; border:none; "
            f"border-radius:4px; padding:6px 16px; font-size:11px; font-weight:700; }}"
            f"QPushButton:hover {{ background:{ACCENT2}; }}"
        )
        layout.addWidget(btns)

        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted:
            # Navigate to Settings page (index 8) and select the Binance tab
            self._navigate_to(8)
            try:
                settings_widget = self.stack.widget(8)
                if hasattr(settings_widget, "tabs"):
                    settings_widget.tabs.setCurrentIndex(0)  # Binance tab is first
            except Exception:
                pass
        else:
            # User chose to ignore — suppress future API error toasts for portfolio
            self._binance_api_ignored = True
            self._intel.warning(
                "MainWindow",
                "Binance API key not set – live trading disabled. "
                "Go to Settings → Binance to configure."
            )

    def _on_settings_saved(self) -> None:
        """Called when settings are saved – re-evaluate API nav state and
        check whether PostgreSQL just became available after SQLite was active."""
        self._settings = get_settings()
        self._apply_api_nav_state()
        if self._settings.binance.api_key:
            self._binance_api_ignored = False

        # If we were on SQLite and PostgreSQL may now be reachable, try to
        # connect and offer a migration dialog.
        from db.postgres import is_sqlite
        if is_sqlite():
            QTimer.singleShot(0, self._try_postgres_and_migrate)

    def _try_postgres_and_migrate(self) -> None:
        """
        Attempt a PostgreSQL connection after settings save.
        If successful and SQLite data exists, show the migration dialog.
        Runs the connection probe in a background thread to avoid blocking the UI.
        """
        import threading

        def _probe():
            try:
                from sqlalchemy import create_engine, text
                test_eng = create_engine(
                    self._settings.db_url,
                    pool_pre_ping=True,
                    connect_args={"connect_timeout": 5},
                )
                with test_eng.connect() as conn:
                    conn.execute(text("SELECT 1"))
                test_eng.dispose()
                # PG is reachable — schedule dialog on the GUI thread
                QTimer.singleShot(0, self._offer_migration)
            except Exception:
                pass   # Still unreachable — stay on SQLite silently

        threading.Thread(target=_probe, daemon=True, name="pg-probe").start()

    def _offer_migration(self) -> None:
        """
        Called on the GUI thread once PostgreSQL is confirmed reachable.
        If SQLite has data show the migration dialog; otherwise switch engines
        directly with a toast notification.
        """
        from db.sqlite_to_postgres import sqlite_has_data

        if sqlite_has_data():
            try:
                from ui.db_migration_dialog import DbMigrationDialog
                dlg = DbMigrationDialog(
                    pg_url=self._settings.db_url,
                    pg_pool_size=self._settings.database.pool_size,
                    pg_max_overflow=self._settings.database.max_overflow,
                    parent=self,
                )
                dlg.run()   # blocks until user closes (auto-closes on success)
            except Exception as exc:
                self._intel.warning("Migration", f"Could not open migration dialog: {exc}")
                return
        else:
            self._intel.system("Migration", "No SQLite data to migrate.")

        # Reinitialise the active DB engine to PostgreSQL for this session
        self._reinit_postgres_engine()

    def _reinit_postgres_engine(self) -> None:
        """
        Reset the module-level SQLAlchemy engine to PostgreSQL.
        Called after a successful migration (or when PG is available but SQLite
        has no data worth migrating).
        """
        import db.postgres as pg_mod
        try:
            with pg_mod._lock:
                # Dispose existing SQLite engine cleanly
                if pg_mod._engine is not None:
                    try:
                        pg_mod._engine.dispose()
                    except Exception:
                        pass
                pg_mod._engine = None
                pg_mod._SessionLocal = None
                pg_mod._using_sqlite = False

            # Re-connect to PostgreSQL
            pg_mod.init_db(
                self._settings.db_url,
                pool_size=self._settings.database.pool_size,
                max_overflow=self._settings.database.max_overflow,
            )
            self._intel.system("Migration", "PostgreSQL is now the active database.")
        except Exception as exc:
            self._intel.warning("Migration", f"Could not switch to PostgreSQL: {exc}")

    # ──────────────────────────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Enable full dock management: animated moves, tabbing, nesting, group-drag
        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks |
            QMainWindow.DockOption.AllowTabbedDocks |
            QMainWindow.DockOption.AllowNestedDocks |
            QMainWindow.DockOption.GroupedDragging
        )

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header (contains hamburger toggle)
        self.header = HeaderBar(self._active_symbols)
        self.header.symbol_changed.connect(self._on_symbol_changed)
        self.header.nav_toggle.connect(self._toggle_nav)
        root.addWidget(self.header)

        # Body
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.nav = NavSidebar()
        self.nav.page_requested.connect(self._navigate_to)
        body.addWidget(self.nav)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        # Slide animation for the nav sidebar (animates maximumWidth)
        self._nav_collapsed = False
        self._nav_anim = QPropertyAnimation(self.nav, b"maximumWidth")
        self._nav_anim.setDuration(220)
        self._nav_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # Status bar
        self.status_bar = TradingStatusBar()
        self.setStatusBar(self.status_bar)

        # Pages
        self._build_trading_page()       # 0
        self._build_autotrader_page()    # 1
        self._build_ml_page()            # 2
        self._build_risk_page()          # 3
        self._build_backtest_page()      # 4
        self._build_trade_journal_page() # 5
        self._build_strategy_page()      # 6
        self._build_connections_page()   # 7
        self._build_settings_page()      # 8
        self._build_help_page()          # 9
        self._build_simulation_page()    # 10
        self._build_reports_page()       # 11
        self._build_market_watch_page()  # 12
        self._build_ml_tools_page()      # 13

        # Toast notification overlay (floats over the window)
        self._toast = ToastOverlay(central)

        # Intel Log dock — uses TradeDock for consistent title bar + full dock features
        from ui.intel_log_widget import IntelLogWidget
        self.intel_log  = IntelLogWidget()
        self.intel_dock = TradeDock("📡  Intel Log", self)
        self.intel_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea |
            Qt.DockWidgetArea.TopDockWidgetArea   |
            Qt.DockWidgetArea.LeftDockWidgetArea  |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.intel_dock.setWidget(self.intel_log)
        self.intel_dock.setMinimumHeight(120)
        # Minimise Intel Log → tabify with itself (just hides to tab bar at bottom)
        self.intel_dock.minimize_requested.connect(
            lambda _: self.intel_dock.hide()
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.intel_dock)

    def _build_trading_page(self) -> None:
        self.trading_page = TradingPage(
            self._active_symbols, forecast_tracker=self._forecast_tracker
        )
        self.trading_page.order_submitted.connect(self._on_order_submitted)
        self.trading_page.cancel_requested.connect(self._on_cancel_requested)
        self.trading_page.symbol_changed.connect(self._on_symbol_changed)
        self.stack.addWidget(self.trading_page)

    def _build_autotrader_page(self) -> None:
        try:
            from ui.auto_trader_widget import AutoTraderWidget
            from ui.alert_panel import AlertPanel
            from core.alert_manager import get_alert_manager

            self._alert_mgr = get_alert_manager()

            # Wire AutoTrader cycle results → AlertManager
            if self._auto_trader:
                try:
                    self._auto_trader.on_cycle_result(self._alert_mgr.on_cycle_result)
                except Exception:
                    pass

            # Wire pre-built MarketPulse service to AlertManager
            if self._market_pulse:
                try:
                    self._market_pulse.on_alert(self._alert_mgr.on_pulse_alert)
                except Exception:
                    pass

            # Wire new-token watcher → AlertManager
            if self._new_token_watcher:
                try:
                    self._new_token_watcher.on_launch(
                        lambda sym, profile: self._alert_mgr.on_new_token(
                            sym,
                            price=getattr(profile, "launch_price", 0.0),
                        )
                    )
                except Exception:
                    pass

            # Build AutoTrader widget (pass chart widget if trading page has one)
            chart_ref = None
            try:
                chart_panel = getattr(self.trading_page, "chart_panel", None)
                cw = getattr(chart_panel, "_chart_widgets", None)
                chart_ref = list(cw.values())[0] if cw else None
            except Exception:
                pass

            self.at_widget = AutoTraderWidget(
                auto_trader=self._auto_trader,
                market_scanner=self._market_scanner,
                chart_widget=chart_ref,
            )

            # Build alert panel
            self.alert_widget = AlertPanel(alert_manager=self._alert_mgr)

            # Combine in a tab widget
            from PyQt6.QtWidgets import QTabWidget
            tabs = QTabWidget()
            tabs.setStyleSheet("""
                QTabBar::tab { padding:5px 14px; font-size:11px; }
                QTabBar::tab:selected { font-weight:700; }
            """)
            tabs.addTab(self.at_widget,    "🤖  AutoTrader")
            tabs.addTab(self.alert_widget, "🔔  Alerts")

            # Ping-Pong range trader tab
            try:
                from ui.ping_pong_widget import PingPongWidget
                self.pp_widget = PingPongWidget(ping_pong_trader=self._ping_pong)
                tabs.addTab(self.pp_widget, "⚡  Ping-Pong")
            except Exception:
                pass

            # ML Strategy Manager tab
            try:
                from ui.strategy_manager_widget import StrategyManagerWidget
                self.strat_widget = StrategyManagerWidget(
                    strategy_manager=self._strategy_manager
                )
                tabs.addTab(self.strat_widget, "🧠  Strategies")
            except Exception:
                pass

            # Arbitrage Detector / Auto-Trader tab
            try:
                from ui.arbitrage_widget import ArbitrageWidget
                self.arb_widget = ArbitrageWidget(
                    arbitrage_detector=self._arb_detector,
                    arbitrage_trader=self._arb_trader,
                )
                tabs.addTab(self.arb_widget, "⚡  Arbitrage")
            except Exception:
                pass

            self.at_page = tabs

        except Exception as exc:
            self.at_page = _placeholder("AutoTrader", f"Not available: {exc}")
        self.stack.addWidget(self.at_page)

    def _build_ml_page(self) -> None:
        try:
            from ui.ml_training_widget import MLTrainingWidget
            self.ml_page = MLTrainingWidget(trainer=self._trainer)
            if self._whale_watcher:
                try:
                    self._whale_watcher.on_event(
                        lambda ev: self.ml_page.add_whale_event(ev)
                    )
                except Exception:
                    pass
            if self._token_ml:
                try:
                    self._token_ml.on_signal(
                        lambda sig: self.ml_page.add_signal({**sig, "source": "TokenML"})
                    )
                except Exception:
                    pass
        except Exception:
            self.ml_page = _placeholder("ML Training", "Not available")
        self.stack.addWidget(self.ml_page)

    def _build_risk_page(self) -> None:
        try:
            from ui.risk_dashboard import RiskDashboard
            self.risk_page = RiskDashboard(
                dynamic_risk=self._dynamic_risk,
                regime_detector=self._regime_detector,
                ensemble=self._ensemble,
                trade_journal=self._trade_journal,
                monte_carlo=self._monte_carlo,
                walk_forward=self._walk_forward,
                engine=self._engine,
                port_opt=self._port_opt,
            )
        except Exception:
            self.risk_page = _placeholder("Risk Dashboard", "Not available")
        self.stack.addWidget(self.risk_page)

    def _build_backtest_page(self) -> None:
        try:
            from ui.backtest_widget import BacktestWidget
            self.backtest_page = BacktestWidget(backtester=self._backtester)
        except Exception as exc:
            self.backtest_page = _placeholder("Backtesting Engine", f"Not available: {exc}")
        self.stack.addWidget(self.backtest_page)

    def _build_trade_journal_page(self) -> None:
        try:
            from ui.trade_journal_widget import TradeJournalWidget
            self.journal_page = TradeJournalWidget(trade_journal=self._trade_journal)
        except Exception as exc:
            self.journal_page = _placeholder("Trade Journal", f"Not available: {exc}")
        self.stack.addWidget(self.journal_page)

    def _build_strategy_page(self) -> None:
        try:
            from ui.strategy_builder import StrategyBuilderWidget
            self.strategy_page = StrategyBuilderWidget(backtester=self._backtester)
        except Exception as exc:
            self.strategy_page = _placeholder("Strategy Builder", f"Not available: {exc}")
        self.stack.addWidget(self.strategy_page)

    def _build_simulation_page(self) -> None:
        """Simulation – Live Twin + Mutation Lab (accessed from Simulation menu)."""
        try:
            from PyQt6.QtWidgets import QTabWidget
            tabs = QTabWidget()
            tabs.setStyleSheet(
                f"QTabWidget::pane {{ border:1px solid #2A2A4A; background:#0A0A12; }}"
                f"QTabBar::tab {{ background:#12121E; color:#8888AA; padding:7px 16px; }}"
                f"QTabBar::tab:selected {{ background:#1A1A2E; color:#00D4FF; "
                f"border-bottom:2px solid #00D4FF; }}"
            )

            # Live Simulation Twin
            from ui.simulation_twin_widget import SimulationTwinWidget
            self.sim_twin_widget = SimulationTwinWidget(twin=getattr(self, "_sim_twin", None))
            tabs.addTab(self.sim_twin_widget, "🔮  Simulation Twin")

            # Strategy Mutation Lab
            from ui.mutation_lab_widget import MutationLabWidget
            self.mutation_lab_widget = MutationLabWidget(lab=getattr(self, "_mutation_lab", None))
            tabs.addTab(self.mutation_lab_widget, "🧬  Mutation Lab")

            # Token & Contract Safety
            from ui.safety_widget import SafetyWidget
            self.safety_widget = SafetyWidget(
                contract_analyzer=getattr(self, "_contract_analyzer", None),
                honeypot_detector=getattr(self, "_honeypot_detector", None),
                liq_analyzer=getattr(self, "_liq_lock_analyzer", None),
                wallet_analyzer=getattr(self, "_wallet_graph_analyzer", None),
                rugpull_scorer=getattr(self, "_rugpull_scorer", None),
                launch_signal_engine=getattr(self, "_launch_signal", None),
            )
            tabs.addTab(self.safety_widget, "🛡  Safety Scanner")

            self.simulation_page = tabs
        except Exception as exc:
            logger.warning(f"Simulation page unavailable: {exc}")
            self.simulation_page = _placeholder("Simulation", f"Not available: {exc}")
        self.stack.addWidget(self.simulation_page)

    def _build_market_watch_page(self) -> None:
        """Market Watch – index 12."""
        try:
            from ui.market_watch_panel import MarketWatchPanel
            alert_mgr = getattr(self, "_alert_mgr", None)
            self.market_watch_page = MarketWatchPanel(
                alert_manager    = alert_mgr,
                whale_watcher    = self._whale_watcher,
                funding_monitor  = self._funding_monitor,
                cascade_detector = self._cascade_detector,
                ofi_monitor      = self._ofi_monitor,
                portfolio        = self._portfolio,
                regime_detector  = self._regime_detector,
                correlation_engine = self._correlation_engine,
                predictor        = self._predictor,
                continuous_learner = self._cl,
                engine           = self._engine,
                auto_trader      = self._auto_trader,
                order_manager    = self._order_manager,
            )
            # Forward ML predictor signals to the ML Watch tab
            if self._predictor:
                try:
                    self._predictor.on_signal(
                        lambda s: self.market_watch_page.add_ml_signal(s)
                    )
                except Exception:
                    pass

            # Wire backend events → chart event annotations
            self._wire_chart_events()
        except Exception as exc:
            logger.warning(f"Market Watch page unavailable: {exc}")
            self.market_watch_page = _placeholder("Market Watch", f"Not available: {exc}")
        self.stack.addWidget(self.market_watch_page)

    def _build_ml_tools_page(self) -> None:
        """ML Tools – index 13. All ML-powered scanner and detector tabs."""
        _tab_style = (
            f"QTabWidget::pane {{ border:1px solid {BORDER}; background:{BG1}; }}"
            f"QTabBar::tab {{ background:{BG2}; color:{FG2}; padding:6px 16px; "
            f"border:1px solid {BORDER}; border-bottom:none; font-size:11px; }}"
            f"QTabBar::tab:selected {{ background:{BG3}; color:{ACCENT}; "
            f"border-color:{ACCENT}; font-weight:700; }}"
            f"QTabBar::tab:hover {{ color:{FG0}; }}"
        )
        try:
            tabs = QTabWidget()
            tabs.setStyleSheet(_tab_style)

            # ML Central Command — unified ranked signal pipeline
            try:
                from ui.ml_central_command_widget import MLCentralCommandWidget
                self.ml_central_widget = MLCentralCommandWidget(
                    central_command=self._ml_central,
                )
                self.ml_central_widget.symbol_selected.connect(self._on_symbol_changed)
                tabs.addTab(self.ml_central_widget, "⚡  ML Command")
            except Exception:
                pass

            # Multi-timeframe trend scanner
            try:
                from ui.trend_widget import TrendWidget
                self.trend_widget = TrendWidget(trend_scanner=self._trend_scanner)
                self.trend_widget.symbol_selected.connect(self._on_symbol_changed)
                tabs.addTab(self.trend_widget, "📈  Trends")
            except Exception:
                pass

            # Pair discovery scanner
            try:
                from ui.pair_scanner_widget import PairScannerWidget
                self.pair_scanner_widget = PairScannerWidget(
                    pair_scanner=self._pair_scanner,
                    arb_detector=self._arb_detector,
                    trend_scanner=self._trend_scanner,
                    pair_ml_analyzer=self._pair_ml_analyzer,
                )
                self.pair_scanner_widget.symbol_selected.connect(self._on_symbol_changed)
                tabs.addTab(self.pair_scanner_widget, "🔍  Pairs")
            except Exception:
                pass

            # Stealth accumulation detector
            try:
                from ui.accumulation_widget import AccumulationWidget
                self.accumulation_widget = AccumulationWidget(
                    accumulation_detector=self._accumulation_detector,
                )
                tabs.addTab(self.accumulation_widget, "🕵  Accumulation")
            except Exception:
                pass

            # Liquidity depth analyzer
            try:
                from ui.liquidity_widget import LiquidityWidget
                self.liquidity_widget = LiquidityWidget(
                    liquidity_analyzer=self._liquidity_analyzer,
                )
                tabs.addTab(self.liquidity_widget, "💧  Liquidity")
            except Exception:
                pass

            # Volume breakout detector
            try:
                from ui.breakout_widget import BreakoutWidget
                self.breakout_widget = BreakoutWidget(
                    breakout_detector=self._breakout_detector,
                )
                tabs.addTab(self.breakout_widget, "💥  Breakouts")
            except Exception:
                pass

            # Gap detector
            try:
                from ui.gap_detector_widget import GapDetectorWidget
                self.gap_detector_widget = GapDetectorWidget(
                    gap_detector=self._gap_detector,
                )
                self.gap_detector_widget.symbol_selected.connect(self._on_symbol_changed)
                tabs.addTab(self.gap_detector_widget, "↕  Gaps")
            except Exception:
                pass

            # Large candle watch
            try:
                from ui.large_candle_widget import LargeCandleWidget
                self.large_candle_widget = LargeCandleWidget(
                    large_candle_watcher=self._large_candle_watcher,
                )
                self.large_candle_widget.symbol_selected.connect(self._on_symbol_changed)
                tabs.addTab(self.large_candle_widget, "🕯  Candles")
            except Exception:
                pass

            # Iceberg detector
            try:
                from ui.iceberg_widget import IcebergWidget
                self.iceberg_widget = IcebergWidget(
                    iceberg_detector=self._iceberg_detector,
                )
                self.iceberg_widget.symbol_selected.connect(self._on_symbol_changed)
                tabs.addTab(self.iceberg_widget, "🧊  Icebergs")
            except Exception:
                pass

            self.ml_tools_page = tabs
        except Exception as exc:
            logger.warning(f"ML Tools page unavailable: {exc}")
            self.ml_tools_page = _placeholder("ML Tools", f"Not available: {exc}")
        self.stack.addWidget(self.ml_tools_page)

    # ── Chart event wiring ────────────────────────────────────────────────────

    def _push_chart_event(
        self,
        symbol: str,
        ts: float,
        price: float,
        event_type: str,
        label: str,
        color: str = "",
        detail: str = "",
    ) -> None:
        """Push a market event to the ChartWidget overlay for the given symbol."""
        try:
            chart_panel = getattr(self.trading_page, "chart_panel", None)
            if chart_panel is None:
                return
            cw_map = getattr(chart_panel, "_chart_widgets", {})
            cw = cw_map.get(symbol)
            if cw and hasattr(cw, "add_chart_event"):
                cw.add_chart_event(ts, price, event_type, label, color, detail)
        except Exception:
            pass

    def _wire_chart_events(self) -> None:
        """Register callbacks on backend services to push events to the chart."""
        import time as _time

        # Cascade detector → chart
        cd = getattr(self, "_cascade_detector", None)
        if cd:
            try:
                def _on_cascade(ev):
                    self._push_chart_event(
                        symbol     = ev.symbol,
                        ts         = _time.time(),
                        price      = 0.0,   # will show at last known price
                        event_type = "CASCADE",
                        label      = f"CASCADE {ev.direction} {ev.price_change:+.2%}",
                        color      = "#FF5722",
                        detail     = f"{ev.vol_ratio:.1f}× vol [{ev.severity}]",
                    )
                cd.on_event(_on_cascade)
            except Exception:
                pass

        # Funding rate monitor → chart
        fm = getattr(self, "_funding_monitor", None)
        if fm:
            try:
                def _on_funding(ev):
                    self._push_chart_event(
                        symbol     = ev.symbol,
                        ts         = _time.time(),
                        price      = ev.price,
                        event_type = "FUNDING",
                        label      = f"FUND {ev.rate_pct:+.4f}%",
                        color      = "#FFD700",
                        detail     = ev.direction,
                    )
                fm.on_event(_on_funding)
            except Exception:
                pass

        # Correlation engine lead/lag → chart
        ce = getattr(self, "_correlation_engine", None)
        if ce:
            try:
                def _on_leadlag(ev):
                    # Tag the follower symbol's chart
                    self._push_chart_event(
                        symbol     = ev.follower,
                        ts         = _time.time(),
                        price      = 0.0,
                        event_type = "LEAD_LAG",
                        label      = f"LEAD {ev.leader} {ev.leader_move:+.2%}",
                        color      = "#26C6DA",
                        detail     = f"expect {ev.expected_move}  r={ev.correlation:.2f}",
                    )
                ce.on_event(_on_leadlag)
            except Exception:
                pass

        # Whale watcher → chart
        ww = getattr(self, "_whale_watcher", None)
        if ww:
            try:
                def _on_whale(ev):
                    sym = getattr(ev, "symbol", "") or ""
                    self._push_chart_event(
                        symbol     = sym,
                        ts         = _time.time(),
                        price      = getattr(ev, "price", 0.0) or 0.0,
                        event_type = "WHALE",
                        label      = f"WHALE ${getattr(ev, 'usd_value', 0):,.0f}",
                        color      = "#CE93D8",
                        detail     = getattr(ev, "side", ""),
                    )
                ww.on_event(_on_whale)
            except Exception:
                pass

    def _build_connections_page(self) -> None:
        from ui.connections_widget import ConnectionsWidget
        binance_client = None
        if self._engine and hasattr(self._engine, "_client"):
            binance_client = self._engine._client
        self.connections_page = ConnectionsWidget(
            binance_client=binance_client,
            engine=self._engine,
        )
        self.stack.addWidget(self.connections_page)

    def _build_settings_page(self) -> None:
        from PyQt6.QtWidgets import QTabWidget
        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabWidget::pane {{ border:1px solid {BORDER}; background:{BG1}; }}"
            f"QTabBar::tab {{ background:{BG3}; color:{FG2}; padding:6px 14px; border:none; }}"
            f"QTabBar::tab:selected {{ background:{BG4}; color:{FG0}; }}"
        )

        from ui.system_settings_widget import SystemSettingsWidget
        sys_settings = SystemSettingsWidget()
        def _on_settings_saved():
            self._intel.system("Settings", "Configuration saved.")
            try:
                from core.dex_data_provider import reload_dex_provider
                reload_dex_provider()
            except Exception:
                pass
            try:
                from core.zerox_provider import reload_zerox_provider
                reload_zerox_provider()
            except Exception:
                pass
            try:
                from core.metamask_live_data import reload_metamask_live_data
                reload_metamask_live_data()
            except Exception:
                pass

        sys_settings.settings_saved.connect(_on_settings_saved)
        sys_settings.settings_saved.connect(self._on_settings_saved)
        tabs.addTab(sys_settings, "⚙  System")

        # Layers configuration panel
        try:
            from ui.layers_settings_panel import LayersSettingsPanel
            from core.feature_flag_controller import get_flags
            self.layers_panel = LayersSettingsPanel(flags_controller=get_flags())
            tabs.addTab(self.layers_panel, "🧩  Layers")
        except Exception as exc:
            logger.warning(f"Layers panel unavailable: {exc}")

        # MetaMask wallet tab
        try:
            from ui.metamask_widget import MetaMaskWidget
            self.metamask_widget = MetaMaskWidget(
                metamask_wallet=self._metamask_wallet,
            )
            tabs.addTab(self.metamask_widget, "🦊  MetaMask")
        except Exception:
            pass

        # System Status tab — live Grafana-style monitoring dashboard
        try:
            from ui.system_status_widget import SystemStatusWidget
            self._system_status_tab = SystemStatusWidget()
            tabs.addTab(self._system_status_tab, "📡  Status")
        except Exception as exc:
            logger.warning(f"System status tab unavailable: {exc}")

        self.settings_page = tabs
        self.stack.addWidget(self.settings_page)

    def _build_help_page(self) -> None:
        from ui.help_widget import HelpWidget
        self.help_page = HelpWidget()
        self.stack.addWidget(self.help_page)

    def _build_reports_page(self) -> None:
        try:
            from ui.reports_widget import ReportsWidget
            self.reports_page = ReportsWidget(
                trade_journal=self._trade_journal,
                tax_calc=self._tax_calc,
                forecast_tracker=self._forecast_tracker,
                dynamic_risk=self._dynamic_risk,
                email_notifier=getattr(self, "_email_notifier", None),
                discord=getattr(self, "_discord", None),
                slack=getattr(self, "_slack", None),
            )
        except Exception as exc:
            self.reports_page = _placeholder("Reports", f"Not available: {exc}")
        self.stack.addWidget(self.reports_page)

    # ──────────────────────────────────────────────────────────────────
    # Menu
    # ──────────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # ── File ──────────────────────────────────────────────────────────────
        fm = mb.addMenu("&File")
        fm.addAction(self._act("Settings",       lambda: self._navigate_to(8), "Ctrl+,"))
        fm.addSeparator()
        fm.addAction(self._act("Exit",           self.close,                   "Ctrl+Q"))

        # ── View ─────────────────────────────────────────────────────────────
        vm = mb.addMenu("&View")
        vm.addAction(self._act("Toggle Nav Sidebar",    self._toggle_nav,       "Ctrl+\\"))
        vm.addAction(self._act("Toggle Fullscreen",     self._toggle_fullscreen,"F11"))
        vm.addAction(self._act("Add Chart Tab",         self._add_chart_tab,    "Ctrl++"))
        vm.addSeparator()
        panels_menu = vm.addMenu("Panels")
        panels_menu.addAction(self._act("Toggle Intel Log",     self._toggle_intel_log,     "Ctrl+L"))
        panels_menu.addAction(self._act("Toggle Order Book",    self._toggle_order_book,    "Ctrl+B"))
        panels_menu.addAction(self._act("Toggle Trading Panel", self._toggle_trading_panel, "Ctrl+Shift+B"))
        panels_menu.addSeparator()
        panels_menu.addAction(self._act("Restore Trading Docks",self._restore_trading_docks,"Ctrl+Shift+R"))

        # ── Trading ───────────────────────────────────────────────────────────
        tm = mb.addMenu("&Trading")

        # Trading sub-menu
        trading_panel_m = tm.addMenu("📊  Trading Panel")
        trading_panel_m.addAction(self._act("Open Trading Panel",    lambda: self._navigate_to(0),  "Ctrl+1"))
        trading_panel_m.addSeparator()
        trading_panel_m.addAction(self._act("Toggle Order Book",     self._toggle_order_book,       "Ctrl+B"))
        trading_panel_m.addAction(self._act("Toggle Trading Panel",  self._toggle_trading_panel,    "Ctrl+Shift+B"))
        trading_panel_m.addAction(self._act("Restore Trading Docks", self._restore_trading_docks,   "Ctrl+Shift+R"))
        trading_panel_m.addAction(self._act("Add Chart Tab",         self._add_chart_tab,           "Ctrl++"))

        # AutoTrader sub-menu
        at_menu = tm.addMenu("🤖  AutoTrader")
        at_menu.addAction(self._act("Open AutoTrader",           lambda: self._navigate_to(1),         "Ctrl+2"))
        at_menu.addSeparator()
        at_menu.addAction(self._act("🔔  Alerts Tab",             lambda: self._open_at_tab("Alerts")))
        at_menu.addAction(self._act("⚡  Ping-Pong Tab",          lambda: self._open_at_tab("Ping-Pong")))
        at_menu.addAction(self._act("🧠  Strategies Tab",         lambda: self._open_at_tab("Strategies")))
        at_menu.addAction(self._act("⚡  Arbitrage Tab",          lambda: self._open_at_tab("Arbitrage")))
        at_menu.addSeparator()
        at_menu.addAction(self._act("Semi-Auto Mode",            lambda: self._set_at_mode("semi_auto")))
        at_menu.addAction(self._act("Full-Auto Mode",            lambda: self._set_at_mode("full_auto")))
        at_menu.addSeparator()
        at_menu.addAction(self._act("🎯 Take Aim",               self._at_take_aim,    "Ctrl+Shift+A"))
        at_menu.addAction(self._act("🛑 Exit Trade",             self._at_manual_exit, "Ctrl+Shift+E"))
        at_menu.addAction(self._act("🔭 Scan Now",               self._at_scan_now,    "Ctrl+Shift+N"))

        tm.addSeparator()

        # Analysis tools sub-menus
        risk_m = tm.addMenu("📉  Risk Dashboard")
        risk_m.addAction(self._act("Open Risk Dashboard",        lambda: self._navigate_to(3), "Ctrl+4"))

        backtest_m = tm.addMenu("🧪  Backtesting")
        backtest_m.addAction(self._act("Open Backtest Engine",   lambda: self._navigate_to(4), "Ctrl+5"))

        journal_m = tm.addMenu("📒  Trade Journal")
        journal_m.addAction(self._act("Open Trade Journal",      lambda: self._navigate_to(5), "Ctrl+6"))

        strategy_m = tm.addMenu("🔧  Strategy Builder")
        strategy_m.addAction(self._act("Open Strategy Builder",  lambda: self._navigate_to(6), "Ctrl+7"))

        tm.addSeparator()

        # Trading mode switcher
        modes_m = tm.addMenu("⚙  Trading Mode")
        for mode in ["Manual", "Auto", "Hybrid", "Paper", "Paused"]:
            modes_m.addAction(self._act(f"{mode} Mode",
                lambda _, m=mode: self._set_engine_mode(m.lower())))

        tm.addSeparator()
        tm.addAction(self._act("❌ Cancel All Orders", self._cancel_all_orders, "Ctrl+Shift+X"))

        # ── ML ────────────────────────────────────────────────────────────────
        mlm = mb.addMenu("&ML")

        # ML Training sub-menu
        mlt_m = mlm.addMenu("🧠  ML Training")
        mlt_m.addAction(self._act("Open ML Training Panel",  lambda: self._navigate_to(2),  "Ctrl+3"))
        mlt_m.addSeparator()
        mlt_m.addAction(self._act("▶  Start Training",       self._start_training,          "Ctrl+T"))
        mlt_m.addAction(self._act("■  Stop Training",        self._stop_training,           "Ctrl+Shift+T"))
        mlt_m.addSeparator()
        mlt_m.addAction(self._act("↺  Reload Model",         self._reload_model,            "Ctrl+R"))
        mlt_m.addAction(self._act("✓  Data Integrity Check", self._run_integrity_check,     "Ctrl+I"))

        # ML Tools sub-menu (each sub-tab in ML Tools page)
        mltools_m = mlm.addMenu("⚡  ML Tools")
        mltools_m.addAction(self._act("Open ML Tools Panel",         lambda: self._navigate_to(13),     "Ctrl+Shift+M"))
        mltools_m.addSeparator()
        mltools_m.addAction(self._act("⚡  ML Central Command",      lambda: self._open_ml_tools_tab("ML Command")))
        mltools_m.addAction(self._act("📈  Trends",                  lambda: self._open_ml_tools_tab("Trends")))
        mltools_m.addAction(self._act("🔍  Pairs Scanner",           lambda: self._open_ml_tools_tab("Pairs")))
        mltools_m.addAction(self._act("🕵  Accumulation Detector",   lambda: self._open_ml_tools_tab("Accumulation")))
        mltools_m.addAction(self._act("💧  Liquidity Analyzer",      lambda: self._open_ml_tools_tab("Liquidity")))
        mltools_m.addAction(self._act("💥  Breakout Detector",       lambda: self._open_ml_tools_tab("Breakouts")))
        mltools_m.addAction(self._act("↕  Gap Detector",             lambda: self._open_ml_tools_tab("Gaps")))
        mltools_m.addAction(self._act("🕯  Large Candle Watcher",    lambda: self._open_ml_tools_tab("Candles")))
        mltools_m.addAction(self._act("🧊  Iceberg Detector",        lambda: self._open_ml_tools_tab("Icebergs")))

        # ── Market ────────────────────────────────────────────────────────────
        mktm = mb.addMenu("&Market")

        # Market Watch sub-menu (sub-tabs)
        mw_m = mktm.addMenu("📡  Market Watch")
        mw_m.addAction(self._act("Open Market Watch",           lambda: self._navigate_to(12), "Ctrl+Shift+W"))
        mw_m.addSeparator()
        mw_m.addAction(self._act("📊  Volume Alerts",           lambda: self._open_market_watch_tab(0)))
        mw_m.addAction(self._act("🤖  ML Watch",                lambda: self._open_market_watch_tab(1)))
        mw_m.addAction(self._act("📈  Order Flow",              lambda: self._open_market_watch_tab(2)))
        mw_m.addAction(self._act("🗺  Portfolio Heatmap",        lambda: self._open_market_watch_tab(3)))
        mw_m.addAction(self._act("🌊  Regime & Cascade",        lambda: self._open_market_watch_tab(4)))
        mw_m.addAction(self._act("🛑  Kill Switch",             lambda: self._open_market_watch_tab(5)))

        # Reports sub-menu
        rep_m = mktm.addMenu("📋  Reports")
        rep_m.addAction(self._act("Open Reports Panel",         lambda: self._navigate_to(11), "F2"))

        # Simulation sub-menu
        sim_m = mktm.addMenu("🔮  Simulation")
        sim_m.addAction(self._act("Open Simulation Panel",      lambda: self._navigate_to(10),  "Ctrl+Shift+S"))
        sim_m.addSeparator()
        sim_m.addAction(self._act("🔮  Live Simulation Twin",   lambda: self._open_sim_tab(0),  "Ctrl+Shift+V"))
        sim_m.addAction(self._act("🧬  Strategy Mutation Lab",  lambda: self._open_sim_tab(1),  "Ctrl+Alt+M"))
        sim_m.addAction(self._act("🛡  Safety Scanner",         lambda: self._open_sim_tab(2),  "Ctrl+Shift+F"))

        # ── Network ───────────────────────────────────────────────────────────
        netm = mb.addMenu("&Network")
        netm.addAction(self._act("🔗  Connections Panel",       lambda: self._navigate_to(7),  "Ctrl+8"))
        netm.addAction(self._act("✓  Check All Connections",    self._check_connections,        "Ctrl+Shift+C"))
        netm.addSeparator()
        netm.addAction(self._act("▶  Start REST API Server",    self._start_api_server))
        netm.addAction(self._act("📄  View API Endpoints",      self._show_api_docs))
        netm.addSeparator()
        netm.addAction(self._act("📡  System Status Dashboard", self._open_system_status_popup, "Ctrl+Shift+D"))

        # ── Settings ─────────────────────────────────────────────────────────
        setm = mb.addMenu("&Settings")
        setm.addAction(self._act("Open Settings",               lambda: self._navigate_to(8),  "Ctrl+9"))
        setm.addSeparator()

        # Settings sub-tabs
        sys_m = setm.addMenu("⚙  System Settings")
        sys_m.addAction(self._act("Open System Settings",       lambda: self._open_settings_tab(0)))
        sys_m.addSeparator()
        sys_m.addAction(self._act("CoinGecko DEX Setup",        self._open_coingecko_setup))

        layers_m = setm.addMenu("🧩  Layers")
        layers_m.addAction(self._act("Open Layers Settings",    lambda: self._open_settings_tab(1)))
        layers_m.addSeparator()
        for n in range(1, 11):
            key = "0" if n == 10 else str(n)
            layers_m.addAction(self._act(f"Layer {n}", lambda _, lnum=n: self._open_layer(lnum),
                                         f"Shift+Alt+{key}"))

        setm.addMenu("🦊  MetaMask").addAction(
            self._act("Open MetaMask Settings",  lambda: self._open_settings_tab(2))
        )
        setm.addMenu("📡  System Status").addAction(
            self._act("Open Status / Health",    self._open_system_status_popup, "Ctrl+Shift+D")
        )
        setm.addSeparator()

        # Tax sub-menu
        tax_m = setm.addMenu("💷  Tax (UK CGT)")
        tax_m.addAction(self._act("Monthly Report",             self._generate_tax_report))
        tax_m.addAction(self._act("Annual CGT Summary",         self._generate_annual_tax))
        tax_m.addAction(self._act("Send Email Now",             self._send_tax_email))

        # ── Help ─────────────────────────────────────────────────────────────
        hm = mb.addMenu("&Help")
        hm.addAction(self._act("Help Panel",                    lambda: self._navigate_to(9), "F1"))
        hm.addSeparator()
        hm.addAction(self._act("About BinanceML Pro",           self._show_about))

    @staticmethod
    def _act(label: str, fn, shortcut: str = "") -> QAction:
        act = QAction(label)
        act.triggered.connect(fn)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        return act

    # ──────────────────────────────────────────────────────────────────
    # Keyboard shortcuts
    # ──────────────────────────────────────────────────────────────────

    def _build_shortcuts(self) -> None:
        # IMPORTANT: QShortcut objects MUST be stored in self._shortcuts.
        # Without a reference they are immediately garbage-collected and never fire.
        self._shortcuts: list[QShortcut] = []
        pairs = [
            ("Ctrl+1",       lambda: self._navigate_to(0)),    # Trading
            ("Ctrl+2",       lambda: self._navigate_to(1)),    # AutoTrader
            ("Ctrl+3",       lambda: self._navigate_to(2)),    # ML Train
            ("Ctrl+4",       lambda: self._navigate_to(3)),    # Risk
            ("Ctrl+5",       lambda: self._navigate_to(4)),    # Backtest
            ("Ctrl+6",       lambda: self._navigate_to(5)),    # Journal
            ("Ctrl+7",       lambda: self._navigate_to(6)),    # Strategy
            ("Ctrl+8",       lambda: self._navigate_to(7)),    # Connections
            ("Ctrl+9",       lambda: self._navigate_to(8)),    # Settings
            ("Ctrl+0",       lambda: self._navigate_to(9)),    # Help
            ("F1",           lambda: self._navigate_to(9)),    # Help
            ("F2",           lambda: self._navigate_to(11)),   # Reports
            ("Ctrl+Shift+W", lambda: self._navigate_to(12)),   # Market Watch
            ("Ctrl+Shift+M", lambda: self._navigate_to(13)),   # ML Tools
            ("Ctrl+Shift+S", lambda: self._navigate_to(10)),   # Simulation
            ("F11",          self._toggle_fullscreen),
            ("Ctrl+\\",      self._toggle_nav),                # Slide nav sidebar
            ("Ctrl+B",       self._toggle_order_book),         # Order Book dock
            ("Ctrl+Shift+B", self._toggle_trading_panel),      # Trading Panel dock
            ("Ctrl+Shift+R", self._restore_trading_docks),     # Restore docks
            ("Ctrl+L",       self._toggle_intel_log),          # Intel Log dock
            ("Ctrl+,",       lambda: self._navigate_to(8)),    # Settings (alt)
            ("Ctrl+Shift+A", self._at_take_aim),               # AutoTrader: Take Aim
            ("Ctrl+Shift+E", self._at_manual_exit),            # AutoTrader: Exit Trade
            ("Ctrl+Shift+N", self._at_scan_now),               # AutoTrader: Scan Now
            ("Ctrl+T",       self._start_training),            # ML: Start Training
            ("Ctrl+Shift+T", self._stop_training),             # ML: Stop Training
            ("Ctrl+R",       self._reload_model),              # ML: Reload Model
            ("Ctrl+I",       self._run_integrity_check),       # ML: Integrity Check
            ("Ctrl+Shift+X", self._cancel_all_orders),         # Trading: Cancel All
            ("Ctrl+Shift+C", self._check_connections),         # Network: Check All
            ("Ctrl+Shift+D", self._open_system_status_popup),  # Network: System Status
            ("Ctrl+Shift+V", lambda: self._open_sim_tab(0)),   # Sim: Twin
            ("Ctrl+Alt+M",   lambda: self._open_sim_tab(1)),   # Sim: Mutation Lab
            ("Ctrl+Shift+F", lambda: self._open_sim_tab(2)),   # Sim: Safety Scanner
        ]
        for key, fn in pairs:
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(fn)
            self._shortcuts.append(sc)   # keep reference to prevent GC

    # ──────────────────────────────────────────────────────────────────
    # Signal connections
    # ──────────────────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_toast"):
            self._toast._reposition()

    # Map intel-log source prefixes → nav page index for alert flashing
    _INTEL_PAGE_MAP: dict[str, int] = {
        "autotrader": 1, "auto_trader": 1, "pingpong": 1, "arbitrage": 1,
        "mltrainer": 2,  "trainer": 2,     "model": 2,
        "risk": 3,       "drawdown": 3,    "montecarlo": 3,
        "backtest": 4,
        "journal": 5,    "trade_journal": 5,
        "strategy": 6,
        "connection": 7, "binance": 7,     "websocket": 7,
        "settings": 8,   "config": 8,
        "simulation": 10, "simtwin": 10,
        "report": 11,    "tax": 11,
        "market": 12,    "cascade": 12,    "whale": 12,    "funding": 12,
        "ml_central": 13, "mlcentral": 13, "scanner": 13,
    }

    def _on_intel_for_toast(self, entry) -> None:
        """Called by IntelLogger from any thread; surfaces ERROR/WARNING as toasts
        and flashes the nav icon for the source panel."""
        if entry.level in ("ERROR", "WARNING"):
            # Suppress portfolio/auth errors when the user has ignored the missing key
            if getattr(self, "_binance_api_ignored", False):
                msg_lower = entry.message.lower()
                if "portfolio refresh" in msg_lower or "401" in msg_lower or "unauthorized" in msg_lower:
                    return
            self._toast_signal.emit(entry.message[:160], entry.level)
            # Flash the nav icon for the relevant panel (best-effort source match)
            src = getattr(entry, "source", "").lower().replace(" ", "_")
            page = next(
                (pg for key, pg in self._INTEL_PAGE_MAP.items() if key in src),
                None,
            )
            if page is not None and hasattr(self, "nav"):
                # Schedule on the GUI thread
                QTimer.singleShot(0, lambda p=page: self.nav.set_alert(p, True))

    def _connect_signals(self) -> None:
        if self._engine:
            self._engine.on("heartbeat",   self._on_heartbeat)
            self._engine.on("trade",       self._on_trade_event)
            self._engine.on("signal",      self._on_signal_event)
            self._engine.on("mode_change", self._on_mode_change)
        if self._predictor:
            self._predictor.on_signal(self._on_ml_signal)
        if self._auto_trader:
            self._auto_trader.on_state_change(
                lambda state: QTimer.singleShot(
                    0, lambda s=state: self.status_bar.set_at_state(s.value)
                )
            )
        if self._new_token_watcher:
            try:
                def _on_launch(sig):
                    self._intel.ml("NewTokenWatcher",
                        f"🚀 {sig.symbol} bar {sig.bar_num}: "
                        f"{sig.action} ({sig.confidence:.0%}) – {sig.reason}")
                    if self._voice and sig.action in ("ENTER_LONG","EXIT_LONG"):
                        self._voice.speak_alert(
                            f"Launch {sig.action.replace('_',' ')} {sig.symbol}"
                        )
                self._new_token_watcher.on_signal(_on_launch)
            except Exception:
                pass

        # Wire RegimeDetector regime changes → intel log
        if self._regime_detector:
            try:
                def _on_regime(snap):
                    self._intel.system("RegimeDetector",
                        f"Regime → {snap.regime}  "
                        f"conf={snap.confidence:.0%}  "
                        f"bull_prob={snap.bull_probability:.0%}  "
                        f"pos_mult={snap.position_multiplier:.2f}x")
                    QTimer.singleShot(0, lambda s=snap: self._on_regime_changed(s))
                self._regime_detector.on_regime_change(_on_regime)
            except Exception:
                pass

        # Wire MTFConfluenceFilter → intel log
        if self._mtf_filter:
            try:
                def _on_confluence(sig):
                    self._intel.signal("MTFConfluence",
                        f"{sig.symbol}  {sig.direction}  "
                        f"score={sig.confluence_pct:.0%}  "
                        f"passes={sig.passes_filter}")
                self._mtf_filter.on_confluence(_on_confluence)
            except Exception:
                pass

        # Wire EnsembleAggregator → intel log + ML page
        if self._ensemble:
            try:
                def _on_ensemble(sig):
                    self._intel.signal("Ensemble",
                        f"{sig.symbol}  {sig.final_signal}  "
                        f"conf={sig.final_confidence:.0%}  "
                        f"buy={sig.buy_score:.2f} sell={sig.sell_score:.2f}")
                    if hasattr(self.ml_page, "add_signal"):
                        self.ml_page.add_signal({
                            "symbol": sig.symbol,
                            "action": sig.final_signal,
                            "confidence": sig.final_confidence,
                            "source": "Ensemble",
                        })
                self._ensemble.on_signal(_on_ensemble)
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────
    # Timers
    # ──────────────────────────────────────────────────────────────────

    def _start_timers(self) -> None:
        QTimer(self, interval=3000, timeout=self._refresh_orders).start()
        QTimer(self, interval=5000, timeout=self._update_stats).start()

    # ──────────────────────────────────────────────────────────────────
    # Navigation
    # ──────────────────────────────────────────────────────────────────

    def _navigate_to(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav.set_active(index)
        # Clear alert flash for this page once user navigates to it
        self.nav.set_alert(index, False)

    def _toggle_nav(self) -> None:
        """Slide the navigation sidebar in or out with an animated transition."""
        if self._nav_collapsed:
            # Expand: animate from 0 → _WIDTH
            self._nav_anim.setStartValue(0)
            self._nav_anim.setEndValue(NavSidebar._WIDTH)
        else:
            # Collapse: animate from _WIDTH → 0
            self._nav_anim.setStartValue(NavSidebar._WIDTH)
            self._nav_anim.setEndValue(0)
        self._nav_collapsed = not self._nav_collapsed
        self._nav_anim.start()

    @staticmethod
    def _tab_index_by_title(tab_widget, title: str) -> int:
        """Return the index of the first tab whose text contains *title*, or -1."""
        for i in range(tab_widget.count()):
            if title in tab_widget.tabText(i):
                return i
        return -1

    def _open_sim_tab(self, tab_index: int) -> None:
        """Navigate to simulation page and select a specific tab."""
        self._navigate_to(10)
        try:
            if hasattr(self, "simulation_page") and hasattr(self.simulation_page, "setCurrentIndex"):
                self.simulation_page.setCurrentIndex(tab_index)
        except Exception:
            pass

    def _open_at_tab(self, tab_title: str) -> None:
        """Navigate to AutoTrader page and select the tab matching *tab_title*."""
        self._navigate_to(1)
        try:
            if hasattr(self, "at_page") and hasattr(self.at_page, "setCurrentIndex"):
                idx = self._tab_index_by_title(self.at_page, tab_title)
                if idx >= 0:
                    self.at_page.setCurrentIndex(idx)
        except Exception:
            pass

    def _open_ml_tools_tab(self, tab_title: str) -> None:
        """Navigate to ML Tools page and select the tab matching *tab_title*."""
        self._navigate_to(13)
        try:
            if hasattr(self, "ml_tools_page") and hasattr(self.ml_tools_page, "setCurrentIndex"):
                idx = self._tab_index_by_title(self.ml_tools_page, tab_title)
                if idx >= 0:
                    self.ml_tools_page.setCurrentIndex(idx)
        except Exception:
            pass

    def _open_market_watch_tab(self, tab_index: int) -> None:
        """Navigate to Market Watch page and select a specific tab."""
        self._navigate_to(12)
        try:
            if hasattr(self, "market_watch_page") and hasattr(self.market_watch_page, "tabs"):
                self.market_watch_page.tabs.setCurrentIndex(tab_index)
        except Exception:
            pass

    def _open_settings_tab(self, tab_index: int) -> None:
        """Navigate to Settings page and select a specific tab."""
        self._navigate_to(8)
        try:
            if hasattr(self, "settings_page") and hasattr(self.settings_page, "setCurrentIndex"):
                self.settings_page.setCurrentIndex(tab_index)
        except Exception:
            pass

    def _open_layer(self, layer_num: int) -> None:
        """Navigate to Settings >> Layers and jump to a specific layer."""
        self._navigate_to(8)  # Settings page
        try:
            if hasattr(self, "settings_page"):
                # Find Layers tab in settings
                for i in range(self.settings_page.count()):
                    if "Layer" in self.settings_page.tabText(i):
                        self.settings_page.setCurrentIndex(i)
                        if hasattr(self, "layers_panel"):
                            self.layers_panel._jump_to_layer(layer_num)
                        break
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────
    # Event handlers
    # ──────────────────────────────────────────────────────────────────

    def _on_heartbeat(self, data: dict) -> None:
        metrics = data.get("metrics", {})
        self.trading_page.update_pnl(metrics)
        n   = metrics.get("trades_today", 0)
        pnl = metrics.get("pnl_today", 0)
        col = GREEN if pnl >= 0 else RED
        self.status_bar.trades_lbl.setText(f"TRADES: {n}")
        self.status_bar.pnl_lbl.setText(f"P&L: ${pnl:+,.2f}")
        self.status_bar.pnl_lbl.setStyleSheet(
            f"color:{col}; font-size:11px; padding:0 10px; font-family:monospace;"
        )

    def _on_trade_event(self, trade: dict) -> None:
        self._intel.trade("TradingEngine",
            f"{trade.get('side')} {trade.get('quantity')} "
            f"{trade.get('symbol')} @ {trade.get('price')}", trade)
        try:
            from api.webhooks import get_webhook_manager
            get_webhook_manager().emit_trade(trade)
        except Exception:
            pass

    def _on_signal_event(self, signal: dict) -> None:
        action = signal.get("action", signal.get("signal", ""))
        sym    = signal.get("symbol", "")
        conf   = signal.get("confidence", 0)
        price  = signal.get("price", 0)
        src    = signal.get("source", "TradingEngine")
        self._intel.signal(src,
            f"{action} {sym}  conf={conf:.1%}  price={price:,.4f}" if price else
            f"{action} {sym}  conf={conf:.1%}",
            signal)
        try:
            from api.webhooks import get_webhook_manager
            get_webhook_manager().emit_signal(signal)
        except Exception:
            pass

    def _on_regime_changed(self, snap) -> None:
        """Update risk page when market regime changes."""
        try:
            if hasattr(self.risk_page, "update_regime"):
                self.risk_page.update_regime(snap)
        except Exception:
            pass

    def _on_mode_change(self, data: dict) -> None:
        mode = str(data.get("new", "")).upper()
        self.status_bar.set_mode(mode)
        self._intel.system("TradingEngine", f"Engine mode → {mode}")

    def _on_ml_signal(self, signal: dict) -> None:
        if hasattr(self.ml_page, "add_signal"):
            self.ml_page.add_signal(signal)
        action = signal.get("action", "")
        conf   = signal.get("confidence", 0)
        sym    = signal.get("symbol", "")
        self._intel.signal("MLPredictor",
            f"{action} {sym}  conf={conf:.1%}  "
            f"price={signal.get('price',0):,.4f}", signal)
        try:
            from api.webhooks import get_webhook_manager
            get_webhook_manager().emit_signal(signal)
        except Exception:
            pass

    def _on_symbol_changed(self, symbol: str) -> None:
        self._current_symbol = symbol
        if self._predictor:
            self._predictor.add_symbol(symbol)
        if self._engine:
            self._engine.add_symbol(symbol)

    def _on_order_submitted(self, order: dict) -> None:
        if not self._engine:
            self._intel.warning("MainWindow", "Engine not available – demo mode")
            return
        from decimal import Decimal
        side = order["side"]
        if side == "BUY":
            result = self._engine.manual_buy(
                order["symbol"],
                Decimal(str(order["quantity"])),
                Decimal(str(order["price"])),
            )
        else:
            result = self._engine.manual_sell(
                order["symbol"],
                Decimal(str(order["quantity"])),
                Decimal(str(order["price"])),
            )
        if result:
            self._intel.trade("MainWindow",
                f"{side} {order['quantity']} {order['symbol']}", order)

    def _on_cancel_requested(self, symbol: str, order_id: str) -> None:
        if self._engine:
            ok = self._engine.manual_cancel(symbol, order_id)
            self._intel.trade("MainWindow",
                f"Order {'cancelled' if ok else 'cancel FAILED'}: {order_id}")

    # ──────────────────────────────────────────────────────────────────
    # Refresh
    # ──────────────────────────────────────────────────────────────────

    def _refresh_orders(self) -> None:
        if self._order_manager:
            orders = self._order_manager.get_open_orders()
            self.trading_page.update_active_orders(orders)

    def _update_stats(self) -> None:
        try:
            from utils.threading_manager import get_thread_manager
            s = get_thread_manager().system_stats()
            self.status_bar.cpu_lbl.setText(f"CPU: {s['cpu_pct']:.0f}%")
            self.status_bar.mem_lbl.setText(f"MEM: {s['mem_pct']:.0f}%")
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────
    # Action helpers
    # ──────────────────────────────────────────────────────────────────

    def _set_engine_mode(self, mode: str) -> None:
        if self._engine:
            from core.trading_engine import EngineMode
            self._engine.set_mode(EngineMode(mode))

    def _set_at_mode(self, mode: str) -> None:
        if self._auto_trader:
            from core.auto_trader import AutoTraderMode
            self._auto_trader.set_mode(AutoTraderMode(mode))
            self._intel.ml("MainWindow", f"AutoTrader → {mode}")

    def _at_take_aim(self) -> None:
        if self._auto_trader:
            ok = self._auto_trader.take_aim()
            self._intel.ml("MainWindow",
                "Take Aim" + (" approved" if ok else " – nothing pending"))

    def _at_manual_exit(self) -> None:
        if self._auto_trader:
            self._auto_trader.manual_exit()
            self._intel.ml("MainWindow", "Manual exit requested")

    def _at_scan_now(self) -> None:
        if self._market_scanner:
            threading.Thread(
                target=self._market_scanner.scan_now, daemon=True
            ).start()
            self._intel.ml("MainWindow", "Manual scan triggered")

    def _cancel_all_orders(self) -> None:
        reply = QMessageBox.question(
            self, "Cancel All Orders", "Cancel ALL open orders?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self._order_manager:
                self._order_manager.cancel_all(self._current_symbol)
                self._intel.trade("MainWindow", "All orders cancelled")

    def _start_training(self) -> None:
        if hasattr(self.ml_page, "_start_training"):
            self.ml_page._start_training()

    def _stop_training(self) -> None:
        if hasattr(self.ml_page, "_stop_training"):
            self.ml_page._stop_training()

    def _reload_model(self) -> None:
        if self._predictor:
            ok = self._predictor.reload_model()
            self._intel.ml("MainWindow",
                f"Model reload {'succeeded' if ok else 'failed – no active model'}")

    def _run_integrity_check(self) -> None:
        def _run():
            if self._cl:
                results = self._cl.integrity_checker.run_check(
                    self._active_symbols, intervals=["1h","4h"],
                )
                self._intel.ml("MainWindow",
                    f"Integrity: {results.get('passed',0)} OK  "
                    f"| {results.get('warnings',0)} warn  "
                    f"| {results.get('errors',0)} errors")
        threading.Thread(target=_run, daemon=True).start()

    def _generate_tax_report(self) -> None:
        if not self._tax_calc:
            return
        t = time.localtime()
        try:
            from tax.email_report import TaxEmailReporter
            path = TaxEmailReporter()._generate_pdf(
                t.tm_year, t.tm_mon,
                self._tax_calc.monthly_summary(t.tm_year, t.tm_mon)
            )
            self._intel.tax("MainWindow", f"Monthly report: {path}")
        except Exception as e:
            self._intel.error("MainWindow", f"Tax report error: {e}")

    def _generate_annual_tax(self) -> None:
        if not self._tax_calc:
            return
        try:
            from tax.uk_tax import UKTaxCalculator
            from tax.email_report import TaxEmailReporter
            path = TaxEmailReporter().generate_annual_report(
                UKTaxCalculator.current_tax_year()
            )
            self._intel.tax("MainWindow", f"Annual CGT report: {path}")
        except Exception as e:
            self._intel.error("MainWindow", f"Annual tax error: {e}")

    def _send_tax_email(self) -> None:
        t = time.localtime()
        try:
            from tax.email_report import TaxEmailReporter
            ok = TaxEmailReporter().generate_and_send_monthly(t.tm_year, t.tm_mon)
            self._intel.tax("MainWindow", f"Tax email {'sent' if ok else 'failed'}")
        except Exception as e:
            self._intel.error("MainWindow", f"Tax email error: {e}")

    def _check_connections(self) -> None:
        self._navigate_to(7)
        try:
            QTimer.singleShot(200, self.connections_page._check_all)
        except Exception:
            pass

    def _start_api_server(self) -> None:
        try:
            from api.server import get_api_server
            srv = get_api_server()
            srv.start(
                engine=self._engine, portfolio=self._portfolio,
                predictor=self._predictor, order_manager=self._order_manager,
                tax_calc=self._tax_calc,
            )
            self._intel.api("MainWindow", f"REST API at {srv.base_url}")
            QMessageBox.information(self, "API Server",
                f"REST API running at:\n{srv.base_url}")
        except Exception as e:
            self._intel.error("MainWindow", f"API server error: {e}")

    def _show_api_docs(self) -> None:
        try:
            from api.server import get_api_server
            base = get_api_server().base_url
        except Exception:
            base = "http://localhost:8080"
        QMessageBox.information(self, "API Endpoints",
            f"Base: {base}\n\n"
            "GET  /api/v1/status\n"
            "GET  /api/v1/portfolio\n"
            "GET  /api/v1/signals?symbol=BTCUSDT\n"
            "POST /api/v1/order\n"
            "GET  /api/v1/log\n"
            "POST /api/v1/webhook/register\n\n"
            "Auth: Bearer <first 16 chars of API key>")

    def _show_about(self) -> None:
        self._navigate_to(9)

    def _open_system_status_popup(self) -> None:
        """Open (or raise) the live System Status / Grafana dashboard popup."""
        try:
            from ui.system_status_widget import SystemStatusDialog
            if not hasattr(self, "_sys_status_dlg") or \
               self._sys_status_dlg is None or \
               not self._sys_status_dlg.isVisible():
                self._sys_status_dlg = SystemStatusDialog(self)
                self._sys_status_dlg.show()
            else:
                self._sys_status_dlg.raise_()
                self._sys_status_dlg.activateWindow()
        except Exception as exc:
            self._intel.error("MainWindow", f"System Status popup error: {exc}")

    def _open_coingecko_setup(self) -> None:
        """Open Settings page and jump to the CoinGecko section."""
        self._navigate_to(8)          # Settings page
        try:
            # Find the System tab (index 0) and scroll to CoinGecko section
            if hasattr(self, "settings_page"):
                for i in range(self.settings_page.count()):
                    if "System" in self.settings_page.tabText(i):
                        self.settings_page.setCurrentIndex(i)
                        tab_widget = self.settings_page.widget(i)
                        if hasattr(tab_widget, "_scroll_to_coingecko"):
                            tab_widget._scroll_to_coingecko()
                        break
        except Exception:
            pass

    def _add_chart_tab(self) -> None:
        try:
            self.trading_page.chart_panel._prompt_add_tab()
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────
    # View toggles
    # ──────────────────────────────────────────────────────────────────

    def _toggle_intel_log(self) -> None:
        self.intel_dock.setVisible(not self.intel_dock.isVisible())

    def _toggle_order_book(self) -> None:
        """Show/hide the Order Book dock on the Trading page."""
        dock = getattr(self.trading_page, "_ob_dock", None)
        if dock:
            dock.setVisible(not dock.isVisible())

    def _toggle_trading_panel(self) -> None:
        """Show/hide the Trading Panel dock on the Trading page."""
        dock = getattr(self.trading_page, "_tp_dock", None)
        if dock:
            dock.setVisible(not dock.isVisible())

    def _restore_trading_docks(self) -> None:
        """Restore all minimised/hidden docks on the Trading page to the right area."""
        page = self.trading_page
        inner = getattr(page, "_inner", None)
        if not inner:
            return
        for dock in (getattr(page, "_ob_dock", None), getattr(page, "_tp_dock", None)):
            if dock:
                inner.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
                dock.show()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    # ──────────────────────────────────────────────────────────────────
    # Close
    # ──────────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        reply = QMessageBox.question(
            self, "Exit BinanceML Pro",
            "Stop all services and exit?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for svc in (self._auto_trader, self._market_scanner,
                        getattr(self, "_market_pulse", None),
                        self._engine, self._predictor, self._cl):
                try:
                    if svc:
                        svc.stop()
                except Exception:
                    pass
            self._intel.system("MainWindow", "Shutdown complete.")
            event.accept()
        else:
            event.ignore()


# ══════════════════════════════════════════════════════════════════════════════
# Module-level helpers
# ══════════════════════════════════════════════════════════════════════════════

def _vsep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setFixedWidth(1)
    f.setStyleSheet(f"background:{BORDER};")
    return f


def _placeholder(title: str, msg: str) -> QWidget:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl = QLabel(f"{title}\n\n{msg}")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(f"color:{FG2}; font-size:16px;")
    layout.addWidget(lbl)
    return w
