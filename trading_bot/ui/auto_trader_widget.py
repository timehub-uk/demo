"""
AutoTrader Widget – live view of the MarketScanner + AutoTrader.

Layout:
  ┌─────────────────────────────────────────────────────────────────────┐
  │  AutoTrader Controls bar                                            │
  │  [State badge]  [Mode toggle]  [▶ Start]  [■ Stop]                 │
  │  [🎯 Take Aim]  [🛑 Manual Exit]  Threshold slider                 │
  ├─────────────────────────────────────────────────────────────────────┤
  │  Left pane                    │  Right pane                         │
  │  ┌──────────────────────────┐ │  ┌───────────────────────────────┐  │
  │  │  Active Trade            │ │  │  Top-5 Profit Candidates      │  │
  │  │  SL / TP / live P&L      │ │  │  table                        │  │
  │  ├──────────────────────────┤ │  ├───────────────────────────────┤  │
  │  │  Recommendation card     │ │  │  Top-5 R:R Champions          │  │
  │  │  Signal + conf + EV      │ │  │  table                        │  │
  │  └──────────────────────────┘ │  └───────────────────────────────┘  │
  ├─────────────────────────────────────────────────────────────────────┤
  │  Cycle Results table (recent closed trades with PnL)                │
  └─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QMetaObject, Q_ARG
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QFrame, QComboBox, QSlider, QSizePolicy,
)

from core.auto_trader import CycleState
from ui.styles import (
    ACCENT, GREEN, RED, YELLOW, BG2, BG3, BG4, BORDER, FG0, FG1, FG2,
)

# ── State colour map ───────────────────────────────────────────────────────────

_STATE_COLOURS = {
    "idle":       FG2,
    "scanning":   ACCENT,
    "aiming":     YELLOW,
    "entering":   GREEN,
    "monitoring": GREEN,
    "exiting":    YELLOW,
    "cooldown":   RED,
}

_STATE_ICONS = {
    "idle":       "⬤ IDLE",
    "scanning":   "🔭 SCANNING",
    "aiming":     "🎯 AIMING",
    "entering":   "▶ ENTERING",
    "monitoring": "👁 MONITORING",
    "exiting":    "⏏ EXITING",
    "cooldown":   "⏳ COOLDOWN",
}


# ── Small reusable table ───────────────────────────────────────────────────────

class _SmallTable(QTableWidget):
    def __init__(self, columns: list[str], parent=None) -> None:
        super().__init__(0, len(columns), parent)
        self.setHorizontalHeaderLabels(columns)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setDefaultSectionSize(20)
        self.setAlternatingRowColors(True)
        self.setStyleSheet(f"""
            QTableWidget {{ font-size:11px; border:none; }}
            QTableWidget::item:alternate {{ background:{BG4}; }}
        """)

    def _item(self, text: str, colour: str = FG0) -> QTableWidgetItem:
        it = QTableWidgetItem(str(text))
        it.setForeground(QBrush(QColor(colour)))
        return it

    def set_rows(self, rows: list[list]) -> None:
        self.setRowCount(0)
        for row_data in rows:
            r = self.rowCount()
            self.insertRow(r)
            for col, cell in enumerate(row_data):
                if isinstance(cell, tuple):
                    text, colour = cell
                else:
                    text, colour = cell, FG0
                self.setItem(r, col, self._item(text, colour))


# ── Active trade panel ─────────────────────────────────────────────────────────

class _ActiveTradePanel(QGroupBox):
    def __init__(self, parent=None) -> None:
        super().__init__("Active Trade", parent)
        self.setMinimumHeight(140)
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        def _row(label: str) -> tuple[QHBoxLayout, QLabel]:
            hl = QHBoxLayout()
            lbl_key = QLabel(label)
            lbl_key.setStyleSheet(f"color:{FG2}; font-size:11px;")
            lbl_key.setFixedWidth(90)
            lbl_val = QLabel("—")
            lbl_val.setStyleSheet(f"color:{FG0}; font-size:11px; font-family:monospace;")
            hl.addWidget(lbl_key)
            hl.addWidget(lbl_val)
            hl.addStretch()
            return hl, lbl_val

        r1, self.lbl_symbol   = _row("Symbol:")
        r2, self.lbl_side     = _row("Side:")
        r3, self.lbl_entry    = _row("Entry:")
        r4, self.lbl_sl_tp    = _row("SL / TP:")
        r5, self.lbl_pnl      = _row("Live P&L:")
        r6, self.lbl_conf     = _row("Confidence:")
        for r in (r1, r2, r3, r4, r5, r6):
            layout.addLayout(r)
        layout.addStretch()

    def update_trade(self, trade) -> None:
        if trade is None:
            for lbl in (self.lbl_symbol, self.lbl_side, self.lbl_entry,
                        self.lbl_sl_tp, self.lbl_pnl, self.lbl_conf):
                lbl.setText("—")
                lbl.setStyleSheet(f"color:{FG0}; font-size:11px; font-family:monospace;")
            return

        side_col = GREEN if trade.side == "BUY" else RED
        self.lbl_symbol.setText(trade.symbol)
        self.lbl_side.setText(trade.side)
        self.lbl_side.setStyleSheet(f"color:{side_col}; font-size:11px; font-family:monospace;")
        self.lbl_entry.setText(f"{trade.entry_price:.6f}")
        self.lbl_sl_tp.setText(f"{trade.stop_loss:.6f}  /  {trade.take_profit:.6f}")
        self.lbl_conf.setText(f"{trade.confidence:.0%}")

    def update_live_pnl(self, pnl: float) -> None:
        colour = GREEN if pnl >= 0 else RED
        self.lbl_pnl.setText(f"{pnl:+.4f} USDT")
        self.lbl_pnl.setStyleSheet(f"color:{colour}; font-size:11px; font-family:monospace;")


# ── Recommendation card ────────────────────────────────────────────────────────

class _RecommendationCard(QGroupBox):
    def __init__(self, parent=None) -> None:
        super().__init__("Latest Recommendation", parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self.lbl_symbol = QLabel("—")
        self.lbl_symbol.setStyleSheet(f"color:{ACCENT}; font-size:15px; font-weight:700;")
        layout.addWidget(self.lbl_symbol)

        def _row(label: str) -> tuple[QHBoxLayout, QLabel]:
            hl = QHBoxLayout()
            k = QLabel(label)
            k.setStyleSheet(f"color:{FG2}; font-size:11px;")
            k.setFixedWidth(80)
            v = QLabel("—")
            v.setStyleSheet(f"color:{FG0}; font-size:11px;")
            hl.addWidget(k)
            hl.addWidget(v)
            hl.addStretch()
            return hl, v

        r1, self.lbl_signal   = _row("Signal:")
        r2, self.lbl_conf     = _row("Confidence:")
        r3, self.lbl_rr       = _row("R:R Ratio:")
        r4, self.lbl_ev       = _row("Exp. Value:")
        r5, self.lbl_score    = _row("Combined:")
        r6, self.lbl_time     = _row("Scan time:")
        for r in (r1, r2, r3, r4, r5, r6):
            layout.addLayout(r)
        layout.addStretch()

    def update_rec(self, rec) -> None:
        if rec is None:
            self.lbl_symbol.setText("No recommendation")
            for lbl in (self.lbl_signal, self.lbl_conf, self.lbl_rr,
                        self.lbl_ev, self.lbl_score, self.lbl_time):
                lbl.setText("—")
            return

        sig_col = GREEN if rec.ensemble_signal == "BUY" else RED
        self.lbl_symbol.setText(f"{rec.direction_emoji}  {rec.symbol}")
        self.lbl_signal.setText(rec.ensemble_signal)
        self.lbl_signal.setStyleSheet(f"color:{sig_col}; font-size:11px;")
        self.lbl_conf.setText(f"{rec.ensemble_confidence:.0%}")
        self.lbl_rr.setText(f"{rec.rr_ratio:.2f}:1")
        self.lbl_ev.setText(f"{rec.expected_value:.3f}")
        self.lbl_score.setText(f"{rec.combined_score:.4f}")
        self.lbl_time.setText(rec.timestamp[:19] if rec.timestamp else "—")


# ── Main widget ────────────────────────────────────────────────────────────────

class AutoTraderWidget(QWidget):
    """
    Full AutoTrader + MarketScanner live dashboard.

    Connects to AutoTrader callbacks from the background thread and
    marshals all UI updates onto the Qt main thread via QTimer.singleShot.
    """

    # Internal signals for thread-safe UI updates
    _state_changed   = pyqtSignal(str)
    _rec_received    = pyqtSignal(object, object)   # rec, summary
    _result_received = pyqtSignal(object)           # CycleResult
    _scan_completed  = pyqtSignal(object)           # ScanSummary

    def __init__(
        self,
        auto_trader=None,
        market_scanner=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._at  = auto_trader
        self._ms  = market_scanner
        self._last_summary = None

        self._setup_ui()
        self._connect_backend()

        # Live P&L refresh timer
        self._pnl_timer = QTimer(self)
        self._pnl_timer.timeout.connect(self._refresh_live_pnl)
        self._pnl_timer.start(2000)

    # ── UI construction ────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Controls bar ──────────────────────────────────────────────
        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet(f"background:{BG3}; border:1px solid {BORDER}; border-radius:4px;")
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(8, 6, 8, 6)
        ctrl_layout.setSpacing(10)

        # State badge
        self.state_lbl = QLabel("⬤ IDLE")
        self.state_lbl.setStyleSheet(f"color:{FG2}; font-weight:700; font-size:12px; font-family:monospace;")
        ctrl_layout.addWidget(self.state_lbl)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine); sep.setStyleSheet(f"color:{BORDER};")
        ctrl_layout.addWidget(sep)

        # Mode combo
        ctrl_layout.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["SEMI_AUTO", "FULL_AUTO"])
        self.mode_combo.setFixedWidth(120)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        ctrl_layout.addWidget(self.mode_combo)

        # Confidence threshold
        ctrl_layout.addWidget(QLabel("Min Conf:"))
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(60, 99)
        self.threshold_slider.setValue(72)
        self.threshold_slider.setFixedWidth(100)
        self.threshold_slider.valueChanged.connect(self._on_threshold_changed)
        ctrl_layout.addWidget(self.threshold_slider)
        self.threshold_lbl = QLabel("72%")
        self.threshold_lbl.setStyleSheet(f"color:{ACCENT}; font-size:11px;")
        self.threshold_lbl.setFixedWidth(36)
        ctrl_layout.addWidget(self.threshold_lbl)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.VLine); sep2.setStyleSheet(f"color:{BORDER};")
        ctrl_layout.addWidget(sep2)

        # Start / Stop
        self.start_btn = QPushButton("▶ Start")
        self.start_btn.setFixedHeight(28)
        self.start_btn.setStyleSheet(f"""
            QPushButton {{ background:{BG4}; color:{GREEN}; border:1px solid {GREEN}55;
                           border-radius:4px; font-weight:600; padding:0 10px; }}
            QPushButton:hover {{ background:{GREEN}22; }}
        """)
        self.start_btn.clicked.connect(self._on_start)
        ctrl_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setFixedHeight(28)
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{ background:{BG4}; color:{RED}; border:1px solid {RED}55;
                           border-radius:4px; font-weight:600; padding:0 10px; }}
            QPushButton:hover {{ background:{RED}22; }}
        """)
        self.stop_btn.clicked.connect(self._on_stop)
        ctrl_layout.addWidget(self.stop_btn)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.Shape.VLine); sep3.setStyleSheet(f"color:{BORDER};")
        ctrl_layout.addWidget(sep3)

        # Take Aim (SEMI_AUTO confirmation)
        self.aim_btn = QPushButton("🎯 Take Aim")
        self.aim_btn.setFixedHeight(32)
        self.aim_btn.setEnabled(False)
        self.aim_btn.setStyleSheet(f"""
            QPushButton {{ background:{BG4}; color:{YELLOW}; border:1px solid {YELLOW}55;
                           border-radius:4px; font-weight:700; padding:0 14px; }}
            QPushButton:enabled:hover {{ background:{YELLOW}22; }}
            QPushButton:disabled {{ color:{FG2}; border-color:{BORDER}; }}
        """)
        self.aim_btn.clicked.connect(self._on_take_aim)
        ctrl_layout.addWidget(self.aim_btn)

        # Manual Exit
        self.exit_btn = QPushButton("🛑 Exit Trade")
        self.exit_btn.setFixedHeight(32)
        self.exit_btn.setEnabled(False)
        self.exit_btn.setStyleSheet(f"""
            QPushButton {{ background:{BG4}; color:{RED}; border:1px solid {RED}55;
                           border-radius:4px; font-weight:700; padding:0 14px; }}
            QPushButton:enabled:hover {{ background:{RED}22; }}
            QPushButton:disabled {{ color:{FG2}; border-color:{BORDER}; }}
        """)
        self.exit_btn.clicked.connect(self._on_manual_exit)
        ctrl_layout.addWidget(self.exit_btn)

        # Scan Now
        self.scan_btn = QPushButton("🔭 Scan Now")
        self.scan_btn.setFixedHeight(28)
        self.scan_btn.setStyleSheet(f"""
            QPushButton {{ background:{BG4}; color:{ACCENT}; border:1px solid {ACCENT}55;
                           border-radius:4px; font-weight:600; padding:0 10px; }}
            QPushButton:hover {{ background:{ACCENT}22; }}
        """)
        self.scan_btn.clicked.connect(self._on_scan_now)
        ctrl_layout.addWidget(self.scan_btn)

        ctrl_layout.addStretch()

        # Stats strip (right of controls)
        self.stats_lbl = QLabel("Cycles: 0 | Wins: 0 | Losses: 0 | Win Rate: — | Total P&L: —")
        self.stats_lbl.setStyleSheet(f"color:{FG1}; font-size:11px;")
        ctrl_layout.addWidget(self.stats_lbl)

        root.addWidget(ctrl_frame)

        # ── Middle splitter: left (trade + rec) | right (top5 tables) ─
        mid_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left pane
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.trade_panel = _ActiveTradePanel()
        left_layout.addWidget(self.trade_panel)

        self.rec_card = _RecommendationCard()
        left_layout.addWidget(self.rec_card)
        left_layout.addStretch()
        mid_splitter.addWidget(left)

        # Right pane: two scanner tables
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        profit_grp = QGroupBox("Top 5 – Profit Score")
        pg_layout = QVBoxLayout(profit_grp)
        self.profit_tbl = _SmallTable(["Symbol","Signal","Conf%","Momentum","MTF","Volume×","Score"])
        pg_layout.addWidget(self.profit_tbl)
        right_layout.addWidget(profit_grp, 1)

        rr_grp = QGroupBox("Top 5 – R:R Champions")
        rg_layout = QVBoxLayout(rr_grp)
        self.rr_tbl = _SmallTable(["Symbol","Signal","Conf%","R:R","WinRate%","EV","RR Score"])
        rg_layout.addWidget(self.rr_tbl)
        right_layout.addWidget(rr_grp, 1)

        mid_splitter.addWidget(right)
        mid_splitter.setSizes([320, 680])
        root.addWidget(mid_splitter, 2)

        # ── Cycle results table ──────────────────────────────────────────
        results_grp = QGroupBox("Cycle Results")
        rr_layout = QVBoxLayout(results_grp)
        self.results_tbl = _SmallTable(
            ["#","Symbol","Side","Entry","Exit","P&L","P&L%","Reason","Duration","Time"]
        )
        rr_layout.addWidget(self.results_tbl)
        root.addWidget(results_grp, 1)

    # ── Backend connection ─────────────────────────────────────────────

    def _connect_backend(self) -> None:
        # Connect internal Qt signals (thread-safe)
        self._state_changed.connect(self._on_state_update)
        self._rec_received.connect(self._on_rec_update)
        self._result_received.connect(self._on_result_update)
        self._scan_completed.connect(self._on_scan_update)

        if self._at:
            self._at.on_state_change(
                lambda state: self._state_changed.emit(state.value)
            )
            self._at.on_recommendation(
                lambda rec, summary: self._rec_received.emit(rec, summary)
            )
            self._at.on_cycle_result(
                lambda result: self._result_received.emit(result)
            )

        if self._ms:
            self._ms.on_scan_complete(
                lambda summary: self._scan_completed.emit(summary)
            )
            # Load any cached summary immediately
            if self._ms.last_summary:
                self._on_scan_update(self._ms.last_summary)

    # ── Qt slot handlers (always on main thread) ───────────────────────

    def _on_state_update(self, state_val: str) -> None:
        colour = _STATE_COLOURS.get(state_val, FG2)
        label  = _STATE_ICONS.get(state_val, state_val.upper())
        self.state_lbl.setText(label)
        self.state_lbl.setStyleSheet(
            f"color:{colour}; font-weight:700; font-size:12px; font-family:monospace;"
        )
        is_aiming     = (state_val == "aiming")
        is_monitoring = (state_val == "monitoring")
        self.aim_btn.setEnabled(is_aiming)
        self.exit_btn.setEnabled(is_monitoring)
        # Update trade panel when entering / monitoring
        if self._at:
            self.trade_panel.update_trade(self._at.active_trade)
            self._refresh_stats()

    def _on_rec_update(self, rec, summary) -> None:
        self.rec_card.update_rec(rec)
        self._on_scan_update(summary)

    def _on_result_update(self, result) -> None:
        self._append_cycle_result(result)
        self.trade_panel.update_trade(None)
        if self._at:
            self._refresh_stats()

    def _on_scan_update(self, summary) -> None:
        self._last_summary = summary
        self.rec_card.update_rec(summary.recommendation)
        self._populate_profit_table(summary.top_profit)
        self._populate_rr_table(summary.top_rr)

    # ── Table population ───────────────────────────────────────────────

    def _populate_profit_table(self, pairs: list) -> None:
        rows = []
        for p in pairs:
            sig_col = GREEN if p.ensemble_signal == "BUY" else RED
            rows.append([
                (p.symbol, ACCENT),
                (p.ensemble_signal, sig_col),
                (f"{p.ensemble_confidence:.0%}", FG0),
                (f"{p.momentum_score:.2f}", FG0),
                (f"{p.mtf_confluence_score:.2f}", FG0),
                (f"{p.volume_spike:.1f}×", FG0),
                (f"{p.profit_score:.4f}", YELLOW),
            ])
        self.profit_tbl.set_rows(rows)

    def _populate_rr_table(self, pairs: list) -> None:
        rows = []
        for p in pairs:
            sig_col = GREEN if p.ensemble_signal == "BUY" else RED
            ev_col  = GREEN if p.expected_value > 0 else RED
            rows.append([
                (p.symbol, ACCENT),
                (p.ensemble_signal, sig_col),
                (f"{p.ensemble_confidence:.0%}", FG0),
                (f"{p.rr_ratio:.2f}:1", FG0),
                (f"{p.historical_win_rate:.0%}", FG0),
                (f"{p.expected_value:.3f}", ev_col),
                (f"{p.rr_score:.4f}", YELLOW),
            ])
        self.rr_tbl.set_rows(rows)

    def _append_cycle_result(self, result) -> None:
        pnl_col = GREEN if result.pnl >= 0 else RED
        reason_col = GREEN if result.exit_reason == "TP" else RED if result.exit_reason == "SL" else YELLOW
        r = self.results_tbl.rowCount()
        self.results_tbl.insertRow(r)
        cells = [
            (str(result.cycle_num), FG2),
            (result.symbol, ACCENT),
            (result.side, GREEN if result.side == "BUY" else RED),
            (f"{result.entry_price:.4f}", FG0),
            (f"{result.exit_price:.4f}", FG0),
            (f"{result.pnl:+.4f}", pnl_col),
            (f"{result.pnl_pct:+.1f}%", pnl_col),
            (result.exit_reason, reason_col),
            (f"{result.duration_sec/60:.1f}m", FG1),
            (result.timestamp[:19] if result.timestamp else "—", FG2),
        ]
        for col, (text, colour) in enumerate(cells):
            it = QTableWidgetItem(text)
            it.setForeground(QBrush(QColor(colour)))
            self.results_tbl.setItem(r, col, it)
        # Keep newest at top by scrolling
        self.results_tbl.scrollToBottom()

    # ── Live P&L refresh ───────────────────────────────────────────────

    def _refresh_live_pnl(self) -> None:
        if not self._at:
            return
        trade = self._at.active_trade
        if trade is None:
            return
        try:
            from db.redis_client import RedisClient
            t = RedisClient().get_ticker(trade.symbol)
            if t:
                price = float(t.get("price", 0))
                if trade.side == "BUY":
                    pnl = (price - trade.entry_price) * trade.quantity
                else:
                    pnl = (trade.entry_price - price) * trade.quantity
                self.trade_panel.update_live_pnl(pnl)
        except Exception:
            pass

    # ── Stats ─────────────────────────────────────────────────────────

    def _refresh_stats(self) -> None:
        if not self._at:
            return
        s = self._at.stats
        pnl_col = GREEN if s["total_pnl"] >= 0 else RED
        wr_pct  = s["win_rate"] * 100
        self.stats_lbl.setText(
            f"Cycles: {s['total_cycles']} | "
            f"Trades: {s['total_trades']} | "
            f"Wins: {s['wins']} | "
            f"Losses: {s['losses']} | "
            f"Win Rate: {wr_pct:.0f}% | "
            f"Total P&L: {s['total_pnl']:+.2f} USDT"
        )

    # ── Control button handlers ────────────────────────────────────────

    def _on_mode_changed(self, mode_text: str) -> None:
        if not self._at:
            return
        from core.auto_trader import AutoTraderMode
        self._at.set_mode(AutoTraderMode(mode_text.lower()))

    def _on_threshold_changed(self, value: int) -> None:
        self.threshold_lbl.setText(f"{value}%")
        if self._at:
            self._at.set_auto_threshold(value / 100.0)

    def _on_start(self) -> None:
        if self._at and self._at.state == CycleState.IDLE:
            self._at.start()

    def _on_stop(self) -> None:
        if self._at:
            self._at.stop()

    def _on_take_aim(self) -> None:
        if self._at:
            self._at.take_aim()
            self.aim_btn.setEnabled(False)

    def _on_manual_exit(self) -> None:
        if self._at:
            self._at.manual_exit()

    def _on_scan_now(self) -> None:
        if self._ms:
            import threading
            threading.Thread(
                target=self._ms.scan_now, daemon=True, name="manual-scan"
            ).start()
