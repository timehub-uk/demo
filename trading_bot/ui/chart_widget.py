"""
Professional Trading Chart Widget — Full Indicator Suite.

Chart styles (switchable):
  Candlestick · OHLC Bar · Line · Area · Heikin-Ashi

Overlay indicators (on price chart):
  EMA 9 · EMA 20 · EMA 50 · EMA 200
  SMA 20 · SMA 50
  Bollinger Bands (20, 2σ) with fill
  VWAP + ±1σ / ±2σ bands
  Ichimoku Cloud (Tenkan · Kijun · Senkou A/B cloud)

Sub-panel oscillators (individually togglable):
  Volume + OBV overlay
  RSI (14) — overbought/oversold zones
  MACD (12, 26, 9) — line + signal + histogram
  Stochastic (14, 3, 3) — %K and %D
  ATR (14) — Average True Range
  ADX + DI± (14) — trend strength

UX:
  Pill-shaped indicator toggles, colour-coded per indicator
  Two-row toolbar: overlays row + panels row
  OHLCV data label that tracks cursor position
  Crosshair with value labels on both axes, synced across all panels
  Per-panel title labels (drawn inside each plot)
  Dynamic splitter sizing — hidden panels collapse to 0
  5-second auto-refresh from Redis / DB
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QPainter, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QComboBox, QLabel, QSizePolicy, QSplitter, QFrame,
    QButtonGroup,
)

from ui.styles import (
    ACCENT, GREEN, RED, YELLOW, ORANGE, BG2, BG3, BG4, BORDER, FG0, FG1, FG2,
)

pg.setConfigOption("background", BG2)
pg.setConfigOption("foreground", FG1)


# ── Colour palette ─────────────────────────────────────────────────────────────

_C = {
    "ema9":   "#26C6DA",
    "ema20":  ACCENT,
    "ema50":  YELLOW,
    "ema200": ORANGE,
    "sma20":  "#AB47BC",
    "sma50":  "#7E57C2",
    "bb":     "#546E7A",
    "vwap":   "#CE93D8",
    "ich":    "#4CAF50",
    "volume": "#26A69A",
    "obv":    "#FF7043",
    "rsi":    ACCENT,
    "macd":   ACCENT,
    "stoch":  "#26C6DA",
    "atr":    YELLOW,
    "adx":    "#EF5350",
    "di_pos": GREEN,
    "di_neg": RED,
}


# ── Indicator toggle pill ──────────────────────────────────────────────────────

class IndicatorPill(QPushButton):
    """Colour-coded checkable pill button for indicator toggles."""

    def __init__(self, label: str, color: str, checked: bool = False, parent=None) -> None:
        super().__init__(label, parent)
        self._color = color
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedHeight(22)
        self._update_style()
        self.toggled.connect(lambda _: self._update_style())

    def _update_style(self) -> None:
        if self.isChecked():
            self.setStyleSheet(f"""
                QPushButton {{
                    background:{self._color}33; color:{self._color};
                    border:1px solid {self._color}; border-radius:10px;
                    padding:1px 8px; font-size:11px; font-weight:700;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background:transparent; color:{FG2};
                    border:1px solid {FG2}55; border-radius:10px;
                    padding:1px 8px; font-size:11px;
                }}
                QPushButton:hover {{ color:{FG1}; border-color:{FG1}55; }}
            """)


# ── Chart style selector ───────────────────────────────────────────────────────

class StyleButton(QPushButton):
    """Compact active/inactive style selector button."""

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setFixedHeight(22)
        self._update_style()
        self.toggled.connect(lambda _: self._update_style())

    def _update_style(self) -> None:
        if self.isChecked():
            self.setStyleSheet(f"""
                QPushButton {{
                    background:{ACCENT}22; color:{ACCENT};
                    border:1px solid {ACCENT}; border-radius:4px;
                    padding:1px 8px; font-size:11px; font-weight:700;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background:transparent; color:{FG2};
                    border:1px solid {FG2}44; border-radius:4px;
                    padding:1px 8px; font-size:11px;
                }}
                QPushButton:hover {{ color:{FG1}; }}
            """)


# ── Candlestick renderer ───────────────────────────────────────────────────────

class CandlestickItem(pg.GraphicsObject):
    """High-performance candlestick renderer with adaptive candle width."""

    def __init__(self, data: list[dict]) -> None:
        super().__init__()
        self.data = data
        self.picture = None
        self._generate()

    def _generate(self) -> None:
        self.picture = pg.Qt.QtGui.QPicture()
        p = QPainter(self.picture)
        # Adaptive width: 40% of inter-bar spacing
        spacing = 1.0
        if len(self.data) >= 2:
            spacing = abs(self.data[1]["t"] - self.data[0]["t"])
        w = spacing * 0.4
        for d in self.data:
            x = d["t"]
            o, h, l, c = d["o"], d["h"], d["l"], d["c"]
            bull = c >= o
            color = GREEN if bull else RED
            body_h = max(abs(c - o), spacing * 0.002)
            body_y = min(o, c)
            # Wick
            p.setPen(pg.mkPen(color, width=1))
            p.drawLine(
                pg.Qt.QtCore.QPointF(x, l),
                pg.Qt.QtCore.QPointF(x, h),
            )
            # Body
            p.setBrush(QBrush(QColor(color)))
            p.setPen(pg.mkPen(color, width=1))
            p.drawRect(pg.Qt.QtCore.QRectF(x - w, body_y, 2 * w, body_h))
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())


class OHLCBarItem(pg.GraphicsObject):
    """OHLC bar chart renderer."""

    def __init__(self, data: list[dict]) -> None:
        super().__init__()
        self.data = data
        self.picture = None
        self._generate()

    def _generate(self) -> None:
        self.picture = pg.Qt.QtGui.QPicture()
        p = QPainter(self.picture)
        spacing = 1.0
        if len(self.data) >= 2:
            spacing = abs(self.data[1]["t"] - self.data[0]["t"])
        tick = spacing * 0.3
        for d in self.data:
            x = d["t"]
            o, h, l, c = d["o"], d["h"], d["l"], d["c"]
            color = GREEN if c >= o else RED
            p.setPen(pg.mkPen(color, width=2))
            # High-low vertical bar
            p.drawLine(pg.Qt.QtCore.QPointF(x, l), pg.Qt.QtCore.QPointF(x, h))
            # Open tick (left)
            p.drawLine(pg.Qt.QtCore.QPointF(x - tick, o), pg.Qt.QtCore.QPointF(x, o))
            # Close tick (right)
            p.drawLine(pg.Qt.QtCore.QPointF(x, c), pg.Qt.QtCore.QPointF(x + tick, c))
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())


class HeikinAshiItem(pg.GraphicsObject):
    """Heikin-Ashi candlestick renderer."""

    def __init__(self, data: list[dict]) -> None:
        super().__init__()
        self.ha_data = self._compute_ha(data)
        self.picture = None
        self._generate()

    @staticmethod
    def _compute_ha(data: list[dict]) -> list[dict]:
        ha = []
        prev_o = prev_c = None
        for d in data:
            o, h, l, c = d["o"], d["h"], d["l"], d["c"]
            ha_c = (o + h + l + c) / 4
            ha_o = ((prev_o + prev_c) / 2) if prev_o is not None else (o + c) / 2
            ha_h = max(h, ha_o, ha_c)
            ha_l = min(l, ha_o, ha_c)
            ha.append({"t": d["t"], "o": ha_o, "h": ha_h, "l": ha_l, "c": ha_c, "v": d.get("v", 0)})
            prev_o, prev_c = ha_o, ha_c
        return ha

    def _generate(self) -> None:
        self.picture = pg.Qt.QtGui.QPicture()
        p = QPainter(self.picture)
        spacing = 1.0
        if len(self.ha_data) >= 2:
            spacing = abs(self.ha_data[1]["t"] - self.ha_data[0]["t"])
        w = spacing * 0.4
        for d in self.ha_data:
            x = d["t"]
            o, h, l, c = d["o"], d["h"], d["l"], d["c"]
            bull = c >= o
            color = GREEN if bull else RED
            body_h = max(abs(c - o), spacing * 0.002)
            body_y = min(o, c)
            p.setPen(pg.mkPen(color, width=1))
            p.drawLine(pg.Qt.QtCore.QPointF(x, l), pg.Qt.QtCore.QPointF(x, h))
            p.setBrush(QBrush(QColor(color)))
            p.drawRect(pg.Qt.QtCore.QRectF(x - w, body_y, 2 * w, body_h))
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())


class VolumeItem(pg.BarGraphItem):
    def __init__(self, data: list[dict]) -> None:
        spacing = 1.0
        if len(data) >= 2:
            spacing = abs(data[1]["t"] - data[0]["t"])
        xs = [d["t"] for d in data]
        ys = [d["v"] for d in data]
        brushes = [
            QBrush(QColor(GREEN + "99")) if d["c"] >= d["o"] else QBrush(QColor(RED + "99"))
            for d in data
        ]
        super().__init__(x=xs, height=ys, width=spacing * 0.7, brushes=brushes)


class SignalMarker(pg.ScatterPlotItem):
    def __init__(self, signals: list[dict]) -> None:
        spots = []
        for s in signals:
            action = s.get("action", s.get("signal", ""))
            price  = s.get("price", s.get("entry_price", 0))
            t      = s.get("t", 0)
            if action == "BUY":
                spots.append({"pos": (t, price), "symbol": "t", "size": 14,
                              "pen": None, "brush": QBrush(QColor(GREEN))})
            elif action == "SELL":
                spots.append({"pos": (t, price), "symbol": "t1", "size": 14,
                              "pen": None, "brush": QBrush(QColor(RED))})
        super().__init__(spots=spots)


# ── Panel title text item ──────────────────────────────────────────────────────

def _panel_label(text: str, color: str = FG1) -> pg.TextItem:
    lbl = pg.TextItem(text, color=color, anchor=(0, 0))
    font = QFont("monospace", 9)
    lbl.setFont(font)
    return lbl


# ── Helper: separator ─────────────────────────────────────────────────────────

def _vsep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setStyleSheet(f"color:{FG2}; margin:4px 2px;")
    return f


def _lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color:{FG2}; font-size:10px; font-weight:600; padding:0 4px;")
    return l


# ── Technical indicator calculations ──────────────────────────────────────────

def _ema_full(data: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    out = np.empty_like(data, dtype=float)
    out[0] = data[0]
    for i in range(1, len(data)):
        out[i] = alpha * data[i] + (1 - alpha) * out[i - 1]
    return out


def _ema(data: np.ndarray, period: int) -> np.ndarray:
    return _ema_full(data, period)[period - 1:]


def _sma(data: np.ndarray, period: int) -> np.ndarray:
    return np.convolve(data, np.ones(period) / period, mode="valid")


def _rolling_std(data: np.ndarray, period: int) -> np.ndarray:
    return np.array([np.std(data[i - period + 1:i + 1]) for i in range(period - 1, len(data))])


def _rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(data)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    ag = np.zeros(len(deltas))
    al = np.zeros(len(deltas))
    ag[period - 1] = gains[:period].mean()
    al[period - 1] = losses[:period].mean()
    for i in range(period, len(deltas)):
        ag[i] = (ag[i - 1] * (period - 1) + gains[i]) / period
        al[i] = (al[i - 1] * (period - 1) + losses[i]) / period
    rs = np.where(al > 0, ag / al, 100.0)
    return (100 - 100 / (1 + rs))[period - 1:]


def _macd(data: np.ndarray, fast=12, slow=26, sig=9):
    ef = _ema_full(data, fast)
    es = _ema_full(data, slow)
    ml = ef - es
    sl = _ema_full(ml, sig)
    ht = ml - sl
    start = slow - 1
    return ml[start:], sl[start:], ht[start:]


def _stochastic(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                k_period=14, d_period=3) -> tuple[np.ndarray, np.ndarray]:
    k_vals = []
    for i in range(k_period - 1, len(closes)):
        hh = highs[i - k_period + 1:i + 1].max()
        ll = lows[i - k_period + 1:i + 1].min()
        rng = hh - ll
        k_vals.append(100 * (closes[i] - ll) / rng if rng > 0 else 50.0)
    k = np.array(k_vals)
    d = _sma(k, d_period)
    return k[d_period - 1:], d


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period=14) -> np.ndarray:
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
    )
    out = np.zeros(len(tr))
    out[period - 1] = tr[:period].mean()
    for i in range(period, len(tr)):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out[period - 1:]


def _adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period=14):
    n = len(closes)
    dm_pos = np.zeros(n)
    dm_neg = np.zeros(n)
    tr_arr = np.zeros(n)
    for i in range(1, n):
        up   = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        dm_pos[i] = up   if up > down and up > 0 else 0.0
        dm_neg[i] = down if down > up and down > 0 else 0.0
        tr_arr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr_s  = _ema_full(tr_arr[1:],  period)
    dmp_s  = _ema_full(dm_pos[1:], period)
    dmn_s  = _ema_full(dm_neg[1:], period)
    di_pos = 100 * np.where(atr_s > 0, dmp_s / atr_s, 0)
    di_neg = 100 * np.where(atr_s > 0, dmn_s / atr_s, 0)
    dx     = 100 * np.abs(di_pos - di_neg) / np.where(di_pos + di_neg > 0, di_pos + di_neg, 1)
    adx    = _ema_full(dx, period)
    start  = period - 1
    return adx[start:], di_pos[start:], di_neg[start:]


def _obv(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    direction = np.sign(np.diff(closes))
    direction = np.concatenate([[0], direction])
    return np.cumsum(direction * volumes)


def _ichimoku(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray):
    def mid(h, l, n):
        return np.array([
            (h[i - n + 1:i + 1].max() + l[i - n + 1:i + 1].min()) / 2
            for i in range(n - 1, len(h))
        ])
    tenkan  = mid(highs, lows, 9)
    kijun   = mid(highs, lows, 26)
    n9  = 9 - 1
    n26 = 26 - 1
    n52 = 52 - 1
    span_a = (tenkan[n26 - n9:] + kijun) / 2
    span_b = mid(highs, lows, 52)
    span_b_aligned = span_b[n26 - n52:]
    return tenkan, kijun, span_a, span_b_aligned


# ── Main chart widget ──────────────────────────────────────────────────────────

class ChartWidget(QWidget):
    symbol_changed = pyqtSignal(str, str)   # symbol, interval

    # Chart style keys
    STYLE_CANDLE = "Candle"
    STYLE_OHLC   = "OHLC"
    STYLE_HA     = "HA"
    STYLE_LINE   = "Line"
    STYLE_AREA   = "Area"

    def __init__(self, parent=None, predictor=None) -> None:
        super().__init__(parent)
        self._data: list[dict] = []
        self._signals: list[dict] = []
        self._symbol   = "BTCUSDT"
        self._interval = "1h"
        self._style    = self.STYLE_CANDLE
        self._predictor = predictor      # optional MLPredictor for forecast
        self._forecast_enabled = False

        # Overlay indicators
        self._overlays: dict[str, bool] = {
            "ema9":   False,
            "ema20":  True,
            "ema50":  True,
            "ema200": False,
            "sma20":  False,
            "sma50":  False,
            "bb":     True,
            "vwap":   True,
            "ich":    False,
        }
        # Sub-panel indicators
        self._panels: dict[str, bool] = {
            "volume": True,
            "obv":    False,
            "rsi":    True,
            "macd":   False,
            "stoch":  False,
            "atr":    False,
            "adx":    False,
        }

        self._ts: Optional[np.ndarray] = None   # timestamps for cursor lookup

        self._setup_ui()
        self._setup_timer()

    # ── UI Setup ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        main.addWidget(self._build_toolbar_row1())
        main.addWidget(self._build_toolbar_row2())

        # Splitter: price + sub-panels
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(3)
        main.addWidget(self._splitter, 1)

        self._build_price_plot()
        self._build_sub_panels()

    def _build_toolbar_row1(self) -> QWidget:
        """Row 1: symbol · interval · chart-style · overlays · OHLCV info · price."""
        row = QWidget()
        row.setFixedHeight(34)
        row.setStyleSheet(f"background:{BG3}; border-bottom:1px solid {BORDER};")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(4)

        # Symbol
        self.sym_combo = QComboBox()
        self.sym_combo.setFixedWidth(120)
        for s in ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT"]:
            self.sym_combo.addItem(s)
        self.sym_combo.currentTextChanged.connect(self._on_symbol_changed)
        lay.addWidget(self.sym_combo)

        # Interval
        self.int_combo = QComboBox()
        self.int_combo.setFixedWidth(64)
        for i in ["1m","3m","5m","15m","30m","1h","2h","4h","1d","1w"]:
            self.int_combo.addItem(i)
        self.int_combo.setCurrentText("1h")
        self.int_combo.currentTextChanged.connect(self._on_interval_changed)
        lay.addWidget(self.int_combo)

        lay.addWidget(_vsep())

        # Chart style buttons (exclusive)
        lay.addWidget(_lbl("STYLE"))
        style_grp = QButtonGroup(self)
        style_grp.setExclusive(True)
        for label in [self.STYLE_CANDLE, self.STYLE_OHLC, self.STYLE_HA,
                      self.STYLE_LINE, self.STYLE_AREA]:
            btn = StyleButton(label)
            btn.setChecked(label == self._style)
            style_grp.addButton(btn)
            lay.addWidget(btn)
            btn.toggled.connect(lambda checked, l=label: self._on_style_changed(l, checked))

        lay.addWidget(_vsep())

        # Overlay indicator pills
        lay.addWidget(_lbl("OVERLAYS"))
        overlay_defs = [
            ("ema9", "EMA9"), ("ema20", "EMA20"), ("ema50", "EMA50"), ("ema200", "EMA200"),
            ("sma20", "SMA20"), ("sma50", "SMA50"), ("bb", "BB"), ("vwap", "VWAP"), ("ich", "ICH"),
        ]
        for key, label in overlay_defs:
            pill = IndicatorPill(label, _C[key], checked=self._overlays.get(key, False))
            pill.toggled.connect(lambda checked, k=key: self._toggle(k, checked))
            lay.addWidget(pill)

        lay.addWidget(_vsep())

        # AI Forecast toggle
        self._forecast_pill = IndicatorPill("AI FORECAST", "#FF6D00", checked=False)
        self._forecast_pill.toggled.connect(self._on_forecast_toggled)
        lay.addWidget(self._forecast_pill)

        lay.addStretch()

        # OHLCV info label
        self.lbl_ohlcv = QLabel("")
        self.lbl_ohlcv.setStyleSheet(
            f"color:{FG1}; font-size:11px; font-family:monospace; padding:0 6px;"
        )
        lay.addWidget(self.lbl_ohlcv)

        lay.addWidget(_vsep())

        # Price + change
        self.lbl_price = QLabel("—")
        self.lbl_price.setStyleSheet(f"font-size:20px; font-weight:700; color:{FG0}; padding:0 4px;")
        lay.addWidget(self.lbl_price)

        self.lbl_change = QLabel("")
        self.lbl_change.setStyleSheet(f"font-size:12px; font-weight:600; padding:0 4px;")
        lay.addWidget(self.lbl_change)

        return row

    def _build_toolbar_row2(self) -> QWidget:
        """Row 2: sub-panel toggles."""
        row = QWidget()
        row.setFixedHeight(30)
        row.setStyleSheet(f"background:{BG4}; border-bottom:1px solid {BORDER};")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 3, 10, 3)
        lay.setSpacing(4)

        lay.addWidget(_lbl("PANELS"))
        panel_defs = [
            ("volume", "VOL"), ("obv", "OBV"), ("rsi", "RSI"),
            ("macd", "MACD"), ("stoch", "STOCH"), ("atr", "ATR"), ("adx", "ADX"),
        ]
        for key, label in panel_defs:
            pill = IndicatorPill(label, _C[key], checked=self._panels.get(key, False))
            pill.toggled.connect(lambda checked, k=key: self._toggle(k, checked))
            lay.addWidget(pill)

        lay.addStretch()
        return row

    def _build_price_plot(self) -> None:
        self._price_plot = pg.PlotWidget()
        self._price_plot.setMenuEnabled(False)
        self._price_plot.showGrid(x=True, y=True, alpha=0.08)
        self._price_plot.setMouseEnabled(x=True, y=True)
        self._price_plot.setAxisItems({"bottom": pg.DateAxisItem(utcOffset=0)})
        self._price_plot.getAxis("right").show()
        self._price_plot.showAxis("right")
        self._price_plot.setMinimumHeight(220)
        self._splitter.addWidget(self._price_plot)

        # Crosshair on price chart
        self._vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(FG2, width=1, style=Qt.PenStyle.DashLine),
            label="{value:.0f}", labelOpts={"position": 0.03, "color": FG1, "fill": BG3},
        )
        self._hline = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen(FG2, width=1, style=Qt.PenStyle.DashLine),
            label="{value:.4f}", labelOpts={"position": 0.97, "color": FG1, "fill": BG3},
        )
        self._price_plot.addItem(self._vline, ignoreBounds=True)
        self._price_plot.addItem(self._hline, ignoreBounds=True)
        self._price_plot.scene().sigMouseMoved.connect(self._on_mouse_move)

    def _build_sub_panels(self) -> None:
        # Each sub-panel: (internal_key, title_text, title_colour, y_range, reference_lines)
        panel_specs = [
            ("volume", "Volume",           _C["volume"],  None,          []),
            ("rsi",    "RSI (14)",         _C["rsi"],     (0, 100),      [80, 70, 50, 30, 20]),
            ("macd",   "MACD (12,26,9)",   _C["macd"],    None,          [0]),
            ("stoch",  "Stoch (14,3,3)",   _C["stoch"],   (0, 100),      [80, 20]),
            ("atr",    "ATR (14)",         _C["atr"],     None,          []),
            ("adx",    "ADX (14)",         _C["adx"],     (0, 100),      [25]),
        ]
        self._sub_plots: dict[str, pg.PlotWidget] = {}
        self._sub_vlines: dict[str, pg.InfiniteLine] = {}

        for key, title, col, yrange, ref_lines in panel_specs:
            pw = pg.PlotWidget()
            pw.setMenuEnabled(False)
            pw.showGrid(x=True, y=True, alpha=0.08)
            pw.setXLink(self._price_plot)
            pw.setAxisItems({"bottom": pg.DateAxisItem(utcOffset=0)})
            pw.setMaximumHeight(120)
            pw.setMinimumHeight(60)
            if yrange:
                pw.setYRange(*yrange, padding=0.05)
                pw.setMouseEnabled(x=True, y=False)
            # Reference lines
            for rv in ref_lines:
                style = Qt.PenStyle.DashLine
                c = RED if rv >= 70 or rv == 80 else (GREEN if rv <= 30 or rv == 20 else FG2)
                pw.addLine(y=rv, pen=pg.mkPen(c, width=1, style=style))
            # Panel title text item
            title_item = _panel_label(f"  {title}", col)
            pw.addItem(title_item, ignoreBounds=True)
            title_item.setParentItem(pw.getPlotItem())
            # Vertical crosshair line (synced)
            vl = pg.InfiniteLine(angle=90, movable=False,
                                  pen=pg.mkPen(FG2, width=1, style=Qt.PenStyle.DashLine))
            pw.addItem(vl, ignoreBounds=True)
            pw.scene().sigMouseMoved.connect(
                lambda pos, p=pw: self._on_sub_mouse_move(pos, p)
            )
            self._sub_plots[key] = pw
            self._sub_vlines[key] = vl
            self._splitter.addWidget(pw)

        self._update_panel_visibility()

    def _setup_timer(self) -> None:
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_data)
        self._refresh_timer.start(5000)

    # ── Data ───────────────────────────────────────────────────────────

    def load_data(self, candles: list[dict], signals: list[dict] | None = None) -> None:
        self._data    = candles
        self._signals = signals or []
        self._render()

    def update_price(self, price: float, change_pct: float) -> None:
        self.lbl_price.setText(f"{price:,.4f}")
        col  = GREEN if change_pct >= 0 else RED
        sign = "+" if change_pct >= 0 else ""
        self.lbl_change.setText(f"{sign}{change_pct:.2f}%")
        self.lbl_change.setStyleSheet(f"font-size:12px; font-weight:600; color:{col};")

    def set_symbol(self, symbol: str) -> None:
        self._symbol = symbol
        idx = self.sym_combo.findText(symbol)
        if idx >= 0:
            self.sym_combo.setCurrentIndex(idx)

    def _refresh_data(self) -> None:
        try:
            from db.redis_client import RedisClient
            candles = RedisClient().get_candles(self._symbol, self._interval)
            if candles:
                self._data = candles
                self._render()
        except Exception:
            pass

    # ── Rendering ──────────────────────────────────────────────────────

    def _render(self) -> None:
        if not self._data:
            return
        data = self._data[-500:]

        # Extract OHLCV arrays
        ts   = np.array([float(d["t"]) for d in data])
        cls  = np.array([float(d.get("c", 0)) for d in data])
        ops  = np.array([float(d.get("o", 0)) for d in data])
        his  = np.array([float(d.get("h", 0)) for d in data])
        los  = np.array([float(d.get("l", 0)) for d in data])
        vols = np.array([float(d.get("v", 0)) for d in data])
        self._ts   = ts
        self._data_slice = data

        # ── Price chart ───────────────────────────────────────────────
        self._price_plot.clear()
        self._price_plot.addItem(self._vline, ignoreBounds=True)
        self._price_plot.addItem(self._hline, ignoreBounds=True)

        self._draw_price_series(data, ts, cls, ops, his, los, vols)
        self._draw_overlays(ts, cls, ops, his, los, vols)

        if self._signals:
            self._price_plot.addItem(SignalMarker(self._signals))

        # AI forecast projection
        self._draw_forecast(ts, cls, his, los)

        # ── Sub-panels ────────────────────────────────────────────────
        for key, pw in self._sub_plots.items():
            pw.clear()
            # Re-add title and crosshair after clear
            title_item = _panel_label(f"  {self._panel_title(key)}", _C.get(key, FG1))
            pw.addItem(title_item, ignoreBounds=True)
            title_item.setParentItem(pw.getPlotItem())
            vl = self._sub_vlines[key]
            pw.addItem(vl, ignoreBounds=True)
            self._redraw_ref_lines(key, pw)

        self._draw_volume_panel(ts, cls, ops, vols)
        self._draw_rsi_panel(ts, cls)
        self._draw_macd_panel(ts, cls)
        self._draw_stoch_panel(ts, his, los, cls)
        self._draw_atr_panel(ts, his, los, cls)
        self._draw_adx_panel(ts, his, los, cls)

        self._update_panel_visibility()

    def _draw_price_series(self, data, ts, cls, ops, his, los, vols) -> None:
        if self._style == self.STYLE_CANDLE:
            self._price_plot.addItem(CandlestickItem(data))
        elif self._style == self.STYLE_OHLC:
            self._price_plot.addItem(OHLCBarItem(data))
        elif self._style == self.STYLE_HA:
            self._price_plot.addItem(HeikinAshiItem(data))
        elif self._style == self.STYLE_LINE:
            self._price_plot.plot(ts, cls, pen=pg.mkPen(ACCENT, width=2))
        elif self._style == self.STYLE_AREA:
            curve = pg.PlotCurveItem(ts, cls, pen=pg.mkPen(ACCENT, width=2))
            fill  = pg.FillBetweenItem(
                curve, pg.PlotCurveItem(ts, np.zeros_like(cls)),
                brush=QBrush(QColor(ACCENT + "22")),
            )
            self._price_plot.addItem(curve)
            self._price_plot.addItem(fill)

    def _draw_overlays(self, ts, cls, ops, his, los, vols) -> None:
        n = len(cls)

        def _plot_ema(period, key):
            if self._overlays.get(key) and n >= period:
                e = _ema(cls, period)
                self._price_plot.plot(ts[-len(e):], e,
                    pen=pg.mkPen(_C[key], width=1.5), name=key.upper())

        _plot_ema(9,   "ema9")
        _plot_ema(20,  "ema20")
        _plot_ema(50,  "ema50")
        _plot_ema(200, "ema200")

        if self._overlays.get("sma20") and n >= 20:
            s = _sma(cls, 20)
            self._price_plot.plot(ts[-len(s):], s,
                pen=pg.mkPen(_C["sma20"], width=1.5, style=Qt.PenStyle.DashLine))
        if self._overlays.get("sma50") and n >= 50:
            s = _sma(cls, 50)
            self._price_plot.plot(ts[-len(s):], s,
                pen=pg.mkPen(_C["sma50"], width=1.5, style=Qt.PenStyle.DashLine))

        if self._overlays.get("bb") and n >= 20:
            mid  = _sma(cls, 20)
            std  = _rolling_std(cls, 20)
            t_sl = ts[-len(mid):]
            up   = mid + 2 * std
            lo   = mid - 2 * std
            c_up = pg.PlotDataItem(t_sl, up, pen=pg.mkPen(_C["bb"], width=1, style=Qt.PenStyle.DashLine))
            c_lo = pg.PlotDataItem(t_sl, lo, pen=pg.mkPen(_C["bb"], width=1, style=Qt.PenStyle.DashLine))
            self._price_plot.addItem(c_up)
            self._price_plot.addItem(c_lo)
            self._price_plot.plot(t_sl, mid, pen=pg.mkPen(_C["bb"], width=1))
            self._price_plot.addItem(
                pg.FillBetweenItem(c_up, c_lo, brush=QBrush(QColor(ACCENT + "12")))
            )

        if self._overlays.get("vwap") and n >= 2:
            cum_vol = np.cumsum(vols)
            vwap_vals = np.cumsum(cls * vols) / np.where(cum_vol > 0, cum_vol, 1)
            self._price_plot.plot(ts, vwap_vals,
                pen=pg.mkPen(_C["vwap"], width=1.5, style=Qt.PenStyle.DotLine))
            # VWAP ± 1σ and ±2σ bands
            rolling_var = np.array([
                np.var(cls[max(0, i - 20):i + 1]) for i in range(n)
            ])
            sigma = np.sqrt(rolling_var)
            for mult, alpha in [(1, "30"), (2, "18")]:
                cu = pg.PlotDataItem(ts, vwap_vals + mult * sigma,
                    pen=pg.mkPen(_C["vwap"] + alpha, width=1, style=Qt.PenStyle.DotLine))
                cl = pg.PlotDataItem(ts, vwap_vals - mult * sigma,
                    pen=pg.mkPen(_C["vwap"] + alpha, width=1, style=Qt.PenStyle.DotLine))
                self._price_plot.addItem(cu)
                self._price_plot.addItem(cl)

        if self._overlays.get("ich") and n >= 52:
            tenkan, kijun, span_a, span_b = _ichimoku(his, los, cls)
            t_tk  = ts[-(len(tenkan)):]
            t_kj  = ts[-(len(kijun)):]
            t_sa  = ts[-(len(span_a)):]
            t_sb  = ts[-(len(span_b)):]
            t_min = min(len(span_a), len(span_b))
            t_cld = ts[-t_min:]
            self._price_plot.plot(t_tk, tenkan, pen=pg.mkPen("#4CAF50", width=1.5))
            self._price_plot.plot(t_kj, kijun,  pen=pg.mkPen("#F44336", width=1.5))
            if t_min > 0:
                sa_c = pg.PlotDataItem(t_cld, span_a[-t_min:],
                    pen=pg.mkPen("#4CAF5088", width=1))
                sb_c = pg.PlotDataItem(t_cld, span_b[-t_min:],
                    pen=pg.mkPen("#F4433688", width=1))
                self._price_plot.addItem(sa_c)
                self._price_plot.addItem(sb_c)
                bull_cloud = span_a[-t_min:] >= span_b[-t_min:]
                for i in range(t_min - 1):
                    col_a = "#4CAF5022" if bull_cloud[i] else "#F4433622"
                    seg_a = pg.PlotDataItem(t_cld[i:i+2], span_a[-t_min:][i:i+2])
                    seg_b = pg.PlotDataItem(t_cld[i:i+2], span_b[-t_min:][i:i+2])
                    self._price_plot.addItem(
                        pg.FillBetweenItem(seg_a, seg_b, brush=QBrush(QColor(col_a)))
                    )

    # ── Sub-panel draw helpers ─────────────────────────────────────────

    def _draw_volume_panel(self, ts, cls, ops, vols) -> None:
        pw = self._sub_plots["volume"]
        data = self._data_slice
        pw.addItem(VolumeItem(data))
        if self._panels.get("obv") and len(cls) >= 2:
            obv = _obv(cls, vols)
            # Scale OBV to fit volume panel (right axis)
            obv_norm = obv / (np.max(np.abs(obv)) + 1e-9) * np.max(vols) * 0.5
            pw.plot(ts, obv_norm,
                pen=pg.mkPen(_C["obv"], width=1.5), name="OBV")

    def _draw_rsi_panel(self, ts, cls) -> None:
        if not self._panels.get("rsi"):
            return
        pw = self._sub_plots["rsi"]
        if len(cls) >= 15:
            r = _rsi(cls, 14)
            n = len(r)
            t_sl = ts[-n:]
            # Colour fill zones: red >70, green <30
            pw.plot(t_sl, r, pen=pg.mkPen(_C["rsi"], width=1.5))
            over  = pg.PlotDataItem(t_sl, np.clip(r, 70, 100))
            over_base = pg.PlotDataItem(t_sl, np.full(n, 70))
            pw.addItem(pg.FillBetweenItem(over, over_base, brush=QBrush(QColor(RED + "33"))))
            under = pg.PlotDataItem(t_sl, np.clip(r, 0, 30))
            under_base = pg.PlotDataItem(t_sl, np.full(n, 30))
            pw.addItem(pg.FillBetweenItem(under_base, under, brush=QBrush(QColor(GREEN + "33"))))

    def _draw_macd_panel(self, ts, cls) -> None:
        if not self._panels.get("macd"):
            return
        pw = self._sub_plots["macd"]
        if len(cls) >= 27:
            ml, sl, ht = _macd(cls)
            n   = len(ml)
            t_m = ts[-n:]
            pw.plot(t_m, ml, pen=pg.mkPen(_C["macd"], width=1.5))
            pw.plot(t_m, sl, pen=pg.mkPen(YELLOW, width=1.5))
            brushes = [QBrush(QColor(GREEN + "AA")) if h >= 0 else QBrush(QColor(RED + "AA"))
                       for h in ht]
            spacing = float(t_m[1] - t_m[0]) if len(t_m) > 1 else 1.0
            pw.addItem(pg.BarGraphItem(x=t_m, height=ht, width=spacing * 0.7, brushes=brushes))

    def _draw_stoch_panel(self, ts, his, los, cls) -> None:
        if not self._panels.get("stoch"):
            return
        pw = self._sub_plots["stoch"]
        if len(cls) >= 17:
            k, d = _stochastic(his, los, cls)
            n    = len(k)
            t_sl = ts[-n:]
            pw.plot(t_sl, k, pen=pg.mkPen(_C["stoch"], width=1.5))
            pw.plot(t_sl, d, pen=pg.mkPen(YELLOW, width=1.5))

    def _draw_atr_panel(self, ts, his, los, cls) -> None:
        if not self._panels.get("atr"):
            return
        pw = self._sub_plots["atr"]
        if len(cls) >= 15:
            a    = _atr(his, los, cls)
            n    = len(a)
            t_sl = ts[-n:]
            pw.plot(t_sl, a, pen=pg.mkPen(_C["atr"], width=1.5))

    def _draw_adx_panel(self, ts, his, los, cls) -> None:
        if not self._panels.get("adx"):
            return
        pw = self._sub_plots["adx"]
        if len(cls) >= 29:
            adx, di_pos, di_neg = _adx(his, los, cls)
            n    = len(adx)
            t_sl = ts[-n:]
            pw.plot(t_sl, adx,    pen=pg.mkPen(_C["adx"],    width=2))
            pw.plot(t_sl, di_pos, pen=pg.mkPen(_C["di_pos"], width=1))
            pw.plot(t_sl, di_neg, pen=pg.mkPen(_C["di_neg"], width=1))

    # ── Panel helpers ──────────────────────────────────────────────────

    def _redraw_ref_lines(self, key: str, pw: pg.PlotWidget) -> None:
        ref = {
            "rsi":   [(70, RED), (50, FG2), (30, GREEN), (80, RED), (20, GREEN)],
            "stoch": [(80, RED), (20, GREEN)],
            "adx":   [(25, YELLOW)],
            "macd":  [(0, FG2)],
        }
        for rv, col in ref.get(key, []):
            pw.addLine(y=rv, pen=pg.mkPen(col, width=1, style=Qt.PenStyle.DashLine))

    def _panel_title(self, key: str) -> str:
        return {
            "volume": "Volume",
            "rsi":    "RSI (14)",
            "macd":   "MACD (12,26,9)",
            "stoch":  "Stoch (14,3,3)  — %K  — %D",
            "atr":    "ATR (14)",
            "adx":    "ADX (14)  — +DI  — −DI",
        }.get(key, key.upper())

    def _update_panel_visibility(self) -> None:
        visible_heights = [400]   # main price plot
        panel_keys = ["volume", "rsi", "macd", "stoch", "atr", "adx"]
        for key in panel_keys:
            pw = self._sub_plots[key]
            is_vis = bool(self._panels.get(key))
            # OBV lives inside volume panel, so volume panel shows if volume OR obv is on
            if key == "volume":
                is_vis = self._panels.get("volume") or self._panels.get("obv")
            pw.setVisible(is_vis)
            visible_heights.append(90 if is_vis else 0)
        self._splitter.setSizes(visible_heights)

    # ── Events ─────────────────────────────────────────────────────────

    def _on_mouse_move(self, pos) -> None:
        if not self._price_plot.sceneBoundingRect().contains(pos):
            return
        mp = self._price_plot.plotItem.vb.mapSceneToView(pos)
        x, y = mp.x(), mp.y()
        self._vline.setPos(x)
        self._hline.setPos(y)
        for vl in self._sub_vlines.values():
            vl.setPos(x)
        self._update_ohlcv_label(x)

    def _on_sub_mouse_move(self, pos, plot: pg.PlotWidget) -> None:
        if not plot.sceneBoundingRect().contains(pos):
            return
        mp = plot.plotItem.vb.mapSceneToView(pos)
        x  = mp.x()
        self._vline.setPos(x)
        for vl in self._sub_vlines.values():
            vl.setPos(x)
        self._update_ohlcv_label(x)

    def _update_ohlcv_label(self, x: float) -> None:
        if self._ts is None or len(self._ts) == 0:
            return
        idx = int(np.searchsorted(self._ts, x, side="right")) - 1
        idx = max(0, min(idx, len(self._data_slice) - 1))
        d   = self._data_slice[idx]
        ts  = datetime.utcfromtimestamp(d["t"]).strftime("%Y-%m-%d %H:%M")
        self.lbl_ohlcv.setText(
            f"{ts}  "
            f"O:<b>{float(d['o']):.4f}</b>  "
            f"H:<b style='color:{GREEN};'>{float(d['h']):.4f}</b>  "
            f"L:<b style='color:{RED};'>{float(d['l']):.4f}</b>  "
            f"C:<b>{float(d['c']):.4f}</b>  "
            f"V:<b>{float(d.get('v',0)):,.0f}</b>"
        )
        self.lbl_ohlcv.setTextFormat(Qt.TextFormat.RichText)

    def _on_symbol_changed(self, symbol: str) -> None:
        self._symbol = symbol
        self.symbol_changed.emit(symbol, self._interval)
        self._refresh_data()

    def _on_interval_changed(self, interval: str) -> None:
        self._interval = interval
        self.symbol_changed.emit(self._symbol, interval)
        self._refresh_data()

    def _on_style_changed(self, style: str, checked: bool) -> None:
        if checked:
            self._style = style
            self._render()

    def _toggle(self, key: str, checked: bool) -> None:
        if key in self._overlays:
            self._overlays[key] = checked
        else:
            self._panels[key] = checked
        self._render()

    def _on_forecast_toggled(self, checked: bool) -> None:
        self._forecast_enabled = checked
        self._render()

    def set_predictor(self, predictor) -> None:
        """Attach an MLPredictor so the forecast panel can query live signals."""
        self._predictor = predictor

    # ── AI Forecast overlay ────────────────────────────────────────────

    def _draw_forecast(self, ts: np.ndarray, cls: np.ndarray, his: np.ndarray,
                        los: np.ndarray) -> None:
        """
        Draw a 20-bar AI price projection on the price chart.

        Sources (tried in order):
          1. Redis ml_signal:{symbol} cache
          2. self._predictor.predict(symbol) if set
          3. Skip silently if neither is available

        Renders:
          - Central dashed forecast line
          - Shaded ±1 ATR confidence cone (uncertainty widens over time)
          - Label at the end showing direction + confidence
        """
        if not self._forecast_enabled or len(cls) < 15:
            return

        signal, confidence = self._fetch_ml_signal()
        if signal == "HOLD" or confidence < 0.45:
            return

        n_forward = 20
        last_t    = float(ts[-1])
        spacing   = float(ts[-1] - ts[-2]) if len(ts) >= 2 else 3600.0

        # ATR for cone width
        atr_vals  = _atr(his, los, cls, 14)
        atr_now   = float(atr_vals[-1]) if len(atr_vals) > 0 else float(cls[-1]) * 0.01

        # Projected price path: curved toward target, then flattening
        last_close = float(cls[-1])
        direction  = 1.0 if signal == "BUY" else -1.0
        target     = last_close + direction * confidence * atr_now * 3.0

        future_t   = np.array([last_t + (i + 1) * spacing for i in range(n_forward)])
        weights    = 1 - np.exp(-np.linspace(0, 2, n_forward))   # asymptotic curve
        future_cls = last_close + (target - last_close) * weights

        # Cone half-width: starts at 0, grows to ±2 ATR
        cone_width = atr_now * np.linspace(0.2, 2.0, n_forward)

        # Join last real close to first forecast point
        all_t   = np.concatenate([[last_t], future_t])
        all_mid = np.concatenate([[last_close], future_cls])
        all_up  = np.concatenate([[last_close], future_cls + cone_width])
        all_lo  = np.concatenate([[last_close], future_cls - cone_width])

        col = "#FF6D00"
        mid_item = pg.PlotDataItem(all_t, all_mid,
            pen=pg.mkPen(col, width=2, style=Qt.PenStyle.DashLine))
        up_item  = pg.PlotDataItem(all_t, all_up,
            pen=pg.mkPen(col + "55", width=1, style=Qt.PenStyle.DotLine))
        lo_item  = pg.PlotDataItem(all_t, all_lo,
            pen=pg.mkPen(col + "55", width=1, style=Qt.PenStyle.DotLine))

        self._price_plot.addItem(mid_item)
        self._price_plot.addItem(up_item)
        self._price_plot.addItem(lo_item)
        self._price_plot.addItem(
            pg.FillBetweenItem(up_item, lo_item, brush=QBrush(QColor(col + "18")))
        )

        # End label
        emoji  = "▲" if signal == "BUY" else "▼"
        label  = pg.TextItem(
            f" {emoji} {signal} {confidence:.0%}",
            color=col, anchor=(0, 0.5),
        )
        label.setPos(future_t[-1], float(future_cls[-1]))
        self._price_plot.addItem(label, ignoreBounds=True)

    def _fetch_ml_signal(self) -> tuple[str, float]:
        """Return (signal, confidence) from Redis cache or live predictor."""
        # Try Redis first (already cached by predictor loop)
        try:
            from db.redis_client import RedisClient
            import json
            raw = RedisClient().get(f"ml_signal:{self._symbol}")
            if raw:
                d = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                sig = d.get("action") or d.get("signal", "HOLD")
                conf = float(d.get("confidence", 0.5))
                return sig, conf
        except Exception:
            pass
        # Try live predictor
        if self._predictor:
            try:
                result = self._predictor.predict(self._symbol)
                if result:
                    sig  = result.get("action") or result.get("signal", "HOLD")
                    conf = float(result.get("confidence", 0.5))
                    return sig, conf
            except Exception:
                pass
        return "HOLD", 0.0
