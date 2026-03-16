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

# Print-friendly colour overrides (dark-on-white, increased contrast).
# Temporarily swapped in during PDF export, then restored.
_PRINT_C = {
    "ema9":   "#006064",
    "ema20":  "#1565C0",
    "ema50":  "#E65100",
    "ema200": "#BF360C",
    "sma20":  "#6A1B9A",
    "sma50":  "#311B92",
    "bb":     "#37474F",
    "vwap":   "#880E4F",
    "ich":    "#1B5E20",
    "volume": "#004D40",
    "obv":    "#BF360C",
    "rsi":    "#1565C0",
    "macd":   "#1565C0",
    "stoch":  "#006064",
    "atr":    "#E65100",
    "adx":    "#B71C1C",
    "di_pos": "#1B5E20",
    "di_neg": "#B71C1C",
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


# ── Trade marker helpers ────────────────────────────────────────────────────────

_BINANCE_FEE_PCT = 0.001   # 0.1% per leg
_UK_CGT_RATE     = 0.20    # 20% capital gains tax
_TRADE_MARKER_COLOR = "#FFD700"   # gold


def _iso_to_ts(iso: str) -> float:
    """Convert ISO timestamp string to Unix timestamp float."""
    if not iso:
        return 0.0
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


class TradeMarkerLayer:
    """
    Draws trade entry/exit markers (yellow squares) and dotted pair connectors
    on a pyqtgraph PlotWidget.  Call draw() to refresh; clear() to remove.
    """

    MARKER_SIZE = 12

    def __init__(self, price_plot: "pg.PlotWidget") -> None:
        self._plot  = price_plot
        self._items: list = []

    def clear(self) -> None:
        for item in self._items:
            try:
                self._plot.removeItem(item)
            except Exception:
                pass
        self._items.clear()

    def draw(self, trades: list) -> list[dict]:
        """
        Draw markers for all trades.  Returns a list of hit-test dicts:
          {"ts": float, "price": float, "trade": TradeEntry, "is_entry": bool}
        """
        self.clear()
        markers: list[dict] = []

        for trade in trades:
            entry_ts = _iso_to_ts(trade.entry_time)
            if entry_ts == 0.0:
                continue
            ep = float(trade.entry_price)
            is_closed = (
                not trade.is_open
                and trade.exit_time
                and float(trade.exit_price or 0) > 0
            )
            exit_ts = _iso_to_ts(trade.exit_time) if is_closed else 0.0
            xp = float(trade.exit_price) if is_closed else 0.0

            # Entry square — yellow border, semi-transparent fill
            e_scatter = pg.ScatterPlotItem(
                x=[entry_ts], y=[ep],
                symbol="s", size=self.MARKER_SIZE,
                pen=pg.mkPen(_TRADE_MARKER_COLOR, width=2),
                brush=QBrush(QColor(_TRADE_MARKER_COLOR + "66")),
            )
            self._plot.addItem(e_scatter)
            self._items.append(e_scatter)
            markers.append({"ts": entry_ts, "price": ep,
                             "trade": trade, "is_entry": True})

            if is_closed:
                pnl_col = GREEN if trade.pnl >= 0 else RED

                # Exit square — profit/loss tinted border
                x_scatter = pg.ScatterPlotItem(
                    x=[exit_ts], y=[xp],
                    symbol="s", size=self.MARKER_SIZE,
                    pen=pg.mkPen(pnl_col, width=2),
                    brush=QBrush(QColor(_TRADE_MARKER_COLOR + "66")),
                )
                self._plot.addItem(x_scatter)
                self._items.append(x_scatter)
                markers.append({"ts": exit_ts, "price": xp,
                                 "trade": trade, "is_entry": False})

                # Dotted connector line
                connector = pg.PlotDataItem(
                    x=[entry_ts, exit_ts], y=[ep, xp],
                    pen=pg.mkPen(_TRADE_MARKER_COLOR + "99", width=1.5,
                                 style=Qt.PenStyle.DotLine),
                )
                self._plot.addItem(connector)
                self._items.append(connector)

        return markers


# ── Chart event annotation layer ───────────────────────────────────────────────

# Per-event-type defaults: (color, symbol, anchor_side)
_EVENT_CONFIG: dict[str, tuple[str, str, str]] = {
    "CASCADE":      ("#FF5722", "▼", "bottom"),
    "WHALE":        ("#CE93D8", "◆", "top"),
    "FUNDING":      ("#FFD700", "◆", "top"),
    "LEAD_LAG":     ("#26C6DA", "→", "top"),
    "AGGRESSOR":    ("#FF7043", "★", "top"),
    "ML_SIGNAL":    ("#4CAF50", "▲", "top"),
    "ML_SELL":      ("#EF5350", "▼", "bottom"),
    "VOLUME_SPIKE": ("#AB47BC", "↑", "top"),
}


class ChartEvent:
    """Lightweight data holder for a chart event annotation."""

    __slots__ = ("ts", "price", "event_type", "label", "color", "detail")

    def __init__(
        self,
        ts: float,
        price: float,
        event_type: str,
        label: str,
        color: str = "",
        detail: str = "",
    ) -> None:
        self.ts         = ts
        self.price      = price
        self.event_type = event_type
        self.label      = label
        self.color      = color
        self.detail     = detail


class EventAnnotationLayer:
    """
    Renders typed market-event markers on a pyqtgraph price plot.

    Each event is drawn as a coloured diamond scatter point with a short
    label.  Hover detection finds the nearest event within a pixel threshold
    so the ChartWidget can show a detailed tooltip.
    """

    def __init__(self, price_plot: pg.PlotWidget) -> None:
        self._plot   = price_plot
        self._items: list = []
        self._events: list[ChartEvent] = []

    def clear(self) -> None:
        for item in self._items:
            try:
                self._plot.removeItem(item)
            except Exception:
                pass
        self._items.clear()

    def draw(self, events: list[ChartEvent]) -> None:
        self.clear()
        self._events = list(events)
        _font = QFont("monospace", 8)
        _font.setBold(True)
        for ev in events:
            cfg  = _EVENT_CONFIG.get(ev.event_type, ("#BBBBBB", "●", "top"))
            col  = ev.color or cfg[0]
            side = cfg[2]
            scatter = pg.ScatterPlotItem(
                x=[ev.ts], y=[ev.price],
                symbol="d", size=9,
                pen=pg.mkPen(col, width=1.5),
                brush=QBrush(QColor(col + "77")),
            )
            self._plot.addItem(scatter)
            self._items.append(scatter)
            # Label positioned just above or below the diamond
            anchor_y = 1.2 if side == "top" else -0.2
            lbl = pg.TextItem(
                text=ev.label[:28],
                color=col,
                anchor=(0.5, anchor_y),
            )
            lbl.setFont(_font)
            lbl.setPos(ev.ts, ev.price)
            self._plot.addItem(lbl, ignoreBounds=True)
            self._items.append(lbl)

    def find_nearest(
        self, x: float, y: float, time_tol: float, price_tol: float
    ) -> "ChartEvent | None":
        """Return the nearest ChartEvent within tolerance, or None."""
        best      = None
        best_dist = float("inf")
        for ev in self._events:
            if abs(ev.ts - x) < time_tol and abs(ev.price - y) < price_tol:
                dist = ((ev.ts - x) ** 2 + (ev.price - y) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best = ev
        return best


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

    def __init__(self, parent=None, predictor=None, forecast_tracker=None) -> None:
        super().__init__(parent)
        self._data: list[dict] = []
        self._signals: list[dict] = []
        self._symbol   = "BTCUSDT"
        self._interval = "1h"
        self._style    = self.STYLE_CANDLE
        self._predictor = predictor
        self._forecast_tracker = forecast_tracker
        self._forecast_enabled = False
        self._forecast_horizon = 20   # bars ahead

        # Overlay indicators
        self._overlays: dict[str, bool] = {
            "ema9":     False,
            "ema20":    True,
            "ema50":    True,
            "ema200":   False,
            "sma20":    False,
            "sma50":    False,
            "bb":       True,
            "vwap":     True,
            "ich":      False,
            "sr":        False,   # auto support/resistance levels
            "sessions":  True,   # Asian / London / NY session bands
            "events":    True,   # market event annotations
            "watermark": True,   # faint pair-name background watermark
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

        # Trade overlay
        self._trades: list = []
        self._show_trades: bool = True
        self._trade_markers: list[dict] = []   # [{ts, price, trade, is_entry}, ...]
        self._trade_layer: Optional[TradeMarkerLayer] = None
        self._trade_hover: Optional[pg.TextItem] = None

        # Market event annotations (whale, cascade, funding, lead-lag, etc.)
        self._chart_events: list[ChartEvent] = []
        self._show_events:  bool = True
        self._event_layer:  Optional[EventAnnotationLayer] = None
        self._event_hover:  Optional[pg.TextItem] = None

        # Chart navigation
        self._auto_scale:  bool = True
        self._auto_follow: bool = True

        self._setup_ui()
        self._setup_timer()

    # ── UI Setup ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        main.addWidget(self._build_toolbar_row1())
        main.addWidget(self._build_toolbar_row2())
        main.addWidget(self._build_toolbar_row3())

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

        # AI Forecast toggle + horizon selector + accuracy badge
        self._forecast_pill = IndicatorPill("AI FORECAST", "#FF6D00", checked=False)
        self._forecast_pill.toggled.connect(self._on_forecast_toggled)
        lay.addWidget(self._forecast_pill)

        self._horizon_combo = QComboBox()
        self._horizon_combo.setFixedWidth(58)
        self._horizon_combo.setFixedHeight(22)
        self._horizon_combo.setStyleSheet(
            f"QComboBox {{ background:{BG4}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:3px; font-size:11px; padding:1px 4px; }}"
        )
        for h in ["5", "10", "20", "50", "100"]:
            self._horizon_combo.addItem(f"{h}b")
        self._horizon_combo.setCurrentText("20b")
        self._horizon_combo.currentTextChanged.connect(self._on_horizon_changed)
        lay.addWidget(self._horizon_combo)

        # Accuracy badge: e.g. "ACC 68% (34/50)"
        self._acc_label = QLabel("")
        self._acc_label.setStyleSheet(
            f"font-size:11px; font-weight:700; font-family:monospace; padding:0 4px;"
        )
        lay.addWidget(self._acc_label)

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

        lay.addWidget(_vsep())
        pdf_btn = QPushButton("⎙ PDF")
        pdf_btn.setFixedHeight(24)
        pdf_btn.setFixedWidth(54)
        pdf_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:3px; font-size:11px; font-weight:700; }}"
            f"QPushButton:hover {{ background:{BG4}; color:{FG0}; }}"
        )
        pdf_btn.setToolTip("Export chart to PDF")
        pdf_btn.clicked.connect(self._export_pdf)
        lay.addWidget(pdf_btn)

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

        lay.addWidget(_vsep())
        trades_pill = IndicatorPill("TRADES", _TRADE_MARKER_COLOR, checked=True)
        trades_pill.toggled.connect(self._on_trades_toggled)
        lay.addWidget(trades_pill)

        lay.addWidget(_vsep())
        lay.addWidget(_lbl("EXTRAS"))
        events_pill = IndicatorPill("EVENTS", "#FF7043", checked=True)
        events_pill.toggled.connect(self._on_events_toggled)
        lay.addWidget(events_pill)
        sr_pill = IndicatorPill("S/R", "#78909C", checked=False)
        sr_pill.toggled.connect(lambda c: self._toggle("sr", c))
        lay.addWidget(sr_pill)
        sess_pill = IndicatorPill("SESSIONS", "#546E7A", checked=True)
        sess_pill.toggled.connect(lambda c: self._toggle("sessions", c))
        lay.addWidget(sess_pill)
        wmark_pill = IndicatorPill("WMARK", "#37474F", checked=True)
        wmark_pill.toggled.connect(lambda c: self._toggle("watermark", c))
        lay.addWidget(wmark_pill)

        lay.addStretch()
        return row

    def _build_toolbar_row3(self) -> QWidget:
        """Row 3: chart navigation controls (zoom, pan, auto-scale, auto-follow)."""
        from PyQt6.QtWidgets import QSpinBox
        row = QWidget()
        row.setFixedHeight(28)
        row.setStyleSheet(f"background:{BG4}; border-bottom:1px solid {BORDER};")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 2, 10, 2)
        lay.setSpacing(4)

        btn_style = (
            f"QPushButton {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:3px; padding:1px 8px; font-size:11px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{BG4}; color:{FG0}; }}"
        )

        def _nav_btn(label: str, slot) -> QPushButton:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setStyleSheet(btn_style)
            b.clicked.connect(slot)
            return b

        lay.addWidget(_lbl("NAVIGATE"))
        lay.addWidget(_nav_btn("◀◀", self._pan_far_left))
        lay.addWidget(_nav_btn("◀",  self._pan_left))
        lay.addWidget(_nav_btn("▶",  self._pan_right))
        lay.addWidget(_nav_btn("▶▶", self._pan_far_right))
        lay.addWidget(_vsep())
        lay.addWidget(_nav_btn("− Zoom", self._zoom_out))
        lay.addWidget(_nav_btn("+ Zoom", self._zoom_in))
        lay.addWidget(_nav_btn("Fit",    self._fit_view))
        lay.addWidget(_vsep())

        # Auto-scale toggle
        self._autoscale_btn = QPushButton("Auto-Scale ✓")
        self._autoscale_btn.setFixedHeight(22)
        self._autoscale_btn.setCheckable(True)
        self._autoscale_btn.setChecked(True)
        self._autoscale_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{GREEN}; border:1px solid {BORDER}; "
            f"border-radius:3px; padding:1px 8px; font-size:11px; font-weight:600; }}"
            f"QPushButton:checked {{ color:{GREEN}; }}"
            f"QPushButton:!checked {{ color:{FG2}; }}"
        )
        self._autoscale_btn.toggled.connect(self._on_autoscale_toggled)
        lay.addWidget(self._autoscale_btn)

        # Auto-follow toggle
        self._autofollow_btn = QPushButton("Auto-Follow ✓")
        self._autofollow_btn.setFixedHeight(22)
        self._autofollow_btn.setCheckable(True)
        self._autofollow_btn.setChecked(True)
        self._autofollow_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{GREEN}; border:1px solid {BORDER}; "
            f"border-radius:3px; padding:1px 8px; font-size:11px; font-weight:600; }}"
            f"QPushButton:checked {{ color:{GREEN}; }}"
            f"QPushButton:!checked {{ color:{FG2}; }}"
        )
        self._autofollow_btn.toggled.connect(self._on_autofollow_toggled)
        lay.addWidget(self._autofollow_btn)

        lay.addStretch()
        return row

    # ── Chart navigation helpers ────────────────────────────────────────

    def _pan_step(self, fraction: float) -> None:
        """Pan the price plot by fraction of the visible range."""
        vr = self._price_plot.viewRange()
        span = vr[0][1] - vr[0][0]
        delta = span * fraction
        self._price_plot.setXRange(vr[0][0] + delta, vr[0][1] + delta, padding=0)

    def _pan_left(self)     -> None: self._pan_step(-0.2)
    def _pan_right(self)    -> None: self._pan_step(+0.2)
    def _pan_far_left(self) -> None: self._pan_step(-0.8)
    def _pan_far_right(self)-> None: self._pan_step(+0.8)

    def _zoom_in(self) -> None:
        vr = self._price_plot.viewRange()
        cx = (vr[0][0] + vr[0][1]) / 2
        half = (vr[0][1] - vr[0][0]) * 0.35
        self._price_plot.setXRange(cx - half, cx + half, padding=0)

    def _zoom_out(self) -> None:
        vr = self._price_plot.viewRange()
        cx = (vr[0][0] + vr[0][1]) / 2
        half = (vr[0][1] - vr[0][0]) * 0.7
        self._price_plot.setXRange(cx - half, cx + half, padding=0)

    def _fit_view(self) -> None:
        self._price_plot.enableAutoRange()

    def _on_autoscale_toggled(self, checked: bool) -> None:
        self._auto_scale = checked
        label = "Auto-Scale ✓" if checked else "Auto-Scale ✗"
        self._autoscale_btn.setText(label)
        if checked:
            self._price_plot.enableAutoRange(axis="y")
        else:
            self._price_plot.disableAutoRange(axis="y")

    def _on_autofollow_toggled(self, checked: bool) -> None:
        self._auto_follow = checked
        label = "Auto-Follow ✓" if checked else "Auto-Follow ✗"
        self._autofollow_btn.setText(label)

    # ── PDF export ─────────────────────────────────────────────────────

    def _export_pdf(self) -> None:
        """
        Export the chart to a PDF with a white background and print-optimised
        colours.  The export process:
          1. Saves the current dark-theme state.
          2. Switches every pyqtgraph plot to a white background with dark
             axis / grid pens and swaps in the _PRINT_C colour map.
          3. Re-renders and grabs the chart-only splitter area as a QPixmap.
          4. Restores the dark theme and re-renders.
          5. Writes the pixmap (plus a text header) to a landscape PDF.
        """
        from PyQt6.QtPrintSupport import QPrinter
        from PyQt6.QtWidgets import QFileDialog, QApplication
        from PyQt6.QtGui import (
            QPainter, QColor, QFont, QPageLayout, QPageSize,
        )
        from PyQt6.QtCore import QRectF, QSizeF

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Chart to PDF",
            f"{self._symbol}_{self._interval}_chart.pdf",
            "PDF Files (*.pdf)",
        )
        if not path:
            return

        # ── Helpers ───────────────────────────────────────────────────────
        _WHITE    = QColor("white")
        _DARK_BG  = QColor(BG2)
        _PRINT_PEN = pg.mkPen("#222222", width=1)
        _DARK_PEN  = pg.mkPen(FG1, width=1)

        all_plots = [self._price_plot] + list(self._sub_plots.values())

        def _set_axes_pen(pen) -> None:
            for pw in all_plots:
                for ax in ("bottom", "left", "right", "top"):
                    try:
                        a = pw.getAxis(ax)
                        a.setPen(pen)
                        a.setTextPen(pen)
                    except Exception:
                        pass

        def _apply_print_theme() -> None:
            for pw in all_plots:
                pw.setBackground(_WHITE)
                pw.showGrid(x=True, y=True, alpha=0.18)
            _set_axes_pen(_PRINT_PEN)
            # Update the shared colour map in-place
            _C.update(_PRINT_C)

        def _restore_dark_theme() -> None:
            for pw in all_plots:
                pw.setBackground(_DARK_BG)
                pw.showGrid(x=True, y=True, alpha=0.08)
            _set_axes_pen(_DARK_PEN)
            # Restore original _C values (use saved snapshot)
            _C.update(_C_ORIG)

        # ── Save original _C state ─────────────────────────────────────────
        _C_ORIG: dict[str, str] = dict(_C)

        # ── Switch to print theme, re-render, grab ─────────────────────────
        pixmap = None
        try:
            _apply_print_theme()
            self._render()
            QApplication.processEvents()
            # Grab only the chart splitter (excludes dark toolbar rows)
            pixmap = self._splitter.grab()
        finally:
            _restore_dark_theme()
            self._render()

        if pixmap is None or pixmap.isNull():
            return

        # ── Write to PDF ───────────────────────────────────────────────────
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)

        layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Landscape,
            __import__("PyQt6.QtCore", fromlist=["QMarginsF"]).QMarginsF(10, 10, 10, 10),
            QPageLayout.Unit.Millimeter,
        )
        printer.setPageLayout(layout)

        painter = QPainter()
        if not painter.begin(printer):
            return
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            page = printer.pageRect(QPrinter.Unit.DevicePixel)
            pw, ph = page.width(), page.height()

            # Fill page white
            painter.fillRect(QRectF(0, 0, pw, ph), _WHITE)

            # Header: symbol / interval / timestamp
            from datetime import datetime, timezone
            ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            sym_str = self._symbol
            if sym_str.endswith("USDT"):
                sym_str = f"{sym_str[:-4]} — USDT"
            header = f"{sym_str}  |  {self._interval}  |  {ts_str}"
            hdr_font = QFont("monospace", 11)
            hdr_font.setBold(True)
            painter.setFont(hdr_font)
            painter.setPen(QColor("#111111"))
            header_h = 40.0
            painter.drawText(
                QRectF(0, 4, pw, header_h),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                header,
            )

            # Chart pixmap scaled to fit remaining area
            chart_y  = header_h + 8
            chart_h  = ph - chart_y - 4
            chart_w  = pw
            scaled   = pixmap.scaled(
                int(chart_w), int(chart_h),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_off = (chart_w - scaled.width())  / 2
            painter.drawPixmap(int(x_off), int(chart_y), scaled)

            # Thin border around chart area
            painter.setPen(pg.mkPen("#BBBBBB", width=1))
            painter.drawRect(
                QRectF(int(x_off), int(chart_y), scaled.width(), scaled.height())
            )
        finally:
            painter.end()

        try:
            from PyQt6.QtWidgets import QToolTip
            QToolTip.showText(
                self.mapToGlobal(self.rect().center()),
                f"Saved: {path}",
                self,
            )
        except Exception:
            pass

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

        # Trade marker layer
        self._trade_layer = TradeMarkerLayer(self._price_plot)

        # Hover tooltip for trade squares (hidden until cursor is near a marker)
        self._trade_hover = pg.TextItem(
            text="", color=FG0, anchor=(0, 1),
            border=pg.mkPen(BORDER, width=1),
            fill=pg.mkBrush(BG3 + "EE"),
        )
        font = QFont("monospace", 10)
        self._trade_hover.setFont(font)
        self._trade_hover.setVisible(False)
        self._trade_hover.setZValue(100)
        self._price_plot.addItem(self._trade_hover, ignoreBounds=True)

        # Event annotation layer (whale, cascade, funding, etc.)
        self._event_layer = EventAnnotationLayer(self._price_plot)

        # Hover tooltip for event markers
        self._event_hover = pg.TextItem(
            text="", color=FG0, anchor=(0, 1),
            border=pg.mkPen(BORDER, width=1),
            fill=pg.mkBrush(BG3 + "EE"),
        )
        self._event_hover.setFont(QFont("monospace", 10))
        self._event_hover.setVisible(False)
        self._event_hover.setZValue(101)
        self._price_plot.addItem(self._event_hover, ignoreBounds=True)

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
        self._refresh_timer = QTimer(self)
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
        # 1. Try Redis (live streaming data)
        try:
            from db.redis_client import RedisClient
            candles = RedisClient().get_candles(self._symbol, self._interval)
            if candles:
                self._data = candles
                self._render()
                return
        except Exception:
            pass

        # 2. Fallback: load from CSV / DB (works without Binance API)
        if not self._data:
            try:
                from ml.data_collector import DataCollector
                df = DataCollector.load_dataframe(self._symbol, self._interval, limit=500)
                if not df.empty:
                    import pandas as pd
                    candles = []
                    for _, row in df.iterrows():
                        ot = row["open_time"]
                        ts = ot.timestamp() if hasattr(ot, "timestamp") else float(ot)
                        candles.append({
                            "t": ts, "o": float(row["open"]),  "h": float(row["high"]),
                            "l": float(row["low"]),  "c": float(row["close"]),
                            "v": float(row["volume"]),
                        })
                    if candles:
                        self._data = candles
                        self._render()
                        return
            except Exception:
                pass

        # 3. Last resort: synthetic demo data so the chart is never blank
        if not self._data:
            try:
                import time as _time
                from ml.data_collector import DataCollector, INTERVALS
                interval_sec = INTERVALS.get(self._interval, 3600)
                end_ms   = int(_time.time() * 1000)
                start_ms = end_ms - 500 * interval_sec * 1000
                raw = DataCollector._generate_synthetic(
                    self._symbol, self._interval, start_ms, end_ms
                )
                if raw:
                    # Binance kline format: [open_time, open, high, low, close, volume, ...]
                    candles = [
                        {"t": float(r[0]) / 1000, "o": float(r[1]), "h": float(r[2]),
                         "l": float(r[3]),  "c": float(r[4]),  "v": float(r[5])}
                        for r in raw
                    ]
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

        # Session background bands (Asian / London / NY)
        self._draw_session_bands(ts)

        # Pair watermark (faint background text)
        self._draw_watermark(ts, cls)

        # Auto support/resistance levels
        self._draw_sr_levels(ts, his, los)

        # Trade entry/exit markers
        self._draw_trade_markers()
        # Re-add hover tooltip on top after clear
        if self._trade_hover:
            self._price_plot.addItem(self._trade_hover, ignoreBounds=True)
            self._trade_hover.setVisible(False)

        # Market event annotations (whale, cascade, funding, etc.)
        self._draw_event_annotations()
        if self._event_hover:
            self._price_plot.addItem(self._event_hover, ignoreBounds=True)
            self._event_hover.setVisible(False)

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

        # Auto-follow: scroll to show the latest N candles
        if self._auto_follow and len(ts) >= 2:
            span = (ts[-1] - ts[-2]) * 120   # show ~120 candles
            self._price_plot.setXRange(ts[-1] - span, ts[-1] + (ts[-1] - ts[-2]) * 2, padding=0)
        if self._auto_scale:
            self._price_plot.enableAutoRange(axis="y")

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
        panel_keys = ["volume", "rsi", "macd", "stoch", "atr", "adx"]
        sub_visible: list[bool] = []
        for key in panel_keys:
            is_vis = bool(self._panels.get(key))
            # OBV lives inside volume panel, so volume panel shows if volume OR obv is on
            if key == "volume":
                is_vis = bool(self._panels.get("volume") or self._panels.get("obv"))
            self._sub_plots[key].setVisible(is_vis)
            sub_visible.append(is_vis)

        sub_panel_height = 90
        total_sub = sum(sub_panel_height for v in sub_visible if v)
        # Ensure the main price plot always occupies more than 50% of the splitter.
        # price_height must be > total_sub so that price / (price + total_sub) > 0.5
        price_height = max(400, total_sub + 50)

        visible_heights = [price_height] + [sub_panel_height if v else 0 for v in sub_visible]
        self._splitter.setSizes(visible_heights)

    # ── Events ─────────────────────────────────────────────────────────

    def _on_mouse_move(self, pos) -> None:
        if not self._price_plot.sceneBoundingRect().contains(pos):
            if self._trade_hover:
                self._trade_hover.setVisible(False)
            return
        mp = self._price_plot.plotItem.vb.mapSceneToView(pos)
        x, y = mp.x(), mp.y()
        self._vline.setPos(x)
        self._hline.setPos(y)
        for vl in self._sub_vlines.values():
            vl.setPos(x)
        self._update_ohlcv_label(x)
        self._check_trade_hover(x, y)
        self._check_event_hover(x, y)

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

    def _check_trade_hover(self, x: float, y: float) -> None:
        """Show trade tooltip when cursor is within 1% price & 2 bars of a marker."""
        if not self._trade_hover or not self._trade_markers:
            if self._trade_hover:
                self._trade_hover.setVisible(False)
            return

        # Determine thresholds in view coordinates
        price_range = self._price_plot.viewRange()[1]
        price_span = max(1e-9, price_range[1] - price_range[0])
        price_tol  = price_span * 0.02

        time_range = self._price_plot.viewRange()[0]
        time_span  = max(1.0, time_range[1] - time_range[0])
        time_tol   = time_span * 0.015

        best = None
        best_dist = float("inf")
        for m in self._trade_markers:
            dt = abs(m["ts"] - x) / time_span
            dp = abs(m["price"] - y) / price_span
            dist = (dt ** 2 + dp ** 2) ** 0.5
            if abs(m["ts"] - x) < time_tol and abs(m["price"] - y) < price_tol:
                if dist < best_dist:
                    best_dist = dist
                    best = m

        if best:
            tooltip = self._trade_tooltip(best["trade"], best["is_entry"])
            self._trade_hover.setText(tooltip)
            self._trade_hover.setPos(best["ts"], best["price"])
            self._trade_hover.setVisible(True)
        else:
            self._trade_hover.setVisible(False)

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
        if not checked:
            self._acc_label.setText("")
        self._render()

    def _on_horizon_changed(self, text: str) -> None:
        try:
            self._forecast_horizon = int(text.rstrip("b"))
        except ValueError:
            pass
        self._render()

    def set_predictor(self, predictor) -> None:
        """Attach an MLPredictor so the forecast panel can query live signals."""
        self._predictor = predictor

    def set_forecast_tracker(self, tracker) -> None:
        """Attach a ForecastTracker to record and score predictions."""
        self._forecast_tracker = tracker

    def set_trades(self, trades: list) -> None:
        """
        Provide a list of TradeEntry objects (open or closed) to overlay on the chart.
        Call this whenever the trade journal refreshes.
        """
        self._trades = trades or []
        if self._data:
            self._draw_trade_markers()

    def _on_trades_toggled(self, checked: bool) -> None:
        self._show_trades = checked
        if self._data:
            self._draw_trade_markers()

    def _draw_trade_markers(self) -> None:
        """Render/refresh all trade squares and connecting lines on the price plot."""
        if not self._trade_layer:
            return
        if not self._show_trades or not self._trades:
            self._trade_layer.clear()
            self._trade_markers = []
            return
        self._trade_markers = self._trade_layer.draw(self._trades)

    @staticmethod
    def _trade_tooltip(trade, is_entry: bool) -> str:
        """Build the hover tooltip text for a trade marker."""
        try:
            ep  = float(trade.entry_price or 0)
            qty = float(trade.quantity or 0)
        except (TypeError, ValueError):
            ep = qty = 0.0

        entry_dt = ""
        try:
            from datetime import datetime, timezone
            raw_et = trade.entry_time or ""
            if raw_et:
                dt = datetime.fromisoformat(raw_et.replace("Z", "+00:00"))
                entry_dt = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            entry_dt = str(getattr(trade, "entry_time", ""))

        try:
            tid = str(trade.trade_id)[:8]
        except Exception:
            tid = "?"

        try:
            base = str(trade.symbol or "").replace("USDT", "")
        except Exception:
            base = ""

        label = "ENTRY" if is_entry else "EXIT"
        lines = [
            f"  {label}  ─  {tid}",
            f"  Side:    {getattr(trade, 'side', '?')}",
            f"  Entry:   {ep:.4f}  @  {entry_dt}",
            f"  Qty:     {qty:.6f} {base}",
        ]

        try:
            is_closed = (
                not getattr(trade, "is_open", True)
                and getattr(trade, "exit_price", None)
                and float(trade.exit_price or 0) > 0
            )
        except Exception:
            is_closed = False

        if is_closed:
            try:
                xp = float(trade.exit_price)
                xdt = ""
                try:
                    from datetime import datetime
                    raw_xt = trade.exit_time or ""
                    if raw_xt:
                        dt2 = datetime.fromisoformat(raw_xt.replace("Z", "+00:00"))
                        xdt = dt2.strftime("%Y-%m-%d %H:%M UTC")
                except Exception:
                    xdt = str(getattr(trade, "exit_time", ""))

                entry_val  = ep * qty
                exit_val   = xp * qty
                side       = getattr(trade, "side", "BUY")
                gross_pnl  = exit_val - entry_val if side == "BUY" else entry_val - exit_val
                total_fees = (entry_val + exit_val) * _BINANCE_FEE_PCT
                net_pnl    = gross_pnl - total_fees
                tax        = max(0.0, net_pnl * _UK_CGT_RATE)
                after_tax  = net_pnl - tax
                pct        = (gross_pnl / entry_val * 100.0) if entry_val != 0 else 0.0
                mins       = float(getattr(trade, "duration_minutes", 0) or 0)
                held_str   = (f"{int(mins // 60)}h {int(mins % 60)}m"
                             if mins >= 60 else f"{int(mins)}m")
                sign       = "+" if net_pnl >= 0 else ""
                lines += [
                    f"  Exit:    {xp:.4f}  @  {xdt}",
                    f"  Held:    {held_str}",
                    f"  Gross:   {sign}${gross_pnl:,.4f}  ({sign}{pct:.2f}%)",
                    f"  Fees:    -${total_fees:.4f}  (2 × 0.1%)",
                    f"  Tax:     -${tax:.4f}  (UK CGT 20%)",
                    f"  Net:     {sign}${after_tax:,.4f}",
                ]
            except Exception:
                lines.append("  Status:  CLOSED")
        else:
            lines.append("  Status:  OPEN")

        return "\n".join(lines)

    # ── AI Forecast overlay ────────────────────────────────────────────

    def _draw_forecast(self, ts: np.ndarray, cls: np.ndarray, his: np.ndarray,
                        los: np.ndarray) -> None:
        """
        Draw an AI price projection for self._forecast_horizon bars ahead.

        Cone width reflects both ATR volatility and horizon-based uncertainty
        decay: the longer the horizon, the wider the cone relative to ATR.

        After drawing, the forecast is recorded in ForecastTracker (throttled
        to once per MIN_RECORD_INTERVAL) and the accuracy badge is refreshed.
        """
        if not self._forecast_enabled or len(cls) < 15:
            return

        signal, confidence = self._fetch_ml_signal()
        if signal == "HOLD" or confidence < 0.45:
            self._acc_label.setText("")
            return

        n_forward  = self._forecast_horizon
        last_t     = float(ts[-1])
        spacing    = float(ts[-1] - ts[-2]) if len(ts) >= 2 else 3600.0
        last_close = float(cls[-1])

        # ATR for cone width
        atr_vals = _atr(his, los, cls, 14)
        atr_now  = float(atr_vals[-1]) if len(atr_vals) > 0 else last_close * 0.01

        # Target: confidence × ATR × horizon_factor (longer = bigger expected move)
        horizon_factor = 1.0 + np.log1p(n_forward / 5.0)
        direction = 1.0 if signal == "BUY" else -1.0
        target    = last_close + direction * confidence * atr_now * 2.5 * horizon_factor

        # Projected path: asymptotic curve toward target
        future_t   = np.array([last_t + (i + 1) * spacing for i in range(n_forward)])
        weights    = 1 - np.exp(-np.linspace(0, 2.5, n_forward))
        future_cls = last_close + (target - last_close) * weights

        # Cone: uncertainty widens faster for longer horizons
        # At the final bar: ±(1.5 + horizon/30) × ATR
        max_half = atr_now * (1.5 + n_forward / 30.0)
        cone_w   = np.linspace(atr_now * 0.1, max_half, n_forward)

        all_t   = np.concatenate([[last_t], future_t])
        all_mid = np.concatenate([[last_close], future_cls])
        all_up  = np.concatenate([[last_close], future_cls + cone_w])
        all_lo  = np.concatenate([[last_close], future_cls - cone_w])

        # Colour: green-tinted for BUY, red-tinted for SELL
        col = "#00C853" if signal == "BUY" else "#FF1744"

        mid_item = pg.PlotDataItem(all_t, all_mid,
            pen=pg.mkPen(col, width=2, style=Qt.PenStyle.DashLine))
        up_item  = pg.PlotDataItem(all_t, all_up,
            pen=pg.mkPen(col + "44", width=1, style=Qt.PenStyle.DotLine))
        lo_item  = pg.PlotDataItem(all_t, all_lo,
            pen=pg.mkPen(col + "44", width=1, style=Qt.PenStyle.DotLine))

        self._price_plot.addItem(mid_item)
        self._price_plot.addItem(up_item)
        self._price_plot.addItem(lo_item)
        self._price_plot.addItem(
            pg.FillBetweenItem(up_item, lo_item, brush=QBrush(QColor(col + "18")))
        )

        # End-of-forecast label with direction, confidence, and target
        pct_move = abs(target - last_close) / last_close * 100
        arrow = "▲" if signal == "BUY" else "▼"
        end_label = pg.TextItem(
            f" {arrow} {signal}  conf:{confidence:.0%}  "
            f"tgt:{target:.4f} ({pct_move:+.2f}%)",
            color=col, anchor=(0, 0.5),
        )
        end_label.setPos(future_t[-1], float(future_cls[-1]))
        self._price_plot.addItem(end_label, ignoreBounds=True)

        # Horizon label at top-left of price plot
        from ml.forecast_tracker import HORIZON_RELIABILITY, _expected_rate
        exp_rate = _expected_rate(n_forward)
        hl = pg.TextItem(
            f"  {n_forward}-bar forecast  |  model ceiling: {exp_rate:.0%}",
            color=FG2, anchor=(0, 0),
        )
        hl.setPos(last_t - spacing * 5, float(np.max(all_up)))
        self._price_plot.addItem(hl, ignoreBounds=True)

        # ── Record this forecast ───────────────────────────────────────
        if self._forecast_tracker:
            try:
                self._forecast_tracker.record_forecast(
                    symbol=self._symbol,
                    interval=self._interval,
                    direction=signal,
                    confidence=confidence,
                    entry_price=last_close,
                    target_price=float(target),
                    horizon_bars=n_forward,
                )
            except Exception:
                pass

        # ── Refresh accuracy badge ─────────────────────────────────────
        self._refresh_accuracy_badge(n_forward)

    def _refresh_accuracy_badge(self, horizon_bars: int) -> None:
        """Update the ACC label with live forecast accuracy from the tracker."""
        if not self._forecast_tracker:
            self._acc_label.setText("")
            return
        try:
            stats = self._forecast_tracker.get_accuracy(
                symbol=self._symbol,
                interval=self._interval,
                horizon_bars=horizon_bars,
                last_n=50,
            )
            total = stats["total"]
            if total < 3:
                self._acc_label.setText(
                    f"<span style='color:{FG2};'>ACC: — (need {3 - total} more)</span>"
                )
            else:
                rate = stats["rate"]
                exp  = stats["expected_rate"]
                pct  = rate * 100
                # Green if at or above expectation, amber if within 5%, red below
                if rate >= exp:
                    col = GREEN
                elif rate >= exp - 0.05:
                    col = YELLOW
                else:
                    col = RED
                calib_txt = ""
                c = stats["calibration"]
                if c > 1.15:
                    calib_txt = " ↑calibrated"
                elif c < 0.85:
                    calib_txt = " ↓over-conf"
                self._acc_label.setText(
                    f"<span style='color:{col};font-weight:700;'>"
                    f"ACC {pct:.0f}% ({stats['correct']}/{total})"
                    f"</span><span style='color:{FG2};font-size:10px;'>"
                    f"  expect:{exp:.0%}{calib_txt}</span>"
                )
            self._acc_label.setTextFormat(Qt.TextFormat.RichText)
        except Exception:
            self._acc_label.setText("")

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

    # ── Pair watermark ─────────────────────────────────────────────────

    def _draw_watermark(self, ts: np.ndarray, cls: np.ndarray) -> None:
        """Draw a faint bold pair-name watermark centred on the price plot."""
        if not self._overlays.get("watermark"):
            return
        sym = self._symbol
        if sym.endswith("USDT"):
            label = f"{sym[:-4]} — USDT"
        elif sym.endswith("BTC"):
            label = f"{sym[:-3]} — BTC"
        elif sym.endswith("ETH"):
            label = f"{sym[:-3]} — ETH"
        else:
            label = sym

        center_t = float((ts[0] + ts[-1]) / 2)
        center_p = float((float(cls.max()) + float(cls.min())) / 2)

        lbl = pg.TextItem(
            text=label,
            color=QColor(200, 210, 220, 14),   # ~5 % opacity
            anchor=(0.5, 0.5),
        )
        font = QFont("monospace", 52)
        font.setBold(True)
        lbl.setFont(font)
        lbl.setPos(center_t, center_p)
        self._price_plot.addItem(lbl, ignoreBounds=True)

    # ── Session background bands ───────────────────────────────────────

    def _draw_session_bands(self, ts: np.ndarray) -> None:
        """Draw Asian / London / NY session background colour bands."""
        if not self._overlays.get("sessions") or len(ts) < 2:
            return
        import datetime as _dt

        t0, t1 = float(ts[0]), float(ts[-1])
        sessions = [
            ("Asian",  0,  9, "#1A237E1A"),   # deep-blue tint
            ("London", 7, 16, "#1B5E201A"),   # deep-green tint
            ("NY",    13, 21, "#B71C1C1A"),   # deep-red tint
        ]
        # Label colours (shown at bottom of band)
        sess_label_cols = {"Asian": "#7986CB", "London": "#66BB6A", "NY": "#EF5350"}

        day_start = _dt.datetime.utcfromtimestamp(t0).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end = _dt.datetime.utcfromtimestamp(t1).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + _dt.timedelta(days=1)

        day = day_start
        while day <= day_end:
            for name, h_start, h_end, color in sessions:
                s = (day + _dt.timedelta(hours=h_start)).timestamp()
                e = (day + _dt.timedelta(hours=h_end)).timestamp()
                if e < t0 or s > t1:
                    continue
                region = pg.LinearRegionItem(
                    values=(s, e),
                    orientation="vertical",
                    movable=False,
                    brush=QBrush(QColor(color)),
                    pen=pg.mkPen(color[:7] + "00", width=0),
                )
                region.setZValue(-10)
                self._price_plot.addItem(region)
                # Session name label at top of band
                lbl = pg.TextItem(
                    text=name, color=sess_label_cols[name], anchor=(0.5, 0),
                )
                lbl.setFont(QFont("monospace", 8))
                lbl.setPos((s + e) / 2, 0)
                lbl.setParentItem(self._price_plot.getPlotItem())
                lbl.setPos((s + e) / 2, 0)
            day += _dt.timedelta(days=1)

    # ── Auto S/R levels ────────────────────────────────────────────────

    def _draw_sr_levels(self, ts: np.ndarray, his: np.ndarray, los: np.ndarray) -> None:
        """Auto-detect swing high/low clusters and draw S/R horizontal lines."""
        if not self._overlays.get("sr") or len(ts) < 20:
            return
        n      = len(ts)
        window = 5

        highs = [his[i] for i in range(window, n - window)
                 if his[i] == his[i - window:i + window + 1].max()]
        lows  = [los[i] for i in range(window, n - window)
                 if los[i] == los[i - window:i + window + 1].min()]

        def _cluster(levels: list, tol: float = 0.005) -> list:
            if not levels:
                return []
            levels = sorted(levels)
            groups: list[list[float]] = [[levels[0]]]
            for v in levels[1:]:
                if abs(v - groups[-1][-1]) / (groups[-1][-1] + 1e-9) < tol:
                    groups[-1].append(v)
                else:
                    groups.append([v])
            return [sum(g) / len(g) for g in groups]

        resistance = _cluster(highs)[-5:]
        support    = _cluster(lows)[:5]

        for lvl in resistance:
            self._price_plot.addItem(pg.InfiniteLine(
                pos=lvl, angle=0, movable=False,
                pen=pg.mkPen(RED + "88", width=1, style=Qt.PenStyle.DashLine),
                label=f"R {lvl:.4f}",
                labelOpts={"position": 0.98, "color": RED, "fill": BG3},
            ), ignoreBounds=True)
        for lvl in support:
            self._price_plot.addItem(pg.InfiniteLine(
                pos=lvl, angle=0, movable=False,
                pen=pg.mkPen(GREEN + "88", width=1, style=Qt.PenStyle.DashLine),
                label=f"S {lvl:.4f}",
                labelOpts={"position": 0.98, "color": GREEN, "fill": BG3},
            ), ignoreBounds=True)

    # ── Market event annotations ───────────────────────────────────────

    def add_chart_event(
        self,
        ts: float,
        price: float,
        event_type: str,
        label: str,
        color: str = "",
        detail: str = "",
    ) -> None:
        """
        Add a market event marker to the chart.

        Call from any thread; the chart will re-render event annotations
        immediately if data is already loaded.  Up to 200 events are kept;
        older ones are pruned automatically.
        """
        ev = ChartEvent(ts=ts, price=price, event_type=event_type,
                        label=label, color=color, detail=detail)
        self._chart_events.append(ev)
        if len(self._chart_events) > 200:
            self._chart_events = self._chart_events[-200:]
        if self._data and self._event_layer:
            self._draw_event_annotations()

    def clear_chart_events(self) -> None:
        """Remove all event annotations from the chart."""
        self._chart_events.clear()
        if self._event_layer:
            self._event_layer.clear()

    def _draw_event_annotations(self) -> None:
        if not self._event_layer:
            return
        if not self._show_events or not self._overlays.get("events"):
            self._event_layer.clear()
            return
        if self._ts is None or len(self._ts) == 0:
            return
        t_min = float(self._ts[0])
        t_max = float(self._ts[-1])
        visible = [ev for ev in self._chart_events if t_min <= ev.ts <= t_max]
        self._event_layer.draw(visible)

    def _on_events_toggled(self, checked: bool) -> None:
        self._show_events = checked
        self._overlays["events"] = checked
        if self._data:
            self._draw_event_annotations()

    def _check_event_hover(self, x: float, y: float) -> None:
        """Show event tooltip when the cursor is near an event diamond."""
        if not self._event_hover or not self._event_layer:
            return
        pr = self._price_plot.viewRange()
        price_span = max(1e-9, pr[1][1] - pr[1][0])
        time_span  = max(1.0,  pr[0][1] - pr[0][0])
        ev = self._event_layer.find_nearest(
            x, y,
            time_tol=time_span  * 0.015,
            price_tol=price_span * 0.02,
        )
        if ev:
            ts_str = datetime.utcfromtimestamp(ev.ts).strftime("%Y-%m-%d %H:%M UTC")
            lines  = [f"  {ev.event_type}  —  {ts_str}", f"  {ev.label}"]
            if ev.detail:
                lines.append(f"  {ev.detail}")
            self._event_hover.setText("\n".join(lines))
            self._event_hover.setPos(ev.ts, ev.price)
            self._event_hover.setVisible(True)
        else:
            self._event_hover.setVisible(False)
