"""
BinanceML Pro – Futuristic Trading Desk Main Window

Layout:
  ┌─────────────────────────────────────────────────────────────────────┐
  │  HEADER BAR:  [Logo] [Brand] [Ticker Strip]  [Health dots] [Time]  │
  ├──────┬──────────────────────────────────────────────────────────────┤
  │      │                                                               │
  │ NAV  │              STACKED CONTENT PANELS                          │
  │ SIDE │  0: Trading  1: AutoTrader  2: ML  3: Risk                   │
  │ BAR  │  4: Connections  5: Settings  6: Help                        │
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

from PyQt6.QtCore import Qt, QTimer, QSize, QPoint, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSplitter, QSizePolicy, QStackedWidget,
    QDockWidget, QMessageBox, QComboBox, QStatusBar, QMenu,
    QTabWidget, QInputDialog,
)

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
        "• Overlay selector: EMA/SMA/Bollinger/RSI/MACD and more\n"
        "• Order entry: LIMIT / MARKET / STOP / OCO with SL+TP\n"
        "• Active Orders table with one-click cancel\n"
        "• Portfolio tab shows free/locked balances in USD/GBP"),
    1: ("AutoTrader",
        "Fully autonomous scan → aim → enter → monitor → exit cycle.\n\n"
        "• SEMI_AUTO: recommendation shown, press Take Aim to fire\n"
        "• FULL_AUTO: executes automatically when confidence ≥ threshold\n"
        "• Top-5 Profit and Top-5 R:R tables from market scan\n"
        "• Active Trade panel with live P&L vs SL/TP levels\n"
        "• Cooldown 15 min after stop-loss, circuit breaker guard"),
    2: ("ML Training",
        "LSTM + Transformer model training and live signal feed.\n\n"
        "• Start/Stop 48-hour full training session\n"
        "• Continuous Learner retrains every 24 hours automatically\n"
        "• Per-token models trained for each USDT pair\n"
        "• Live signal stream with confidence scores\n"
        "• Whale detection and sentiment analysis feeds"),
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
}


# ══════════════════════════════════════════════════════════════════════════════
# NAV BUTTON
# ══════════════════════════════════════════════════════════════════════════════

class NavButton(QPushButton):
    """
    Sidebar navigation button.
    • Mouse enter + 5 s  → QToolTip with panel title
    • Mouse enter + 10 s → contextual help QMessageBox
    • Mouse leave        → cancel both timers
    """

    clicked_index = pyqtSignal(int)

    def __init__(self, index: int, icon_name: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self._index     = index
        self._icon_name = icon_name
        self._label     = label

        self.setObjectName("nav_btn")
        self.setFixedSize(64, 64)
        self.setText(label)
        self._set_icon(FG2)

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

        self.clicked.connect(lambda: self.clicked_index.emit(self._index))

    def _set_icon(self, color: str) -> None:
        self.setIcon(svg_icon(self._icon_name, color, 22))
        self.setIconSize(QSize(22, 22))

    def set_active(self, active: bool) -> None:
        self._set_icon(ACCENT if active else FG2)
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, event) -> None:
        self._set_icon(FG1)
        self._tip_timer.start()
        self._pop_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_icon(FG2)
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
    """Logo | Brand | Ticker strip | Health dots | Clock."""

    symbol_changed = pyqtSignal(str)

    def __init__(self, symbols: list[str], parent=None) -> None:
        super().__init__(parent)
        self._symbols = symbols
        self.setFixedHeight(46)
        self.setStyleSheet(
            f"HeaderBar {{ background:{BG0}; border-bottom:1px solid {BORDER2}; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(0)

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
    (0, "trading",      "TRADE"),
    (1, "autotrader",   "AUTO"),
    (2, "ml",           "ML"),
    (3, "risk",         "RISK"),
    (4, "backtest",     "BT"),
    (5, "journal",      "JNL"),
    (6, "strategy",     "STRAT"),
    (7, "connections",  "NET"),
    (8, "settings",     "CFG"),
    (9, "help",         "HELP"),
]


class NavSidebar(QFrame):
    page_requested = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(64)
        self.setStyleSheet(
            f"NavSidebar {{ background:{BG0}; border-right:1px solid {BORDER}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._buttons: list[NavButton] = []
        for idx, icon, label in _NAV_ITEMS:
            btn = NavButton(idx, icon, label)
            btn.clicked_index.connect(self._on_nav)
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
            self._buttons.append(btn)

        layout.addStretch()

    def _on_nav(self, index: int) -> None:
        for btn in self._buttons:
            btn.set_active(btn._index == index)
        self.page_requested.emit(index)

    def set_active(self, index: int) -> None:
        self._on_nav(index)


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

    def __init__(self, default_symbols: list[str], parent=None) -> None:
        super().__init__(parent)
        self._default_symbols = default_symbols
        self._chart_widgets: dict[str, QWidget] = {}
        self._active_overlays: set[str] = {"EMA 20", "EMA 50", "Volume Profile"}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar row ───────────────────────────────────────────────
        ctrl = QFrame()
        ctrl.setFixedHeight(36)
        ctrl.setStyleSheet(
            f"background:{BG0}; border-bottom:1px solid {BORDER};"
        )
        ctl = QHBoxLayout(ctrl)
        ctl.setContentsMargins(8, 0, 8, 0)
        ctl.setSpacing(8)

        # Interval
        ctl.addWidget(QLabel("Interval:"))
        self.interval_combo = QComboBox()
        self.interval_combo.setFixedWidth(70)
        for iv in ["1m","3m","5m","15m","30m","1h","4h","1d","1w"]:
            self.interval_combo.addItem(iv)
        self.interval_combo.setCurrentText("1h")
        self.interval_combo.currentTextChanged.connect(self._on_interval_changed)
        ctl.addWidget(self.interval_combo)

        ctl.addWidget(_vsep())

        # Overlay pulldown
        ctl.addWidget(QLabel("Overlays:"))
        self.overlay_btn = QPushButton("EMA20, EMA50, Volume ▾")
        self.overlay_btn.setFixedWidth(180)
        self.overlay_btn.setFixedHeight(26)
        self.overlay_btn.setStyleSheet(f"""
            QPushButton {{
                background:{BG4}; color:{FG1}; border:1px solid {BORDER2};
                border-radius:4px; font-size:11px; padding:0 8px; text-align:left;
            }}
            QPushButton:hover {{ color:{ACCENT}; border-color:{ACCENT}; }}
        """)
        self.overlay_btn.clicked.connect(self._show_overlay_menu)
        ctl.addWidget(self.overlay_btn)

        ctl.addWidget(_vsep())

        # Add tab button
        add_btn = QPushButton()
        add_btn.setIcon(svg_icon("scan", ACCENT, 13))
        add_btn.setIconSize(QSize(13, 13))
        add_btn.setFixedSize(28, 28)
        add_btn.setToolTip("Add chart tab  (Ctrl++)")
        add_btn.setStyleSheet(
            f"background:{BG4}; border:1px solid {BORDER}; border-radius:4px;"
        )
        add_btn.clicked.connect(self._prompt_add_tab)
        ctl.addWidget(add_btn)

        ctl.addStretch()

        # Current symbol label
        self.sym_lbl = QLabel("BTCUSDT")
        self.sym_lbl.setStyleSheet(
            f"color:{ACCENT}; font-weight:700; font-size:13px; "
            f"font-family:monospace; padding-right:8px;"
        )
        ctl.addWidget(self.sym_lbl)

        layout.addWidget(ctrl)

        # ── Chart tabs ────────────────────────────────────────────────
        self.chart_tabs = QTabWidget()
        self.chart_tabs.setTabsClosable(True)
        self.chart_tabs.setMovable(True)
        self.chart_tabs.tabCloseRequested.connect(self._close_tab)
        self.chart_tabs.currentChanged.connect(self._on_tab_changed)
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
            cw = ChartWidget()
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


# ══════════════════════════════════════════════════════════════════════════════
# TRADING PAGE
# ══════════════════════════════════════════════════════════════════════════════

class TradingPage(QWidget):
    order_submitted  = pyqtSignal(dict)
    cancel_requested = pyqtSignal(str, str)
    symbol_changed   = pyqtSignal(str)

    def __init__(self, default_symbols: list[str], parent=None) -> None:
        super().__init__(parent)
        self._default_symbols = default_symbols
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        outer = QSplitter(Qt.Orientation.Horizontal)

        # Left: multi-chart
        self.chart_panel = MultiChartPanel(self._default_symbols)
        self.chart_panel.symbol_changed.connect(self.symbol_changed)
        outer.addWidget(self.chart_panel)

        # Right: order book + trading panel
        right_split = QSplitter(Qt.Orientation.Vertical)

        from ui.orderbook_widget import OrderBookWidget
        self.orderbook = OrderBookWidget(self._default_symbols[0])
        right_split.addWidget(self.orderbook)

        from ui.trading_panel import TradingPanel
        self.trading_panel = TradingPanel()
        self.trading_panel.order_submitted.connect(self.order_submitted)
        self.trading_panel.cancel_requested.connect(self.cancel_requested)
        right_split.addWidget(self.trading_panel)
        right_split.setSizes([300, 420])

        outer.addWidget(right_split)
        outer.setSizes([1000, 420])
        layout.addWidget(outer)

        self.symbol_changed.connect(self.orderbook.set_symbol)

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


class TradingStatusBar(QStatusBar):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(26)

        def lbl(text: str, col: str = FG2) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(
                f"color:{col}; font-size:10px; padding:0 8px; font-family:monospace;"
            )
            return l

        self.mode_lbl     = lbl("MODE: MANUAL", YELLOW)
        self.at_lbl       = lbl("AT: IDLE")
        self.trades_lbl   = lbl("TRADES: 0")
        self.pnl_lbl      = lbl("P&L: $0.00")
        self.api_lbl      = lbl("● API")
        self.db_lbl       = lbl("● DB")
        self.redis_lbl    = lbl("● RDS")

        for w in [self.mode_lbl, _vsep(), self.at_lbl, _vsep(),
                  self.trades_lbl, _vsep(), self.pnl_lbl, _vsep(),
                  self.api_lbl, _vsep(), self.db_lbl, _vsep(),
                  self.redis_lbl, _vsep()]:
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

    def set_mode(self, mode: str) -> None:
        col = {"AUTO": GREEN, "MANUAL": YELLOW, "HYBRID": ACCENT,
               "PAPER": ACCENT2, "PAUSED": RED}.get(mode.upper(), FG1)
        self.mode_lbl.setText(f"MODE: {mode.upper()}")
        self.mode_lbl.setStyleSheet(
            f"color:{col}; font-size:10px; padding:0 8px; font-family:monospace;"
        )

    def set_at_state(self, state: str) -> None:
        col = {"idle": FG2, "scanning": ACCENT, "aiming": YELLOW,
               "entering": GREEN, "monitoring": GREEN,
               "exiting": YELLOW, "cooldown": RED}.get(state, FG2)
        self.at_lbl.setText(f"AT: {state.upper()}")
        self.at_lbl.setStyleSheet(
            f"color:{col}; font-size:10px; padding:0 8px; font-family:monospace;"
        )

    def set_service(self, name: str, ok: bool) -> None:
        mapping = {"api": self.api_lbl, "db": self.db_lbl, "redis": self.redis_lbl}
        lbl = mapping.get(name)
        if lbl:
            col = GREEN if ok else RED
            tag = {"api": "API", "db": "DB", "redis": "RDS"}.get(name, name.upper())
            lbl.setText(f"● {tag}")
            lbl.setStyleSheet(
                f"color:{col}; font-size:10px; padding:0 8px; font-family:monospace;"
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
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._engine             = engine
        self._portfolio          = portfolio
        self._predictor          = predictor
        self._order_manager      = order_manager
        self._trainer            = trainer
        self._tax_calc           = tax_calc
        self._cl                 = continuous_learner
        self._whale_watcher      = whale_watcher
        self._token_ml           = token_ml
        self._sentiment          = sentiment
        self._port_opt           = port_opt
        self._backtester         = backtester
        self._voice              = voice
        self._telegram           = telegram
        self._new_token_watcher  = new_token_watcher
        self._regime_detector    = regime_detector
        self._mtf_filter         = mtf_filter
        self._signal_council     = signal_council
        self._ensemble           = ensemble
        self._dynamic_risk       = dynamic_risk
        self._monte_carlo        = monte_carlo
        self._walk_forward       = walk_forward
        self._trade_journal      = trade_journal
        self._market_scanner     = market_scanner
        self._auto_trader        = auto_trader
        self._market_pulse       = market_pulse
        self._forecast_tracker   = forecast_tracker
        self._archive_downloader = archive_downloader
        self._data_collector     = data_collector
        self._ping_pong          = ping_pong
        self._strategy_manager   = strategy_manager

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

    # ──────────────────────────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self.header = HeaderBar(self._active_symbols)
        self.header.symbol_changed.connect(self._on_symbol_changed)
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

        # Toast notification overlay (floats over the window)
        self._toast = ToastOverlay(central)

        # Intel Log dock
        from ui.intel_log_widget import IntelLogWidget
        self.intel_log  = IntelLogWidget()
        self.intel_dock = QDockWidget("Intel Log", self)
        self.intel_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea |
            Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.intel_dock.setWidget(self.intel_log)
        self.intel_dock.setMinimumHeight(160)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.intel_dock)

    def _build_trading_page(self) -> None:
        self.trading_page = TradingPage(self._active_symbols)
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
        from ui.system_settings_widget import SystemSettingsWidget
        self.settings_page = SystemSettingsWidget()
        self.settings_page.settings_saved.connect(
            lambda: self._intel.system("Settings", "Configuration saved.")
        )
        self.stack.addWidget(self.settings_page)

    def _build_help_page(self) -> None:
        from ui.help_widget import HelpWidget
        self.help_page = HelpWidget()
        self.stack.addWidget(self.help_page)

    # ──────────────────────────────────────────────────────────────────
    # Menu
    # ──────────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # File
        fm = mb.addMenu("&File")
        fm.addAction(self._act("Settings", lambda: self._navigate_to(8), "Ctrl+,"))
        fm.addSeparator()
        fm.addAction(self._act("Exit", self.close, "Ctrl+Q"))

        # View
        vm = mb.addMenu("&View")
        labels = [
            "Trading", "AutoTrader", "ML", "Risk",
            "Backtest", "Trade Journal", "Strategy Builder",
            "Connections", "Settings", "Help",
        ]
        for i, lbl in enumerate(labels):
            sc = f"Ctrl+{i+1}" if i < 9 else ""
            vm.addAction(self._act(lbl, lambda _, idx=i: self._navigate_to(idx), sc))
        vm.addSeparator()
        vm.addAction(self._act("Toggle Intel Log",   self._toggle_intel_log,   "Ctrl+L"))
        vm.addAction(self._act("Toggle Order Book",  self._toggle_order_book,  "Ctrl+B"))
        vm.addAction(self._act("Add Chart Tab",      self._add_chart_tab,      "Ctrl++"))
        vm.addAction(self._act("Toggle Fullscreen",  self._toggle_fullscreen,  "F11"))

        # Trading
        tm = mb.addMenu("&Trading")
        for mode in ["Manual","Auto","Hybrid","Paper","Paused"]:
            tm.addAction(self._act(f"{mode} Mode",
                lambda _, m=mode: self._set_engine_mode(m.lower())))
        tm.addSeparator()
        tm.addAction(self._act("Cancel All Orders", self._cancel_all_orders, "Ctrl+Shift+X"))
        tm.addSeparator()

        at_menu = tm.addMenu("🤖 AutoTrader")
        at_menu.addAction(self._act("Semi-Auto Mode",    lambda: self._set_at_mode("semi_auto")))
        at_menu.addAction(self._act("Full-Auto Mode",    lambda: self._set_at_mode("full_auto")))
        at_menu.addSeparator()
        at_menu.addAction(self._act("🎯 Take Aim",       self._at_take_aim,    "Ctrl+Shift+A"))
        at_menu.addAction(self._act("🛑 Exit Trade",     self._at_manual_exit, "Ctrl+Shift+E"))
        at_menu.addAction(self._act("🔭 Scan Now",       self._at_scan_now,    "Ctrl+Shift+N"))

        # ML
        mlm = mb.addMenu("&ML")
        mlm.addAction(self._act("Start Training",       self._start_training,       "Ctrl+T"))
        mlm.addAction(self._act("Stop Training",        self._stop_training,        "Ctrl+Shift+T"))
        mlm.addSeparator()
        mlm.addAction(self._act("Reload Model",         self._reload_model,         "Ctrl+R"))
        mlm.addAction(self._act("Data Integrity Check", self._run_integrity_check,  "Ctrl+I"))

        # Tax
        taxm = mb.addMenu("&Tax")
        taxm.addAction(self._act("Monthly Report",      self._generate_tax_report))
        taxm.addAction(self._act("Annual CGT Summary",  self._generate_annual_tax))
        taxm.addAction(self._act("Send Email Now",      self._send_tax_email))

        # Network
        netm = mb.addMenu("&Network")
        netm.addAction(self._act("Check All Connections", self._check_connections, "Ctrl+Shift+C"))
        netm.addAction(self._act("Start REST API Server", self._start_api_server))
        netm.addAction(self._act("View API Endpoints",    self._show_api_docs))

        # Help
        hm = mb.addMenu("&Help")
        hm.addAction(self._act("Help Panel", lambda: self._navigate_to(9), "F1"))
        hm.addAction(self._act("About",      self._show_about))

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
        pairs = [
            ("Ctrl+1", lambda: self._navigate_to(0)),
            ("Ctrl+2", lambda: self._navigate_to(1)),
            ("Ctrl+3", lambda: self._navigate_to(2)),
            ("Ctrl+4", lambda: self._navigate_to(3)),
            ("Ctrl+5", lambda: self._navigate_to(4)),
            ("Ctrl+6", lambda: self._navigate_to(5)),
            ("Ctrl+7", lambda: self._navigate_to(6)),
            ("Ctrl+8", lambda: self._navigate_to(7)),
            ("Ctrl+9", lambda: self._navigate_to(8)),
            ("F11",    self._toggle_fullscreen),
            ("F1",     lambda: self._navigate_to(9)),
        ]
        for key, fn in pairs:
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(fn)

    # ──────────────────────────────────────────────────────────────────
    # Signal connections
    # ──────────────────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_toast"):
            self._toast._reposition()

    def _on_intel_for_toast(self, entry) -> None:
        """Called by IntelLogger from any thread; only surfaces ERROR/WARNING as toasts."""
        if entry.level in ("ERROR", "WARNING"):
            self._toast_signal.emit(entry.message[:160], entry.level)

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
            f"color:{col}; font-size:10px; padding:0 8px; font-family:monospace;"
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
        QTimer.singleShot(200, self.connections_page._check_all)

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

    def _add_chart_tab(self) -> None:
        self.trading_page.chart_panel._prompt_add_tab()

    # ──────────────────────────────────────────────────────────────────
    # View toggles
    # ──────────────────────────────────────────────────────────────────

    def _toggle_intel_log(self) -> None:
        self.intel_dock.setVisible(not self.intel_dock.isVisible())

    def _toggle_order_book(self) -> None:
        ob = self.trading_page.orderbook
        ob.setVisible(not ob.isVisible())

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
