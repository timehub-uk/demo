"""
Ping-Pong Trader UI Widget.

Displays the range-bound trading status, live range levels,
trade history and controls for the PingPongTrader service.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QProgressBar,
)

from ui.styles import ACCENT, ACCENT2, GREEN, RED, YELLOW, PURPLE,\
    BG2, BG3, BG4, BORDER, FG0, FG1, FG2


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setFixedWidth(1)
    f.setStyleSheet(f"background:{BORDER};")
    return f


def _stat_box(label: str, value: str = "—", col: str = FG1) -> tuple[QLabel, QLabel]:
    """Returns (value_label, caption_label)."""
    vl = QLabel(value)
    vl.setStyleSheet(f"color:{col}; font-size:15px; font-weight:700; font-family:monospace;")
    vl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cl = QLabel(label)
    cl.setStyleSheet(f"color:{FG2}; font-size:10px;")
    cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return vl, cl


class PingPongWidget(QWidget):
    """
    Control panel and live monitor for the Ping-Pong range trader.
    """

    symbol_changed   = pyqtSignal(str)
    _refresh_signal  = pyqtSignal()

    SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
               "ADAUSDT","DOTUSDT","LINKUSDT","AVAXUSDT","MATICUSDT"]

    def __init__(self, ping_pong_trader=None, parent=None) -> None:
        super().__init__(parent)
        self._pp = ping_pong_trader
        self._refresh_signal.connect(self._refresh)
        self._setup_ui()
        self._connect_backend()
        QTimer(self, interval=2000, timeout=self._refresh).start()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("⚡  PING-PONG RANGE TRADER")
        title.setStyleSheet(
            f"color:{ACCENT2}; font-size:13px; font-weight:700; letter-spacing:1px;"
        )
        hdr.addWidget(title)
        hdr.addStretch()
        self.state_lbl = QLabel("IDLE")
        self.state_lbl.setStyleSheet(
            f"color:{YELLOW}; font-size:12px; font-weight:700; font-family:monospace;"
        )
        hdr.addWidget(self.state_lbl)
        root.addLayout(hdr)

        # Description blurb
        info = QLabel(
            "Buys near range lows and sells near range highs in sideways / ranging markets. "
            "Automatically suspends when a trend is detected."
        )
        info.setStyleSheet(f"color:{FG2}; font-size:11px;")
        info.setWordWrap(True)
        root.addWidget(info)

        # Controls row
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Symbol:"))
        self.symbol_combo = QComboBox()
        self.symbol_combo.addItems(self.SYMBOLS)
        self.symbol_combo.setFixedWidth(130)
        self.symbol_combo.currentTextChanged.connect(self._on_symbol_changed)
        ctrl.addWidget(self.symbol_combo)
        ctrl.addWidget(_sep())
        ctrl.addWidget(QLabel("Risk %:"))
        self.risk_spin = QDoubleSpinBox()
        self.risk_spin.setRange(0.1, 5.0)
        self.risk_spin.setValue(1.0)
        self.risk_spin.setSingleStep(0.1)
        self.risk_spin.setSuffix(" %")
        self.risk_spin.setFixedWidth(80)
        self.risk_spin.valueChanged.connect(self._on_risk_changed)
        ctrl.addWidget(self.risk_spin)
        ctrl.addWidget(_sep())
        btn_style = (
            f"QPushButton {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:5px 14px; font-size:11px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{BG4}; color:{FG0}; }}"
        )
        self.start_btn = QPushButton("▶  Start")
        self.start_btn.setStyleSheet(
            btn_style.replace(f"color:{FG1}", f"color:{GREEN}")
        )
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setStyleSheet(
            btn_style.replace(f"color:{FG1}", f"color:{RED}")
        )
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        ctrl.addWidget(self.start_btn)
        ctrl.addWidget(self.stop_btn)
        ctrl.addStretch()
        root.addLayout(ctrl)

        # Stats row
        stats_frame = QFrame()
        stats_frame.setStyleSheet(
            f"QFrame {{ background:{BG3}; border:1px solid {BORDER}; border-radius:4px; }}"
        )
        sf_lay = QHBoxLayout(stats_frame)
        sf_lay.setContentsMargins(12, 6, 12, 6)

        self.val_regime,  cap_regime  = _stat_box("Regime",         "—",     ACCENT)
        self.val_range,   cap_range   = _stat_box("Range",          "—")
        self.val_zone,    cap_zone    = _stat_box("Current Zone",   "—")
        self.val_trades,  cap_trades  = _stat_box("Total Trades",   "0")
        self.val_pnl,     cap_pnl    = _stat_box("Total P&L",      "$0.00")
        self.val_losses,  cap_losses  = _stat_box("Consec. Losses", "0",     FG2)

        for val, cap in [(self.val_regime, cap_regime), (self.val_range, cap_range),
                         (self.val_zone, cap_zone), (self.val_trades, cap_trades),
                         (self.val_pnl, cap_pnl), (self.val_losses, cap_losses)]:
            col_w = QWidget()
            cl = QVBoxLayout(col_w)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(1)
            cl.addWidget(val)
            cl.addWidget(cap)
            sf_lay.addWidget(col_w)
            sf_lay.addWidget(_sep())
        root.addWidget(stats_frame)

        # Range bar visualiser
        range_grp = QGroupBox("Range Position")
        range_grp.setStyleSheet(
            f"QGroupBox {{ color:{ACCENT}; font-weight:700; border:1px solid {BORDER}; "
            f"border-radius:4px; margin-top:6px; padding-top:8px; }}"
        )
        rg_lay = QVBoxLayout(range_grp)
        range_row = QHBoxLayout()
        self.range_low_lbl  = QLabel("Low: —")
        self.range_high_lbl = QLabel("High: —")
        self.price_lbl      = QLabel("Price: —")
        for l in (self.range_low_lbl, self.price_lbl, self.range_high_lbl):
            l.setStyleSheet(f"color:{FG1}; font-size:11px; font-family:monospace;")
        range_row.addWidget(self.range_low_lbl)
        range_row.addStretch()
        range_row.addWidget(self.price_lbl)
        range_row.addStretch()
        range_row.addWidget(self.range_high_lbl)
        rg_lay.addLayout(range_row)
        self.range_bar = QProgressBar()
        self.range_bar.setRange(0, 1000)
        self.range_bar.setValue(500)
        self.range_bar.setTextVisible(False)
        self.range_bar.setFixedHeight(14)
        self.range_bar.setStyleSheet(
            f"QProgressBar {{ background:{BG2}; border:1px solid {BORDER}; border-radius:3px; }}"
            f"QProgressBar::chunk {{ background:{ACCENT}; border-radius:3px; }}"
        )
        rg_lay.addWidget(self.range_bar)
        root.addWidget(range_grp)

        # Active trade
        trade_grp = QGroupBox("Active Trade")
        trade_grp.setStyleSheet(
            f"QGroupBox {{ color:{ACCENT}; font-weight:700; border:1px solid {BORDER}; "
            f"border-radius:4px; margin-top:6px; padding-top:8px; }}"
        )
        tg_lay = QHBoxLayout(trade_grp)
        self.trade_info_lbl = QLabel("No active trade")
        self.trade_info_lbl.setStyleSheet(
            f"color:{FG2}; font-size:12px; font-family:monospace;"
        )
        tg_lay.addWidget(self.trade_info_lbl)
        tg_lay.addStretch()
        close_btn = QPushButton("Close Trade")
        close_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{RED}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:4px 10px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{BG4}; }}"
        )
        close_btn.clicked.connect(self._on_manual_close)
        tg_lay.addWidget(close_btn)
        root.addWidget(trade_grp)

        # Trade history table
        hist_grp = QGroupBox("Trade History")
        hist_grp.setStyleSheet(
            f"QGroupBox {{ color:{ACCENT}; font-weight:700; border:1px solid {BORDER}; "
            f"border-radius:4px; margin-top:6px; padding-top:8px; }}"
        )
        hg_lay = QVBoxLayout(hist_grp)
        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(
            ["Symbol", "Side", "Entry", "Exit", "P&L", "Reason", "Time"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setStyleSheet(
            f"QTableWidget {{ background:{BG2}; color:{FG1}; border:none; font-size:11px; }}"
            f"QHeaderView::section {{ background:{BG3}; color:{FG2}; border:none; padding:4px; }}"
        )
        hg_lay.addWidget(self.history_table)
        root.addWidget(hist_grp, 1)

    # ── Backend wiring ─────────────────────────────────────────────────────────

    def _connect_backend(self) -> None:
        if not self._pp:
            return
        try:
            self._pp.on_state_change(self._on_pp_state)
            self._pp.on_trade(self._on_pp_trade)
        except Exception:
            pass

    # ── Refresh ────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if not self._pp:
            return
        try:
            s = self._pp.status
        except Exception:
            return

        # State label
        state_colors = {
            "idle": FG2, "watching": ACCENT, "long": GREEN,
            "short": RED, "paused": YELLOW, "disabled": FG2,
        }
        col = state_colors.get(s.state, FG1)
        self.state_lbl.setText(s.state.upper())
        self.state_lbl.setStyleSheet(
            f"color:{col}; font-size:12px; font-weight:700; font-family:monospace;"
        )

        # Stats
        regime_col = {"RANGING": GREEN, "VOLATILE": YELLOW,
                      "TRENDING_UP": ACCENT, "TRENDING_DOWN": RED}.get(s.regime, FG2)
        self.val_regime.setText(s.regime)
        self.val_regime.setStyleSheet(
            f"color:{regime_col}; font-size:15px; font-weight:700; font-family:monospace;"
        )
        self.val_range.setText(f"{s.range_pct:.2%}")
        zone_col = {"BUY_ZONE": GREEN, "SELL_ZONE": RED, "NEUTRAL": FG2}.get(s.zone, FG2)
        self.val_zone.setText(s.zone.replace("_", " "))
        self.val_zone.setStyleSheet(
            f"color:{zone_col}; font-size:15px; font-weight:700; font-family:monospace;"
        )
        self.val_trades.setText(str(s.total_trades))
        pnl_col = GREEN if s.total_pnl >= 0 else RED
        self.val_pnl.setText(f"${s.total_pnl:+,.4f}")
        self.val_pnl.setStyleSheet(
            f"color:{pnl_col}; font-size:15px; font-weight:700; font-family:monospace;"
        )
        loss_col = RED if s.consecutive_losses >= 2 else FG2
        self.val_losses.setText(str(s.consecutive_losses))
        self.val_losses.setStyleSheet(
            f"color:{loss_col}; font-size:15px; font-weight:700; font-family:monospace;"
        )

        # Range bar
        self.range_low_lbl.setText(f"Low: {s.range_low:.4f}")
        self.range_high_lbl.setText(f"High: {s.range_high:.4f}")
        self.price_lbl.setText(f"Price: {s.current_price:.4f}")
        if s.range_high > s.range_low and s.current_price > 0:
            pct = (s.current_price - s.range_low) / (s.range_high - s.range_low)
            self.range_bar.setValue(int(pct * 1000))
            chunk_col = GREEN if pct <= 0.25 else RED if pct >= 0.75 else ACCENT
            self.range_bar.setStyleSheet(
                f"QProgressBar {{ background:{BG2}; border:1px solid {BORDER}; border-radius:3px; }}"
                f"QProgressBar::chunk {{ background:{chunk_col}; border-radius:3px; }}"
            )

        # Active trade
        if s.active_trade:
            t = s.active_trade
            pnl_est = (s.current_price - t.entry_price) * t.quantity
            if t.side == "SELL":
                pnl_est = -pnl_est
            pnl_est_col = GREEN if pnl_est >= 0 else RED
            self.trade_info_lbl.setText(
                f"{t.side}  {t.symbol}  entry={t.entry_price:.4f}  "
                f"sl={t.stop_loss:.4f}  tp={t.take_profit:.4f}  "
                f"est P&L: ${pnl_est:+,.4f}"
            )
            self.trade_info_lbl.setStyleSheet(
                f"color:{pnl_est_col}; font-size:12px; font-family:monospace;"
            )
        else:
            self.trade_info_lbl.setText("No active trade")
            self.trade_info_lbl.setStyleSheet(
                f"color:{FG2}; font-size:12px; font-family:monospace;"
            )

        # History table
        history = getattr(self._pp, "_history", [])
        recent = list(reversed(history[-50:]))
        self.history_table.setRowCount(len(recent))
        for r, t in enumerate(recent):
            pnl_col_t = GREEN if t.pnl >= 0 else RED
            vals = [
                t.symbol, t.side, f"{t.entry_price:.4f}",
                f"{t.exit_price:.4f}" if t.exit_price else "—",
                f"${t.pnl:+,.4f}" if t.exit_price else "—",
                t.exit_reason, t.entry_time[:16].replace("T", " "),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 4:
                    item.setForeground(QColor(pnl_col_t))
                elif c == 1:
                    item.setForeground(QColor(GREEN if t.side == "BUY" else RED))
                self.history_table.setItem(r, c, item)

    # ── Button handlers ────────────────────────────────────────────────────────

    def _on_start(self) -> None:
        if not self._pp:
            return
        symbol = self.symbol_combo.currentText()
        self._pp.set_risk_pct(self.risk_spin.value() / 100.0)
        self._pp.start(symbol)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _on_stop(self) -> None:
        if not self._pp:
            return
        self._pp.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _on_manual_close(self) -> None:
        if not self._pp:
            return
        try:
            self._pp._close_active_trade("MANUAL")
        except Exception:
            pass

    def _on_symbol_changed(self, symbol: str) -> None:
        if self._pp and self._pp.is_running:
            self._pp.set_symbol_live(symbol)
        self.symbol_changed.emit(symbol)

    def _on_risk_changed(self, value: float) -> None:
        if self._pp:
            try:
                self._pp.set_risk_pct(value / 100.0)
            except Exception:
                pass

    # ── Backend callbacks (called from worker thread) ──────────────────────────

    def _on_pp_state(self, status) -> None:
        self._refresh_signal.emit()

    def _on_pp_trade(self, trade) -> None:
        self._refresh_signal.emit()
