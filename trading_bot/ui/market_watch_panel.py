"""
Market Watch Panel – Unified real-time surveillance dashboard.

Tabs:
  0  📊 Volume Alerts   – large volume movements + whale event feed
  1  🤖 ML Watch        – live ML signals, model confidence, signal history
  2  ⚡ Order Flow      – per-symbol OFI + aggressor ratio bars
  3  🗂  Heatmap         – portfolio exposure colour grid (P&L + size)
  4  🌊 Regime & Cascade – market regime per symbol + cascade alerts
  5  🔴 Kill Switch     – emergency halt controls

All sub-panels are thread-safe via pyqtSignal.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QSizePolicy, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget, QProgressBar, QGridLayout, QScrollArea,
)

from ui.styles import (
    ACCENT, GREEN, RED, YELLOW, PURPLE,
    BG0, BG1, BG2, BG3, BG4, BORDER, BORDER2,
    FG0, FG1, FG2,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_TAB_STYLE = f"""
    QTabWidget::pane {{ border:1px solid {BORDER}; background:{BG1}; }}
    QTabBar::tab {{
        background:{BG3}; color:{FG2}; padding:6px 14px;
        border:none; font-size:11px;
    }}
    QTabBar::tab:selected {{ background:{BG4}; color:{FG0}; font-weight:700; }}
    QTabBar::tab:hover {{ color:{ACCENT}; }}
"""

_TABLE_STYLE = f"""
    QTableWidget {{ font-size:11px; border:none; background:{BG2}; gridline-color:{BORDER}; }}
    QHeaderView::section {{
        background:{BG3}; color:{FG1}; font-size:10px; font-weight:700;
        padding:3px 6px; border:none; border-bottom:1px solid {BORDER};
    }}
    QTableWidget::item:alternate {{ background:{BG3}; }}
"""

_GRP_STYLE = f"""
    QGroupBox {{
        font-size:11px; font-weight:700; color:{FG1};
        border:1px solid {BORDER}; border-radius:4px; margin-top:6px; padding-top:8px;
    }}
    QGroupBox::title {{ subcontrol-origin:margin; left:8px; padding:0 4px; }}
