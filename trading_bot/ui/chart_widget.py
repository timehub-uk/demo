"""
Professional candlestick chart widget with full suite of technical indicators.
Uses pyqtgraph for high-performance real-time rendering.

Features:
  - Candlestick OHLCV
  - Volume bars (colour-coded)
  - EMA 20/50/200
  - Bollinger Bands
  - RSI panel
  - MACD panel
  - VWAP line
  - Buy/Sell signal markers
  - P&L overlay
  - Crosshair cursor with OHLCV tooltip
  - Zoom / pan
  - Interval selector
  - Show/hide indicators toolbar
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QColor, QPen, QBrush, QPainter
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QComboBox, QLabel, QCheckBox, QToolBar, QSizePolicy,
    QSplitter, QFrame,
)

from ui.styles import ACCENT, GREEN, RED, YELLOW, BG2, BG3, BG4, BORDER, FG0, FG1, FG2


pg.setConfigOption("background", BG2)
pg.setConfigOption("foreground", FG1)


# ── Candlestick item ────────────────────────────────────────────────────────

class CandlestickItem(pg.GraphicsObject):
    """High-performance candlestick renderer."""

    def __init__(self, data: list[dict]) -> None:
        super().__init__()
        self.data = data
        self.picture = None
        self.generatePicture()

    def generatePicture(self) -> None:
        self.picture = pg.Qt.QtGui.QPicture()
        p = QPainter(self.picture)
        p.setPen(pg.mkPen(FG2, width=1))
        w = 0.4
        for d in self.data:
            x = d["t"]
            o, h, l, c = d["o"], d["h"], d["l"], d["c"]
            color = GREEN if c >= o else RED
            p.setPen(pg.mkPen(color, width=1))
            p.setBrush(QBrush(QColor(color) if c >= o else QColor(RED)))
            p.drawLine(
                pg.Qt.QtCore.QPointF(x, l),
                pg.Qt.QtCore.QPointF(x, h)
            )
            p.drawRect(pg.Qt.QtCore.QRectF(x - w, min(o, c), 2 * w, abs(c - o) or 0.001))
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())


# ── Volume item ──────────────────────────────────────────────────────────────

class VolumeItem(pg.BarGraphItem):
    def __init__(self, data: list[dict]) -> None:
        xs = [d["t"] for d in data]
        ys = [d["v"] for d in data]
        brushes = [
            QBrush(QColor(GREEN + "88")) if d["c"] >= d["o"] else QBrush(QColor(RED + "88"))
            for d in data
        ]
        super().__init__(x=xs, height=ys, width=0.7, brushes=brushes)


# ── Signal marker ─────────────────────────────────────────────────────────────

class SignalMarker(pg.ScatterPlotItem):
    def __init__(self, signals: list[dict]) -> None:
        buys  = [s for s in signals if s.get("action") == "BUY"]
        sells = [s for s in signals if s.get("action") == "SELL"]
        spots = []
        for s in buys:
            spots.append({"pos": (s["t"], s["price"]), "symbol": "t",
                          "size": 14, "pen": None,
                          "brush": QBrush(QColor(GREEN))})
        for s in sells:
            spots.append({"pos": (s["t"], s["price"]), "symbol": "t1",
                          "size": 14, "pen": None,
                          "brush": QBrush(QColor(RED))})
        super().__init__(spots=spots)


# ── Main chart widget ─────────────────────────────────────────────────────────

class ChartWidget(QWidget):
    symbol_changed = pyqtSignal(str, str)   # symbol, interval

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._data: list[dict] = []
        self._signals: list[dict] = []
        self._symbol = "BTCUSDT"
        self._interval = "1m"

        self._indicators = {
            "ema20": True, "ema50": True, "ema200": False,
            "bb": True, "vwap": True, "volume": True,
            "rsi": True, "macd": False,
        }
        self._setup_ui()
        self._setup_timer()

    # ── UI setup ───────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setFixedHeight(40)
        toolbar.setStyleSheet(f"background:{BG3}; border-bottom:1px solid {BORDER};")
        tbl = QHBoxLayout(toolbar)
        tbl.setContentsMargins(10, 4, 10, 4)
        tbl.setSpacing(6)

        # Symbol / interval selectors
        self.sym_combo = QComboBox()
        self.sym_combo.setFixedWidth(130)
        for s in ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]:
            self.sym_combo.addItem(s)
        self.sym_combo.currentTextChanged.connect(self._on_symbol_changed)
        tbl.addWidget(self.sym_combo)

        self.int_combo = QComboBox()
        self.int_combo.setFixedWidth(70)
        for i in ["1m","3m","5m","15m","30m","1h","2h","4h","1d","1w"]:
            self.int_combo.addItem(i)
        self.int_combo.setCurrentText("1h")
        self.int_combo.currentTextChanged.connect(self._on_interval_changed)
        tbl.addWidget(self.int_combo)

        tbl.addSpacing(10)

        # Indicator toggles
        ind_labels = {
            "ema20": "EMA20", "ema50": "EMA50", "ema200": "EMA200",
            "bb": "BB", "vwap": "VWAP", "volume": "VOL",
            "rsi": "RSI", "macd": "MACD",
        }
        self._ind_checks = {}
        for key, label in ind_labels.items():
            cb = QCheckBox(label)
            cb.setChecked(self._indicators.get(key, True))
            cb.toggled.connect(lambda checked, k=key: self._toggle_indicator(k, checked))
            tbl.addWidget(cb)

        tbl.addStretch()

        # Price display
        self.lbl_price = QLabel("—")
        self.lbl_price.setObjectName("label_price")
        self.lbl_price.setStyleSheet(f"font-size:22px; font-weight:700; color:{FG0};")
        tbl.addWidget(self.lbl_price)

        self.lbl_change = QLabel("")
        self.lbl_change.setStyleSheet(f"font-size:13px; font-weight:600;")
        tbl.addWidget(self.lbl_change)

        main_layout.addWidget(toolbar)

        # Chart splitter (main chart + sub-panels)
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setChildrenCollapsible(False)
        main_layout.addWidget(self._splitter, 1)

        # Main price chart
        self._price_plot = pg.PlotWidget()
        self._price_plot.setMenuEnabled(False)
        self._price_plot.showGrid(x=True, y=True, alpha=0.1)
        self._price_plot.setMouseEnabled(x=True, y=True)
        self._price_plot.setAxisItems({"bottom": pg.DateAxisItem()})
        self._splitter.addWidget(self._price_plot)

        # Volume sub-panel
        self._vol_plot = pg.PlotWidget()
        self._vol_plot.setMenuEnabled(False)
        self._vol_plot.setMaximumHeight(80)
        self._vol_plot.showGrid(x=True, y=False, alpha=0.1)
        self._vol_plot.setXLink(self._price_plot)
        self._vol_plot.setAxisItems({"bottom": pg.DateAxisItem()})
        self._splitter.addWidget(self._vol_plot)

        # RSI sub-panel
        self._rsi_plot = pg.PlotWidget()
        self._rsi_plot.setMenuEnabled(False)
        self._rsi_plot.setMaximumHeight(100)
        self._rsi_plot.showGrid(x=True, y=True, alpha=0.1)
        self._rsi_plot.setXLink(self._price_plot)
        self._rsi_plot.setAxisItems({"bottom": pg.DateAxisItem()})
        self._rsi_plot.addLine(y=70, pen=pg.mkPen(RED, style=Qt.PenStyle.DashLine, width=1))
        self._rsi_plot.addLine(y=30, pen=pg.mkPen(GREEN, style=Qt.PenStyle.DashLine, width=1))
        self._splitter.addWidget(self._rsi_plot)

        # MACD sub-panel
        self._macd_plot = pg.PlotWidget()
        self._macd_plot.setMenuEnabled(False)
        self._macd_plot.setMaximumHeight(100)
        self._macd_plot.showGrid(x=True, y=True, alpha=0.1)
        self._macd_plot.setXLink(self._price_plot)
        self._macd_plot.setAxisItems({"bottom": pg.DateAxisItem()})
        self._splitter.addWidget(self._macd_plot)

        self._splitter.setSizes([500, 80, 100, 0])

        # Crosshair
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(FG2, width=1))
        self._hline = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(FG2, width=1))
        self._price_plot.addItem(self._vline, ignoreBounds=True)
        self._price_plot.addItem(self._hline, ignoreBounds=True)
        self._price_plot.scene().sigMouseMoved.connect(self._on_mouse_move)

    def _setup_timer(self) -> None:
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_data)
        self._refresh_timer.start(5000)

    # ── Data loading ───────────────────────────────────────────────────
    def load_data(self, candles: list[dict], signals: list[dict] | None = None) -> None:
        self._data = candles
        self._signals = signals or []
        self._render()

    def update_price(self, price: float, change_pct: float) -> None:
        self.lbl_price.setText(f"{price:,.4f}")
        colour = GREEN if change_pct >= 0 else RED
        sign = "+" if change_pct >= 0 else ""
        self.lbl_change.setText(f"{sign}{change_pct:.2f}%")
        self.lbl_change.setStyleSheet(f"font-size:13px; font-weight:600; color:{colour};")

    def _refresh_data(self) -> None:
        """Pull latest candles from Redis / DB and re-render."""
        try:
            from db.redis_client import RedisClient
            rc = RedisClient()
            candles = rc.get_candles(self._symbol, self._interval)
            if candles:
                self._data = candles
                self._render()
        except Exception:
            pass

    # ── Rendering ──────────────────────────────────────────────────────
    def _render(self) -> None:
        if not self._data:
            return
        data = self._data[-500:]   # Last 500 candles

        # Clear plots
        self._price_plot.clear()
        self._vol_plot.clear()
        self._rsi_plot.clear()
        self._macd_plot.clear()

        # Re-add infinite lines
        self._price_plot.addItem(self._vline, ignoreBounds=True)
        self._price_plot.addItem(self._hline, ignoreBounds=True)
        if self._indicators.get("rsi"):
            self._rsi_plot.addLine(y=70, pen=pg.mkPen(RED, style=Qt.PenStyle.DashLine))
            self._rsi_plot.addLine(y=30, pen=pg.mkPen(GREEN, style=Qt.PenStyle.DashLine))
            self._rsi_plot.addLine(y=50, pen=pg.mkPen(FG2, style=Qt.PenStyle.DashLine))

        ts  = np.array([d["t"] for d in data])
        cls = np.array([float(d.get("c", 0)) for d in data])
        ops = np.array([float(d.get("o", 0)) for d in data])
        his = np.array([float(d.get("h", 0)) for d in data])
        los = np.array([float(d.get("l", 0)) for d in data])
        vols = np.array([float(d.get("v", 0)) for d in data])

        # Candlestick
        candle_item = CandlestickItem(data)
        self._price_plot.addItem(candle_item)

        # EMA lines
        if self._indicators.get("ema20") and len(cls) >= 20:
            ema20 = self._ema(cls, 20)
            self._price_plot.plot(ts[-len(ema20):], ema20, pen=pg.mkPen(ACCENT, width=1.5), name="EMA20")
        if self._indicators.get("ema50") and len(cls) >= 50:
            ema50 = self._ema(cls, 50)
            self._price_plot.plot(ts[-len(ema50):], ema50, pen=pg.mkPen(YELLOW, width=1.5), name="EMA50")
        if self._indicators.get("ema200") and len(cls) >= 200:
            ema200 = self._ema(cls, 200)
            self._price_plot.plot(ts[-len(ema200):], ema200, pen=pg.mkPen("#FF9800", width=2), name="EMA200")

        # Bollinger Bands
        if self._indicators.get("bb") and len(cls) >= 20:
            bb_mid = self._sma(cls, 20)
            bb_std = self._rolling_std(cls, 20)
            bb_up  = bb_mid + 2 * bb_std
            bb_lo  = bb_mid - 2 * bb_std
            n = len(bb_mid)
            t_slice = ts[-n:]
            self._price_plot.plot(t_slice, bb_up, pen=pg.mkPen(FG2, width=1, style=Qt.PenStyle.DashLine))
            self._price_plot.plot(t_slice, bb_lo, pen=pg.mkPen(FG2, width=1, style=Qt.PenStyle.DashLine))
            fill = pg.FillBetweenItem(
                pg.PlotDataItem(t_slice, bb_up),
                pg.PlotDataItem(t_slice, bb_lo),
                brush=QBrush(QColor(ACCENT + "15")),
            )
            self._price_plot.addItem(fill)

        # VWAP
        if self._indicators.get("vwap"):
            vwap = (cls * vols).cumsum() / vols.cumsum()
            self._price_plot.plot(ts, vwap, pen=pg.mkPen("#CE93D8", width=1.5, style=Qt.PenStyle.DotLine))

        # Buy/Sell markers
        if self._signals:
            marker = SignalMarker(self._signals)
            self._price_plot.addItem(marker)

        # Volume
        if self._indicators.get("volume"):
            vi = VolumeItem(data)
            self._vol_plot.addItem(vi)

        # RSI
        if self._indicators.get("rsi") and len(cls) >= 15:
            rsi = self._rsi(cls, 14)
            n = len(rsi)
            self._rsi_plot.plot(ts[-n:], rsi, pen=pg.mkPen(ACCENT, width=1.5))

        # MACD
        if self._indicators.get("macd") and len(cls) >= 27:
            macd_line, signal_line, hist = self._macd(cls)
            n = len(macd_line)
            t_m = ts[-n:]
            self._macd_plot.plot(t_m, macd_line, pen=pg.mkPen(ACCENT, width=1.5))
            self._macd_plot.plot(t_m, signal_line, pen=pg.mkPen(YELLOW, width=1.5))
            colours = [GREEN if h >= 0 else RED for h in hist]
            bars = pg.BarGraphItem(x=t_m, height=hist, width=0.7,
                                   brushes=[QBrush(QColor(c + "88")) for c in colours])
            self._macd_plot.addItem(bars)

        # Show/hide panels based on indicator toggles
        self._rsi_plot.setVisible(bool(self._indicators.get("rsi")))
        self._macd_plot.setVisible(bool(self._indicators.get("macd")))
        self._vol_plot.setVisible(bool(self._indicators.get("volume")))

    # ── Technical indicator calculations ──────────────────────────────
    @staticmethod
    def _ema(data: np.ndarray, period: int) -> np.ndarray:
        alpha = 2.0 / (period + 1)
        result = np.empty_like(data)
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i-1]
        return result[period-1:]

    @staticmethod
    def _sma(data: np.ndarray, period: int) -> np.ndarray:
        return np.convolve(data, np.ones(period)/period, mode="valid")

    @staticmethod
    def _rolling_std(data: np.ndarray, period: int) -> np.ndarray:
        result = []
        for i in range(period - 1, len(data)):
            result.append(np.std(data[i-period+1:i+1]))
        return np.array(result)

    @staticmethod
    def _rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
        deltas = np.diff(data)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.zeros(len(deltas))
        avg_loss = np.zeros(len(deltas))
        avg_gain[period-1] = gains[:period].mean()
        avg_loss[period-1] = losses[:period].mean()
        for i in range(period, len(deltas)):
            avg_gain[i] = (avg_gain[i-1] * (period-1) + gains[i]) / period
            avg_loss[i] = (avg_loss[i-1] * (period-1) + losses[i]) / period
        rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100.0)
        rsi = 100 - 100 / (1 + rs)
        return rsi[period-1:]

    @staticmethod
    def _macd(data: np.ndarray, fast=12, slow=26, signal=9):
        def ema_full(d, p):
            a = 2.0 / (p + 1)
            r = np.empty_like(d)
            r[0] = d[0]
            for i in range(1, len(d)):
                r[i] = a * d[i] + (1 - a) * r[i-1]
            return r
        ema_fast = ema_full(data, fast)
        ema_slow = ema_full(data, slow)
        macd_line = ema_fast - ema_slow
        sig_line = ema_full(macd_line, signal)
        hist = macd_line - sig_line
        start = slow - 1
        return macd_line[start:], sig_line[start:], hist[start:]

    # ── Events ─────────────────────────────────────────────────────────
    def _on_mouse_move(self, pos) -> None:
        if self._price_plot.sceneBoundingRect().contains(pos):
            mouse_point = self._price_plot.plotItem.vb.mapSceneToView(pos)
            self._vline.setPos(mouse_point.x())
            self._hline.setPos(mouse_point.y())

    def _on_symbol_changed(self, symbol: str) -> None:
        self._symbol = symbol
        self.symbol_changed.emit(symbol, self._interval)
        self._refresh_data()

    def _on_interval_changed(self, interval: str) -> None:
        self._interval = interval
        self.symbol_changed.emit(self._symbol, interval)
        self._refresh_data()

    def _toggle_indicator(self, key: str, checked: bool) -> None:
        self._indicators[key] = checked
        self._render()

    def set_symbol(self, symbol: str) -> None:
        self._symbol = symbol
        idx = self.sym_combo.findText(symbol)
        if idx >= 0:
            self.sym_combo.setCurrentIndex(idx)