"""

_BTN = (
    f"QPushButton {{"
    f"  background:{BG4}; color:{FG0}; border:1px solid {BORDER2};"
    f"  border-radius:4px; font-size:11px; padding:4px 12px;"
    f"}}"
    f"QPushButton:hover {{ background:{ACCENT}22; border-color:{ACCENT}; color:{ACCENT}; }}"
    f"QPushButton:pressed {{ background:{ACCENT}44; }}"
)
_BTN_DANGER = (
    f"QPushButton {{"
    f"  background:#3A0808; color:{RED}; border:2px solid {RED};"
    f"  border-radius:6px; font-size:13px; font-weight:700; padding:8px 20px;"
    f"}}"
    f"QPushButton:hover {{ background:#5A1010; }}"
    f"QPushButton:pressed {{ background:#7A1818; }}"
)

def _hsep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{BORDER};")
    return f


def _cell(text: str, color: str = FG0, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setForeground(QBrush(QColor(color)))
    it.setTextAlignment(int(align) | int(Qt.AlignmentFlag.AlignVCenter))
    return it


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 0 – Volume / Whale Alerts
# ─────────────────────────────────────────────────────────────────────────────

class VolumeAlertTab(QWidget):
    """
    Live feed of:
      • Large volume movements (VOLUME_SPIKE, EARLY_PUMP, CASCADE alerts)
      • Whale events from WhaleWatcher
      • Funding rate extremes
    """

    _row_signal = pyqtSignal(list)   # [ts, type, symbol, message, extra]

    # Row colours per event type keyword
    _COLOURS = {
        "CASCADE":      RED,
        "VOLUME_SPIKE": YELLOW,
        "EARLY_PUMP":   ACCENT,
        "FUNDING_RATE": PURPLE,
        "WHALE":        "#FF8C00",
        "LEAD_LAG":     "#00BFFF",
        "AGGRESSOR":    "#7CFC00",
    }

    def __init__(self, alert_manager=None, whale_watcher=None,
                 funding_monitor=None, cascade_detector=None, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._row_signal.connect(self._append_row)

        if alert_manager:
            alert_manager.register_callback(self._on_alert)
        if whale_watcher:
            try:
                whale_watcher.on_event(self._on_whale_event)
            except Exception:
                pass
        if funding_monitor:
            funding_monitor.on_event(self._on_funding_event)
        if cascade_detector:
            cascade_detector.on_event(self._on_cascade_event)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        grp = QGroupBox("Live Volume & Whale Alert Feed")
        grp.setStyleSheet(_GRP_STYLE)
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(4, 8, 4, 4)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Time", "Type", "Symbol", "Details", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for c in (0, 1, 2, 4):
            self.table.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setStyleSheet(_TABLE_STYLE)
        gl.addWidget(self.table)

        btns = QHBoxLayout()
        clear = QPushButton("Clear")
        clear.setStyleSheet(_BTN)
        clear.setFixedHeight(24)
        clear.clicked.connect(lambda: self.table.setRowCount(0))
        btns.addWidget(clear)
        btns.addStretch()
        self._count_lbl = QLabel("0 events")
        self._count_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        btns.addWidget(self._count_lbl)
        gl.addLayout(btns)
        root.addWidget(grp, 1)

    def _on_alert(self, alert) -> None:
        from core.alert_manager import AlertType
        watched = {
            AlertType.VOLUME_SPIKE, AlertType.EARLY_PUMP, AlertType.CASCADE,
            AlertType.FUNDING_RATE, AlertType.LEAD_LAG, AlertType.AGGRESSOR,
        }
        if alert.alert_type not in watched:
            return
        atype = alert.alert_type.value
        extra = ""
        data = alert.data or {}
        if "rate" in data:
            extra = f"{float(data['rate'])*100:+.4f}%"
        elif "vol_ratio" in data:
            extra = f"{float(data['vol_ratio']):.1f}× vol"
        elif "aggressor_1m" in data:
            extra = f"{float(data['aggressor_1m']):.0%} buy"
        self._row_signal.emit([_ts(), atype, alert.symbol, alert.message, extra])

    def _on_whale_event(self, ev) -> None:
        ev_type = str(getattr(ev, "event_type", "WHALE"))
        symbol  = str(getattr(ev, "symbol", ""))
        vol_usd = float(getattr(ev, "volume_usd", 0))
        conf    = float(getattr(ev, "confidence", 0))
        msg     = f"{ev_type} | conf {conf:.0%}"
        extra   = f"${vol_usd:,.0f}"
        self._row_signal.emit([_ts(), "WHALE", symbol, msg, extra])

    def _on_funding_event(self, ev) -> None:
        from core.funding_rate_monitor import FundingRateEvent
        self._row_signal.emit([
            _ts(), "FUNDING_RATE", ev.symbol,
            f"Extreme funding: {ev.rate_pct:+.4f}% ({ev.direction})",
            f"${ev.price:,.4f}",
        ])

    def _on_cascade_event(self, ev) -> None:
        from core.cascade_detector import CascadeEvent
        self._row_signal.emit([
            _ts(), "CASCADE", ev.symbol,
            f"Liquidation cascade {ev.direction}: {ev.price_change:+.2%} [{ev.severity}]",
            f"{ev.vol_ratio:.1f}× vol",
        ])

    def _append_row(self, cells: list) -> None:
        ts, atype, symbol, details, value = cells
        col = self._COLOURS.get(atype, FG0)
        r = 0
        self.table.insertRow(r)
        self.table.setItem(r, 0, _cell(ts))
        self.table.setItem(r, 1, _cell(atype, col))
        self.table.setItem(r, 2, _cell(symbol, ACCENT))
        self.table.setItem(r, 3, _cell(details))
        self.table.setItem(r, 4, _cell(value, col, Qt.AlignmentFlag.AlignRight))
        while self.table.rowCount() > 300:
            self.table.removeRow(self.table.rowCount() - 1)
        self._count_lbl.setText(f"{self.table.rowCount()} events")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 – ML Watch
# ─────────────────────────────────────────────────────────────────────────────

class MLWatchTab(QWidget):
    """Live ML signal feed + per-symbol confidence summary."""

    _sig_signal  = pyqtSignal(dict)
    _conf_signal = pyqtSignal(str, float, str)   # symbol, confidence, action

    def __init__(self, predictor=None, continuous_learner=None,
                 whale_watcher=None, parent=None) -> None:
        super().__init__(parent)
        self._conf: dict[str, tuple[float, str]] = {}   # symbol → (conf, action)
        self._setup_ui()
        self._sig_signal.connect(self._append_signal)
        self._conf_signal.connect(self._update_conf_row)

        if predictor:
            try:
                predictor.on_signal(self._on_ml_signal)
            except Exception:
                pass
        if continuous_learner:
            try:
                continuous_learner.on_signal(self._on_ml_signal)
            except Exception:
                pass
        if whale_watcher:
            try:
                whale_watcher.on_event(self._on_whale_signal)
            except Exception:
                pass

    def _setup_ui(self) -> None:
        root = QSplitter(Qt.Orientation.Vertical)
        root.setStyleSheet(f"QSplitter::handle {{ background:{BORDER}; }}")

        # ── Confidence summary ─────────────────────────────────────────
        top = QGroupBox("Model Confidence by Symbol")
        top.setStyleSheet(_GRP_STYLE)
        tl = QVBoxLayout(top)
        tl.setContentsMargins(4, 8, 4, 4)

        self.conf_table = QTableWidget(0, 4)
        self.conf_table.setHorizontalHeaderLabels(["Symbol", "Action", "Confidence", "Source"])
        self.conf_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.conf_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.conf_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.conf_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.conf_table.verticalHeader().setVisible(False)
        self.conf_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.conf_table.setStyleSheet(_TABLE_STYLE)
        tl.addWidget(self.conf_table)
        root.addWidget(top)

        # ── Signal feed ────────────────────────────────────────────────
        bot = QGroupBox("Live Signal Feed")
        bot.setStyleSheet(_GRP_STYLE)
        bl = QVBoxLayout(bot)
        bl.setContentsMargins(4, 8, 4, 4)

        self.sig_table = QTableWidget(0, 5)
        self.sig_table.setHorizontalHeaderLabels(["Time", "Symbol", "Action", "Confidence", "Source"])
        self.sig_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.sig_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.sig_table.verticalHeader().setVisible(False)
        self.sig_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sig_table.setAlternatingRowColors(True)
        self.sig_table.verticalHeader().setDefaultSectionSize(20)
        self.sig_table.setStyleSheet(_TABLE_STYLE)
        bl.addWidget(self.sig_table)
        root.addWidget(bot)

        root.setSizes([200, 400])

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.addWidget(root, 1)

    def _on_ml_signal(self, sig: dict) -> None:
        self._sig_signal.emit(sig)

    def _on_whale_signal(self, ev) -> None:
        try:
            from ml.whale_watcher import WhaleEvent
            sym   = getattr(ev, "symbol", "")
            etype = str(getattr(ev, "event_type", "WHALE"))
            conf  = float(getattr(ev, "confidence", 0))
            self._sig_signal.emit({
                "symbol":     sym,
                "action":     "WATCH",
                "confidence": conf,
                "source":     f"Whale/{etype}",
            })
        except Exception:
            pass

    def add_signal(self, sig: dict) -> None:
        self._sig_signal.emit(sig)

    def _append_signal(self, sig: dict) -> None:
        sym    = sig.get("symbol", "—")
        action = sig.get("action", sig.get("signal", "HOLD"))
        conf   = float(sig.get("confidence", 0))
        source = sig.get("source", "ML")

        action_col = {
            "BUY": GREEN, "SELL": RED, "HOLD": FG2, "WATCH": YELLOW,
        }.get(action.upper(), FG1)

        r = 0
        self.sig_table.insertRow(r)
        self.sig_table.setItem(r, 0, _cell(_ts()))
        self.sig_table.setItem(r, 1, _cell(sym, ACCENT))
        self.sig_table.setItem(r, 2, _cell(action, action_col))
        self.sig_table.setItem(r, 3, _cell(f"{conf:.0%}", action_col))
        self.sig_table.setItem(r, 4, _cell(source))
        while self.sig_table.rowCount() > 500:
            self.sig_table.removeRow(self.sig_table.rowCount() - 1)

        # Update confidence summary
        self._conf_signal.emit(sym, conf, action)

    def _update_conf_row(self, symbol: str, conf: float, action: str) -> None:
        # Find existing row for symbol
        for r in range(self.conf_table.rowCount()):
            if self.conf_table.item(r, 0) and self.conf_table.item(r, 0).text() == symbol:
                self._fill_conf_row(r, symbol, action, conf)
                return
        # Insert new row sorted by symbol
        r = self.conf_table.rowCount()
        self.conf_table.insertRow(r)
        self._fill_conf_row(r, symbol, action, conf)

    def _fill_conf_row(self, r: int, sym: str, action: str, conf: float) -> None:
        col = {
            "BUY": GREEN, "SELL": RED, "HOLD": FG2, "WATCH": YELLOW,
        }.get(action.upper(), FG1)
        self.conf_table.setItem(r, 0, _cell(sym, ACCENT))
        self.conf_table.setItem(r, 1, _cell(action, col))
        bar_item = QTableWidgetItem()
        bar_item.setData(Qt.ItemDataRole.DisplayRole, f"{conf:.0%}")
        bar_item.setForeground(QBrush(QColor(col)))
        self.conf_table.setItem(r, 2, bar_item)
        self.conf_table.setItem(r, 3, _cell("ML", FG2))


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 – Order Flow (OFI)
# ─────────────────────────────────────────────────────────────────────────────

class OFITab(QWidget):
    """Per-symbol aggressor ratio bars + OFI delta table."""

    _snap_signal = pyqtSignal(object)

    def __init__(self, ofi_monitor=None, parent=None) -> None:
        super().__init__(parent)
        self._rows: dict[str, int] = {}   # symbol → table row
        self._setup_ui()
        self._snap_signal.connect(self._update_row)

        if ofi_monitor:
            ofi_monitor.on_snapshot(self._on_snapshot)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        grp = QGroupBox("Order Flow Imbalance – Aggressor Ratio per Symbol")
        grp.setStyleSheet(_GRP_STYLE)
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(4, 8, 4, 4)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Symbol", "Signal 1m", "Aggr 1m", "Aggr 5m",
            "OFI 1m (USD)", "OFI 5m (USD)", "Updated",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(_TABLE_STYLE)
        gl.addWidget(self.table)
        root.addWidget(grp, 1)

        note = QLabel(
            "Aggressor ratio: % of volume initiated by market orders.  "
            "≥ 72% = BUY_PRESSURE (smart money buying)  ·  "
            "≤ 28% = SELL_PRESSURE (distribution)"
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{FG2}; font-size:10px; padding:4px;")
        root.addWidget(note)

    def _on_snapshot(self, snap) -> None:
        self._snap_signal.emit(snap)

    def _update_row(self, snap) -> None:
        sym = snap.symbol
        if sym not in self._rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._rows[sym] = r
        r = self._rows[sym]

        sig   = snap.signal_1m
        sig_col = {
            "BUY_PRESSURE":  GREEN,
            "SELL_PRESSURE": RED,
            "NEUTRAL":       FG2,
        }.get(sig, FG2)

        aggr1 = snap.aggressor_1m
        aggr5 = snap.aggressor_5m
        bar_col = GREEN if aggr1 >= 0.72 else (RED if aggr1 <= 0.28 else YELLOW)

        self.table.setItem(r, 0, _cell(sym, ACCENT))
        self.table.setItem(r, 1, _cell(sig, sig_col))
        self.table.setItem(r, 2, _cell(f"{aggr1:.0%}", bar_col))
        self.table.setItem(r, 3, _cell(f"{aggr5:.0%}", FG1))
        self.table.setItem(r, 4, _cell(f"{snap.ofi_1m:+,.0f}", GREEN if snap.ofi_1m > 0 else RED))
        self.table.setItem(r, 5, _cell(f"{snap.ofi_5m:+,.0f}", GREEN if snap.ofi_5m > 0 else RED))
        self.table.setItem(r, 6, _cell(_ts(), FG2))


# ─────────────────────────────────────────────────────────────────────────────
# Tab 3 – Portfolio Heatmap
# ─────────────────────────────────────────────────────────────────────────────

class HeatmapTab(QWidget):
    """
    Colour-coded tile grid showing all portfolio positions.

    Tile colour: green (profitable) → red (losing)
    Tile brightness: proportional to position size in USD
    """

    _update_signal = pyqtSignal(list)   # list of position dicts

    def __init__(self, portfolio=None, parent=None) -> None:
        super().__init__(parent)
        self._portfolio = portfolio
        self._tiles: dict[str, QLabel] = {}
        self._setup_ui()
        self._update_signal.connect(self._rebuild_grid)

        # Poll portfolio every 5 s
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        QTimer.singleShot(500, self._poll)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel(
            "<b style='color:{};font-size:12px;'>Portfolio Exposure Heatmap</b>".format(ACCENT)
        ))
        hdr.setAlignment(Qt.AlignmentFlag.AlignLeft)
        hdr.addStretch()
        self._total_lbl = QLabel("Total: $0.00")
        self._total_lbl.setStyleSheet(f"color:{FG1}; font-size:11px;")
        hdr.addWidget(self._total_lbl)
        root.addLayout(hdr)

        root.addWidget(_hsep())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border:none; background:{BG1}; }}")

        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet(f"background:{BG1};")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(6)
        scroll.setWidget(self._grid_widget)
        root.addWidget(scroll, 1)

        legend = QLabel(
            "■ Dark green = large profit  ·  ■ Light green = small profit  ·  "
            "■ Light red = small loss  ·  ■ Dark red = large loss  ·  "
            "Tile size reflects position USD value"
        )
        legend.setWordWrap(True)
        legend.setStyleSheet(f"color:{FG2}; font-size:10px; padding:4px;")
        root.addWidget(legend)

    def _poll(self) -> None:
        if not self._portfolio:
            return
        try:
            positions = []
            if hasattr(self._portfolio, "get_positions"):
                raw = self._portfolio.get_positions()
            elif hasattr(self._portfolio, "positions"):
                raw = self._portfolio.positions
            else:
                return

            for pos in (raw if isinstance(raw, list) else raw.values()):
                if hasattr(pos, "__dict__"):
                    d = pos.__dict__
                else:
                    d = dict(pos)
                positions.append(d)
            if positions:
                self._update_signal.emit(positions)
        except Exception:
            pass

    def _rebuild_grid(self, positions: list) -> None:
        # Clear grid
        for i in reversed(range(self._grid.count())):
            w = self._grid.itemAt(i).widget()
            if w:
                w.deleteLater()
        self._tiles.clear()

        if not positions:
            lbl = QLabel("No open positions")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"color:{FG2}; font-size:14px;")
            self._grid.addWidget(lbl, 0, 0)
            return

        total = 0.0
        for i, pos in enumerate(positions):
            sym     = str(pos.get("symbol", "???"))
            pnl     = float(pos.get("unrealised_pnl", pos.get("pnl", 0)) or 0)
            size_usd = float(pos.get("value_usd", pos.get("notional_usd",
                              pos.get("qty", 0) * pos.get("price", 1) or 50)) or 50)
            total += size_usd

            pnl_pct = pnl / size_usd if size_usd else 0

            # Colour based on P&L %
            if pnl_pct >= 0.02:
                bg = "#004400"
            elif pnl_pct >= 0.005:
                bg = "#002200"
            elif pnl_pct >= 0:
                bg = "#001A00"
            elif pnl_pct >= -0.005:
                bg = "#1A0000"
            elif pnl_pct >= -0.02:
                bg = "#330000"
            else:
                bg = "#550000"

            txt_col = GREEN if pnl >= 0 else RED
            size_px = max(60, min(140, int(size_usd / 10)))

            tile = QLabel(
                f"<div style='text-align:center;'>"
                f"<b style='font-size:11px;color:{ACCENT};'>{sym.replace('USDT','')}</b><br>"
                f"<span style='font-size:10px;color:{txt_col};'>{pnl:+.2f}</span><br>"
                f"<span style='font-size:9px;color:{FG2};'>${size_usd:,.0f}</span>"
                f"</div>"
            )
            tile.setTextFormat(Qt.TextFormat.RichText)
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.setFixedSize(size_px, size_px)
            tile.setStyleSheet(
                f"background:{bg}; border:1px solid {BORDER}; border-radius:6px; padding:4px;"
            )

            row, col = divmod(i, 6)
            self._grid.addWidget(tile, row, col)
            self._tiles[sym] = tile

        self._total_lbl.setText(f"Total: ${total:,.0f}")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 4 – Regime & Cascade
# ─────────────────────────────────────────────────────────────────────────────

class RegimeCascadeTab(QWidget):
    """Market regime per symbol + cascade event feed."""

    _regime_signal  = pyqtSignal(str, str)    # symbol, regime
    _cascade_signal = pyqtSignal(object)
    _leadlag_signal = pyqtSignal(object)
    _funding_signal = pyqtSignal(object)

    def __init__(
        self, regime_detector=None, cascade_detector=None,
        correlation_engine=None, funding_monitor=None, parent=None
    ) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._regime_signal.connect(self._update_regime_row)
        self._cascade_signal.connect(self._append_cascade)
        self._leadlag_signal.connect(self._append_leadlag)
        self._funding_signal.connect(self._append_funding)

        if regime_detector:
            try:
                regime_detector.on_regime_change(
                    lambda sym, regime: self._regime_signal.emit(sym, str(regime))
                )
            except Exception:
                pass

        if cascade_detector:
            cascade_detector.on_event(lambda ev: self._cascade_signal.emit(ev))

        if correlation_engine:
            correlation_engine.on_event(lambda ev: self._leadlag_signal.emit(ev))

        if funding_monitor:
            funding_monitor.on_event(lambda ev: self._funding_signal.emit(ev))

        # Poll regime every 30 s if detector available
        if regime_detector:
            self._regime_timer = QTimer(self)
            self._regime_timer.setInterval(30000)
            self._regime_timer.timeout.connect(
                lambda: self._poll_regimes(regime_detector)
            )
            self._regime_timer.start()
            QTimer.singleShot(1000, lambda: self._poll_regimes(regime_detector))

    def _setup_ui(self) -> None:
        root = QSplitter(Qt.Orientation.Horizontal)
        root.setStyleSheet(f"QSplitter::handle {{ background:{BORDER}; width:2px; }}")

        # ── Left: regime table ─────────────────────────────────────────
        left = QGroupBox("Market Regime")
        left.setStyleSheet(_GRP_STYLE)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(4, 8, 4, 4)

        self.regime_table = QTableWidget(0, 3)
        self.regime_table.setHorizontalHeaderLabels(["Symbol", "Regime", "Updated"])
        self.regime_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.regime_table.verticalHeader().setVisible(False)
        self.regime_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.regime_table.setStyleSheet(_TABLE_STYLE)
        ll.addWidget(self.regime_table)
        root.addWidget(left)

        # ── Right: event feed ──────────────────────────────────────────
        right = QGroupBox("Cascade / Lead-Lag / Funding Events")
        right.setStyleSheet(_GRP_STYLE)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 8, 4, 4)

        self.event_table = QTableWidget(0, 4)
        self.event_table.setHorizontalHeaderLabels(["Time", "Type", "Symbol", "Details"])
        self.event_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.event_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.event_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.event_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.event_table.verticalHeader().setVisible(False)
        self.event_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.event_table.setAlternatingRowColors(True)
        self.event_table.verticalHeader().setDefaultSectionSize(20)
        self.event_table.setStyleSheet(_TABLE_STYLE)
        rl.addWidget(self.event_table)
        root.addWidget(right)

        root.setSizes([300, 500])

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.addWidget(root, 1)

    _REGIME_COLOURS = {
        "BULL":     GREEN,
        "BEAR":     RED,
        "RANGING":  YELLOW,
        "VOLATILE": PURPLE,
        "LOW_VOL":  FG2,
    }

    def _poll_regimes(self, detector) -> None:
        try:
            regimes = detector.get_all_regimes()
            for sym, regime in (regimes if isinstance(regimes, dict) else {}).items():
                self._regime_signal.emit(sym, str(regime))
        except Exception:
            pass

    def _update_regime_row(self, symbol: str, regime: str) -> None:
        if not hasattr(self, "_regime_rows_map"):
            self._regime_rows_map: dict[str, int] = {}
        rm = self._regime_rows_map
        regime_upper = regime.upper().replace(" ", "_")
        col = self._REGIME_COLOURS.get(regime_upper, FG1)
        if symbol not in rm:
            r = self.regime_table.rowCount()
            self.regime_table.insertRow(r)
            rm[symbol] = r
        r = rm[symbol]
        self.regime_table.setItem(r, 0, _cell(symbol, ACCENT))
        self.regime_table.setItem(r, 1, _cell(regime_upper, col))
        self.regime_table.setItem(r, 2, _cell(_ts(), FG2))

    def _append_event_row(self, etype: str, symbol: str, details: str, col: str) -> None:
        r = 0
        self.event_table.insertRow(r)
        self.event_table.setItem(r, 0, _cell(_ts()))
        self.event_table.setItem(r, 1, _cell(etype, col))
        self.event_table.setItem(r, 2, _cell(symbol, ACCENT))
        self.event_table.setItem(r, 3, _cell(details))
        while self.event_table.rowCount() > 200:
            self.event_table.removeRow(self.event_table.rowCount() - 1)

    def _append_cascade(self, ev) -> None:
        self._append_event_row(
            f"CASCADE {ev.direction}",
            ev.symbol,
            f"{ev.price_change:+.2%} | {ev.vol_ratio:.1f}× vol [{ev.severity}]",
            RED if ev.direction == "DOWN" else GREEN,
        )

    def _append_leadlag(self, ev) -> None:
        self._append_event_row(
            "LEAD/LAG",
            ev.follower,
            f"{ev.leader} moved {ev.leader_move:+.2%} → expect {ev.follower} {ev.expected_move}"
            f"  (r={ev.correlation:.2f})",
            YELLOW,
        )

    def _append_funding(self, ev) -> None:
        col = RED if ev.rate > 0 else GREEN
        self._append_event_row(
            "FUNDING",
            ev.symbol,
            f"{ev.rate_pct:+.4f}% ({ev.direction})",
            col,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tab 5 – Kill Switch
# ─────────────────────────────────────────────────────────────────────────────

class KillSwitchTab(QWidget):
    """
    Emergency halt controls:
      • Cancel all open orders (all symbols)
      • Pause AutoTrader immediately
      • Set engine to PAPER mode
      • Emergency: do all three at once
    """

    def __init__(
        self, engine=None, auto_trader=None, order_manager=None, parent=None
    ) -> None:
        super().__init__(parent)
        self._engine       = engine
        self._auto_trader  = auto_trader
        self._order_mgr    = order_manager
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Warning banner
        warn = QLabel(
            "⚠️  EMERGENCY CONTROLS – Actions are immediate and irreversible"
        )
        warn.setStyleSheet(
            f"background:#2A1A00; color:{YELLOW}; font-size:12px; font-weight:700;"
            f"border:1px solid {YELLOW}; border-radius:4px; padding:8px;"
        )
        warn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(warn)

        # Individual actions
        grp = QGroupBox("Individual Actions")
        grp.setStyleSheet(_GRP_STYLE)
        gl = QVBoxLayout(grp)
        gl.setSpacing(8)

        actions = [
            ("Cancel All Open Orders",   YELLOW, self._cancel_orders,
             "Sends cancel to Binance for every open order on all symbols."),
            ("Pause AutoTrader",         YELLOW, self._pause_at,
             "Stops the AutoTrader from entering new positions.  Existing positions unchanged."),
            ("Switch to PAPER Mode",     ACCENT, self._paper_mode,
             "Switches the trading engine to paper mode — orders are simulated, not sent."),
        ]
        for label, col, fn, tip in actions:
            row = QHBoxLayout()
            btn = QPushButton(label)
            btn.setStyleSheet(
                f"QPushButton {{ background:{BG4}; color:{col}; border:1px solid {col};"
                f"border-radius:4px; font-size:11px; font-weight:700; padding:6px 16px; }}"
                f"QPushButton:hover {{ background:{col}22; }}"
            )
            btn.setFixedHeight(36)
            btn.clicked.connect(fn)
            tip_lbl = QLabel(tip)
            tip_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
            tip_lbl.setWordWrap(True)
            row.addWidget(btn)
            row.addWidget(tip_lbl, 1)
            gl.addLayout(row)
        root.addWidget(grp)

        # Big red emergency button
        egrp = QGroupBox("Emergency Stop – All At Once")
        egrp.setStyleSheet(_GRP_STYLE)
        el = QVBoxLayout(egrp)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._emergency_btn = QPushButton("🔴  EMERGENCY STOP")
        self._emergency_btn.setStyleSheet(_BTN_DANGER)
        self._emergency_btn.setMinimumHeight(60)
        self._emergency_btn.setMinimumWidth(280)
        self._emergency_btn.clicked.connect(self._emergency_stop)
        el.addWidget(self._emergency_btn, 0, Qt.AlignmentFlag.AlignCenter)

        sub = QLabel("Cancels all orders + pauses AutoTrader + switches to PAPER mode")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color:{FG2}; font-size:10px; margin-top:4px;")
        el.addWidget(sub)
        root.addWidget(egrp)

        # Status log
        self._log = QLabel("Ready.")
        self._log.setStyleSheet(
            f"background:{BG3}; color:{FG1}; font-size:11px; font-family:monospace;"
            f"border:1px solid {BORDER}; border-radius:4px; padding:6px;"
        )
        self._log.setWordWrap(True)
        root.addWidget(self._log)
        root.addStretch()

    # ── Actions ──────────────────────────────────────────────────────────────

    def _log_msg(self, msg: str) -> None:
        ts = _ts()
        self._log.setText(f"[{ts}] {msg}")
        from utils.logger import get_intel_logger
        get_intel_logger().warning("KillSwitch", msg)

    def _cancel_orders(self) -> None:
        reply = QMessageBox.question(
            self, "Confirm", "Cancel ALL open orders on all symbols?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            if self._order_mgr:
                self._order_mgr.cancel_all_orders()
                self._log_msg("All open orders cancelled.")
            elif self._engine and hasattr(self._engine, "cancel_all_orders"):
                self._engine.cancel_all_orders()
                self._log_msg("All open orders cancelled via engine.")
            else:
                self._log_msg("No order manager available — cannot cancel.")
        except Exception as exc:
            self._log_msg(f"Cancel orders failed: {exc}")

    def _pause_at(self) -> None:
        try:
            if self._auto_trader:
                if hasattr(self._auto_trader, "pause"):
                    self._auto_trader.pause()
                elif hasattr(self._auto_trader, "stop"):
                    self._auto_trader.stop()
                self._log_msg("AutoTrader paused.")
            else:
                self._log_msg("AutoTrader not available.")
        except Exception as exc:
            self._log_msg(f"Pause AutoTrader failed: {exc}")

    def _paper_mode(self) -> None:
        try:
            if self._engine:
                self._engine.set_mode("paper")
                self._log_msg("Engine switched to PAPER mode.")
            else:
                self._log_msg("Engine not available.")
        except Exception as exc:
            self._log_msg(f"Paper mode switch failed: {exc}")

    def _emergency_stop(self) -> None:
        reply = QMessageBox.critical(
            self,
            "EMERGENCY STOP",
            "This will:\n\n"
            "  1. Cancel ALL open orders\n"
            "  2. Pause the AutoTrader\n"
            "  3. Switch engine to PAPER mode\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        msgs = []
        try:
            if self._order_mgr:
                self._order_mgr.cancel_all_orders()
                msgs.append("orders cancelled")
        except Exception as exc:
            msgs.append(f"cancel failed: {exc}")
        try:
            if self._auto_trader:
                if hasattr(self._auto_trader, "pause"):
                    self._auto_trader.pause()
                elif hasattr(self._auto_trader, "stop"):
                    self._auto_trader.stop()
                msgs.append("AT paused")
        except Exception as exc:
            msgs.append(f"AT pause failed: {exc}")
        try:
            if self._engine:
                self._engine.set_mode("paper")
                msgs.append("PAPER mode")
        except Exception as exc:
            msgs.append(f"paper failed: {exc}")
        self._log_msg("EMERGENCY STOP: " + " | ".join(msgs))
        self._emergency_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{GREEN}; border:2px solid {GREEN};"
            f"border-radius:6px; font-size:13px; font-weight:700; padding:8px 20px; }}"
        )
        self._emergency_btn.setText("✅  EMERGENCY STOP EXECUTED")


# ─────────────────────────────────────────────────────────────────────────────
# Main panel
# ─────────────────────────────────────────────────────────────────────────────

class MarketWatchPanel(QWidget):
    """
    Unified Market Watch dashboard.
    Instantiate with any subset of services; missing ones degrade gracefully.
    """

    def __init__(
        self,
        alert_manager=None,
        whale_watcher=None,
        funding_monitor=None,
        cascade_detector=None,
        ofi_monitor=None,
        portfolio=None,
        regime_detector=None,
        correlation_engine=None,
        predictor=None,
        continuous_learner=None,
        engine=None,
        auto_trader=None,
        order_manager=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._setup_ui(
            alert_manager, whale_watcher, funding_monitor, cascade_detector,
            ofi_monitor, portfolio, regime_detector, correlation_engine,
            predictor, continuous_learner, engine, auto_trader, order_manager,
        )

    def _setup_ui(self, am, ww, fm, cd, ofi, port, rd, ce, pred, cl, eng, at, om) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toggle bar ────────────────────────────────────────────────────────
        toggle_bar = QFrame()
        toggle_bar.setFixedHeight(32)
        toggle_bar.setStyleSheet(
            f"QFrame {{ background:{BG0}; border-bottom:1px solid {BORDER}; }}"
        )
        tbl = QHBoxLayout(toggle_bar)
        tbl.setContentsMargins(8, 0, 8, 0)
        tbl.setSpacing(6)

        title = QLabel("Market Watch")
        title.setStyleSheet(
            f"color:{ACCENT}; font-size:11px; font-weight:700; padding-right:12px;"
        )
        tbl.addWidget(title)

        # Map: (label, service_obj)
        _toggles = [
            ("Funding",     fm),
            ("Order Flow",  ofi),
            ("Correlation", ce),
            ("Cascade",     cd),
        ]
        for label, svc in _toggles:
            if svc is None:
                continue
            btn = QPushButton(f"● {label}")
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setFixedHeight(22)
            btn.setStyleSheet(
                f"QPushButton {{ background:{BG4}; color:{GREEN}; border:1px solid {GREEN}55;"
                f"  border-radius:3px; font-size:10px; padding:0 8px; }}"
                f"QPushButton:!checked {{ color:{FG2}; border-color:{BORDER}; }}"
                f"QPushButton:hover {{ border-color:{ACCENT}; }}"
            )
            _svc = svc   # closure
            def _on_toggle(checked, s=_svc):
                if checked:
                    try:
                        s.enable()
                    except Exception:
                        pass
                else:
                    try:
                        s.disable()
                    except Exception:
                        pass
            btn.toggled.connect(_on_toggle)
            tbl.addWidget(btn)

        tbl.addStretch()
        root.addWidget(toggle_bar)

        # ── Tabs ──────────────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        tabs = self.tabs
        tabs.setStyleSheet(_TAB_STYLE)

        self.volume_tab = VolumeAlertTab(am, ww, fm, cd)
        tabs.addTab(self.volume_tab,    "📊  Volume Alerts")

        self.ml_tab = MLWatchTab(pred, cl, ww)
        tabs.addTab(self.ml_tab,        "🤖  ML Watch")

        self.ofi_tab = OFITab(ofi)
        tabs.addTab(self.ofi_tab,       "⚡  Order Flow")

        self.heatmap_tab = HeatmapTab(port)
        tabs.addTab(self.heatmap_tab,   "🗂  Heatmap")

        self.regime_tab = RegimeCascadeTab(rd, cd, ce, fm)
        tabs.addTab(self.regime_tab,    "🌊  Regime & Cascade")

        self.kill_tab = KillSwitchTab(eng, at, om)
        tabs.addTab(self.kill_tab,      "🔴  Kill Switch")

        root.addWidget(tabs, 1)

    # ── Proxy methods so main_window can forward events ──────────────────────

    def add_ml_signal(self, sig: dict) -> None:
        self.ml_tab.add_signal(sig)
