"""
Arbitrage Detector UI Widget.

Displays live arbitrage opportunities discovered by ArbitrageDetector and
executes them via ArbitrageAutoTrader.  Three tabs:

  1. Live Opportunities  — real-time scored list with one-click execution
  2. Active Positions    — currently open arb trades with live P&L
  3. Pair Statistics     — per-pair ML win-rate and cumulative P&L history

Controls:
  - Enable / Disable auto-trader
  - Paper / Live mode toggle
  - Per-trade USDT budget spinner
  - Min score / confidence filter
  - Add custom pair to scanner
  - Manual close of individual active positions
"""

from __future__ import annotations

from datetime import datetime, timezone

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QDoubleSpinBox, QLineEdit, QTabWidget, QFrame,
    QSpinBox,
)

from ui.styles import (
    ACCENT, GREEN, RED, YELLOW, ORANGE,
    BG2, BG3, BG4, BORDER, FG0, FG1, FG2,
)

BINANCE_FEE_PCT = 0.001   # 0.1% per leg


def _conf_col(conf: float) -> str:
    if conf >= 0.80:
        return GREEN
    if conf >= 0.65:
        return YELLOW
    return RED


def _vsep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setStyleSheet(f"color:{FG2}; margin:3px 2px;")
    return f


_ARB_TYPE_COLORS = {
    "STAT":        ACCENT,
    "TRIANGULAR":  YELLOW,
    "SPREAD":      ORANGE,
}


class ArbitrageWidget(QWidget):
    """Live arbitrage opportunity and auto-trader panel."""

    def __init__(self, arbitrage_detector=None, arbitrage_trader=None,
                 parent=None) -> None:
        super().__init__(parent)
        self._det    = arbitrage_detector
        self._trader = arbitrage_trader
        self._setup_ui()
        self._connect_backend()
        QTimer(self, interval=5000, timeout=self._refresh).start()
        QTimer.singleShot(2000, self._refresh)

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("⚡  ARBITRAGE DETECTOR  &  AUTO-TRADER")
        title.setStyleSheet(
            f"color:{ACCENT}; font-size:13px; font-weight:700; letter-spacing:1px;"
        )
        hdr.addWidget(title)
        hdr.addStretch()
        self._status_lbl = QLabel("Scanning…")
        self._status_lbl.setStyleSheet(
            f"color:{GREEN}; font-size:11px; font-weight:700;"
        )
        hdr.addWidget(self._status_lbl)
        root.addLayout(hdr)

        # ── Info banner ───────────────────────────────────────────────────────
        info = QLabel(
            "The ML arbitrage engine monitors cointegrated asset pairs and "
            "triangular loops in real time.  It scores each opportunity using "
            "spread z-score, cointegration half-life, expected net profit "
            "(after Binance 0.1% fees), and historical pair win rate.  "
            "When Auto-Trade is enabled it opens and closes both legs "
            "simultaneously, monitoring for z-score reversion."
        )
        info.setStyleSheet(f"color:{FG2}; font-size:11px;")
        info.setWordWrap(True)
        root.addWidget(info)

        # ── Scanner & trader controls ─────────────────────────────────────────
        ctrl_grp = QGroupBox("Scanner / Auto-Trader Controls")
        ctrl_grp.setStyleSheet(
            f"QGroupBox {{ color:{ACCENT}; font-weight:700; border:1px solid {BORDER}; "
            f"border-radius:4px; margin-top:6px; padding-top:8px; }}"
        )
        ctrl_lay = QHBoxLayout(ctrl_grp)

        # Auto-trade toggle
        self._auto_chk = QCheckBox("Auto-Trade")
        self._auto_chk.setChecked(False)
        self._auto_chk.setStyleSheet(f"color:{FG1}; font-size:11px;")
        self._auto_chk.toggled.connect(self._on_auto_toggled)
        ctrl_lay.addWidget(self._auto_chk)

        # Paper mode toggle
        self._paper_chk = QCheckBox("Paper Mode")
        self._paper_chk.setChecked(True)
        self._paper_chk.setStyleSheet(f"color:{FG1}; font-size:11px;")
        self._paper_chk.toggled.connect(self._on_paper_toggled)
        ctrl_lay.addWidget(self._paper_chk)

        ctrl_lay.addWidget(_vsep())

        # Budget
        ctrl_lay.addWidget(QLabel("Budget (USDT):"))
        self._budget_spin = QDoubleSpinBox()
        self._budget_spin.setRange(10.0, 100_000.0)
        self._budget_spin.setSingleStep(10.0)
        self._budget_spin.setValue(100.0)
        self._budget_spin.setFixedWidth(90)
        self._budget_spin.setStyleSheet(
            f"QDoubleSpinBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:3px; padding:2px; font-size:11px; }}"
        )
        self._budget_spin.valueChanged.connect(self._on_budget_changed)
        ctrl_lay.addWidget(self._budget_spin)

        ctrl_lay.addWidget(_vsep())

        # Min score filter
        ctrl_lay.addWidget(QLabel("Min score:"))
        self._min_score_spin = QDoubleSpinBox()
        self._min_score_spin.setRange(0.0, 1.0)
        self._min_score_spin.setSingleStep(0.05)
        self._min_score_spin.setValue(0.50)
        self._min_score_spin.setFixedWidth(70)
        self._min_score_spin.setStyleSheet(
            f"QDoubleSpinBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:3px; padding:2px; font-size:11px; }}"
        )
        ctrl_lay.addWidget(self._min_score_spin)

        ctrl_lay.addWidget(_vsep())

        # Add custom pair
        ctrl_lay.addWidget(QLabel("Add pair:"))
        self._pair_a_edit = QLineEdit()
        self._pair_a_edit.setPlaceholderText("e.g. BTCUSDT")
        self._pair_a_edit.setFixedWidth(95)
        self._pair_a_edit.setStyleSheet(
            f"QLineEdit {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:3px; padding:2px 4px; font-size:11px; }}"
        )
        ctrl_lay.addWidget(self._pair_a_edit)
        self._pair_b_edit = QLineEdit()
        self._pair_b_edit.setPlaceholderText("e.g. ETHUSDT")
        self._pair_b_edit.setFixedWidth(95)
        self._pair_b_edit.setStyleSheet(self._pair_a_edit.styleSheet())
        ctrl_lay.addWidget(self._pair_b_edit)

        add_btn = QPushButton("Add")
        add_btn.setFixedWidth(50)
        add_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{ACCENT}; border:1px solid {BORDER}; "
            f"border-radius:3px; padding:3px 8px; font-size:11px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{BG4}; }}"
        )
        add_btn.clicked.connect(self._on_add_pair)
        ctrl_lay.addWidget(add_btn)
        ctrl_lay.addStretch()
        root.addWidget(ctrl_grp)

        # ── Tabs ──────────────────────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabWidget::pane {{ border:1px solid {BORDER}; }}"
            f"QTabBar::tab {{ background:{BG3}; color:{FG2}; padding:5px 12px; "
            f"border:1px solid {BORDER}; margin-right:2px; border-radius:3px 3px 0 0; }}"
            f"QTabBar::tab:selected {{ background:{BG2}; color:{FG0}; font-weight:700; }}"
        )

        # Tab 1 — Live Opportunities
        tabs.addTab(self._build_opp_tab(), "Live Opportunities")

        # Tab 2 — Active Positions
        tabs.addTab(self._build_positions_tab(), "Active Positions")

        # Tab 3 — Pair Statistics
        tabs.addTab(self._build_stats_tab(), "Pair Statistics")

        root.addWidget(tabs, 1)

        # ── Bottom row ────────────────────────────────────────────────────────
        bot = QHBoxLayout()
        self._last_scan_lbl = QLabel("Last scan: —")
        self._last_scan_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        bot.addWidget(self._last_scan_lbl)
        bot.addStretch()
        scan_btn = QPushButton("⟳  Scan Now")
        scan_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{ACCENT}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:4px 12px; font-size:11px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{BG4}; }}"
        )
        scan_btn.clicked.connect(self._refresh)
        bot.addWidget(scan_btn)
        root.addLayout(bot)

    def _build_opp_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(4, 4, 4, 4)

        self._opp_table = QTableWidget(0, 8)
        self._opp_table.setHorizontalHeaderLabels([
            "Type", "Buy Leg", "Sell Leg", "Z / Return",
            "Hedge β", "Net Profit", "Confidence", "Score",
        ])
        self._opp_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._opp_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._opp_table.setAlternatingRowColors(True)
        self._opp_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._opp_table.setStyleSheet(
            f"QTableWidget {{ background:{BG2}; color:{FG1}; border:none; font-size:11px; }}"
            f"QHeaderView::section {{ background:{BG3}; color:{FG2}; border:none; padding:4px; }}"
        )
        lay.addWidget(self._opp_table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._exec_btn = QPushButton("⚡  Execute Selected Now")
        self._exec_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{YELLOW}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:5px 14px; font-size:11px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{BG4}; }}"
        )
        self._exec_btn.clicked.connect(self._on_execute_selected)
        btn_row.addWidget(self._exec_btn)
        lay.addLayout(btn_row)
        return tab

    def _build_positions_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(4, 4, 4, 4)

        self._pos_table = QTableWidget(0, 9)
        self._pos_table.setHorizontalHeaderLabels([
            "Pair", "Type", "Buy Qty", "Sell Qty",
            "Entry Z", "Buy P&L", "Sell P&L", "Net P&L", "Hold",
        ])
        self._pos_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._pos_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pos_table.setAlternatingRowColors(True)
        self._pos_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pos_table.setStyleSheet(
            f"QTableWidget {{ background:{BG2}; color:{FG1}; border:none; font-size:11px; }}"
            f"QHeaderView::section {{ background:{BG3}; color:{FG2}; border:none; padding:4px; }}"
        )
        lay.addWidget(self._pos_table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("✕  Close Selected Position")
        close_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{RED}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:5px 14px; font-size:11px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{BG4}; }}"
        )
        close_btn.clicked.connect(self._on_close_position)
        btn_row.addWidget(close_btn)
        close_all_btn = QPushButton("✕✕  Close ALL Positions")
        close_all_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{RED}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:5px 14px; font-size:11px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{BG4}; }}"
        )
        close_all_btn.clicked.connect(self._on_close_all)
        btn_row.addWidget(close_all_btn)
        lay.addLayout(btn_row)
        return tab

    def _build_stats_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(4, 4, 4, 4)

        self._stats_table = QTableWidget(0, 7)
        self._stats_table.setHorizontalHeaderLabels([
            "Pair", "Trades", "Wins", "Losses", "Win Rate", "Total P&L", "Recent Win%",
        ])
        self._stats_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._stats_table.setAlternatingRowColors(True)
        self._stats_table.setStyleSheet(
            f"QTableWidget {{ background:{BG2}; color:{FG1}; border:none; font-size:11px; }}"
            f"QHeaderView::section {{ background:{BG3}; color:{FG2}; border:none; padding:4px; }}"
        )
        lay.addWidget(self._stats_table)
        return tab

    # ── Backend wiring ─────────────────────────────────────────────────────────

    def _connect_backend(self) -> None:
        if self._det:
            try:
                self._det.on_opportunity(
                    lambda opp: QTimer.singleShot(0, self._refresh)
                )
            except Exception:
                pass
        if self._trader:
            try:
                self._trader.on_trade(
                    lambda evt: QTimer.singleShot(0, self._refresh)
                )
            except Exception:
                pass

    # ── Refresh ────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._last_scan_lbl.setText(
            f"Last scan: {datetime.utcnow().strftime('%H:%M:%S')} UTC"
        )
        self._refresh_opportunities()
        self._refresh_positions()
        self._refresh_stats()

    def _refresh_opportunities(self) -> None:
        if not self._det:
            self._status_lbl.setText("No detector attached")
            self._status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
            return

        opps = self._det.active_opportunities
        min_score = self._min_score_spin.value()
        opps = [o for o in opps if o.score >= min_score]

        count = len(opps)
        if count > 0:
            self._status_lbl.setText(
                f"{count} opportunit{'y' if count == 1 else 'ies'} found"
            )
            self._status_lbl.setStyleSheet(
                f"color:{GREEN}; font-size:11px; font-weight:700;"
            )
        else:
            self._status_lbl.setText("Scanning — no signals above threshold")
            self._status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")

        self._opp_table.setRowCount(len(opps))
        for r, opp in enumerate(opps):
            type_col = _ARB_TYPE_COLORS.get(opp.arb_type, FG2)
            conf_col = _conf_col(opp.confidence)
            leg3_str = f" / {opp.leg3}" if opp.leg3 else ""
            z_str = (
                f"{opp.spread_z:+.3f}σ" if opp.arb_type == "STAT"
                else f"{opp.spread_z:+.4f}%"
            )
            vals = [
                opp.arb_type,
                opp.leg_buy,
                opp.leg_sell + leg3_str,
                z_str,
                f"{opp.hedge_ratio:.4f}" if opp.arb_type == "STAT" else "—",
                f"{opp.expected_profit_pct:.3%}",
                f"{opp.confidence:.0%}",
                f"{opp.score:.3f}",
            ]
            colors = [
                type_col, GREEN, RED, YELLOW,
                FG1,
                GREEN if opp.expected_profit_pct > 0 else RED,
                conf_col,
                ACCENT if opp.score >= 0.7 else FG1,
            ]
            for c, (v, col) in enumerate(zip(vals, colors)):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setForeground(QColor(col))
                self._opp_table.setItem(r, c, item)

    def _refresh_positions(self) -> None:
        positions = self._trader.active_positions if self._trader else []
        self._pos_table.setRowCount(len(positions))

        for r, pos in enumerate(positions):
            buy_sym  = pos["buy_symbol"]
            sell_sym = pos["sell_symbol"]
            buy_qty  = float(pos["buy_qty"])
            sell_qty = float(pos["sell_qty"])

            # Current prices for live P&L
            cur_buy  = self._get_price(buy_sym,  pos["buy_price"])
            cur_sell = self._get_price(sell_sym, pos["sell_price"])

            pnl_buy  = (cur_buy  - pos["buy_price"])  * buy_qty
            pnl_sell = (pos["sell_price"] - cur_sell)  * sell_qty
            net_pnl  = pnl_buy + pnl_sell - 4 * BINANCE_FEE_PCT * self._budget_spin.value()

            try:
                entry_dt  = datetime.fromisoformat(pos["entry_time"])
                hold_secs = (datetime.now(timezone.utc) - entry_dt).total_seconds()
                hold_str  = (f"{int(hold_secs // 60)}m {int(hold_secs % 60)}s"
                             if hold_secs < 3600
                             else f"{int(hold_secs // 3600)}h {int((hold_secs % 3600) // 60)}m")
            except Exception:
                hold_str = "—"

            vals = [
                f"{buy_sym} / {sell_sym}",
                pos.get("arb_type", "STAT"),
                f"{buy_qty:.6f}",
                f"{sell_qty:.6f}",
                f"{pos['entry_z']:+.3f}σ",
                f"${pnl_buy:+.4f}",
                f"${pnl_sell:+.4f}",
                f"${net_pnl:+.4f}",
                hold_str,
            ]
            colors = [
                FG0, ACCENT, FG1, FG1,
                YELLOW,
                GREEN if pnl_buy >= 0 else RED,
                GREEN if pnl_sell >= 0 else RED,
                GREEN if net_pnl >= 0 else RED,
                FG2,
            ]
            for c, (v, col) in enumerate(zip(vals, colors)):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setForeground(QColor(col))
                self._pos_table.setItem(r, c, item)

    def _refresh_stats(self) -> None:
        if not self._det:
            return
        stats = self._det.pair_stats
        rows  = sorted(stats.values(), key=lambda s: -(s.wins + s.losses))
        self._stats_table.setRowCount(len(rows))
        for r, st in enumerate(rows):
            wr_col  = GREEN if st.win_rate >= 0.5 else RED
            pnl_col = GREEN if st.total_pnl >= 0 else RED
            rwr_col = GREEN if st.recent_win_rate >= 0.5 else RED
            total   = st.wins + st.losses
            vals = [
                f"{st.pair[0]} / {st.pair[1]}",
                str(total),
                str(st.wins),
                str(st.losses),
                f"{st.win_rate:.0%}",
                f"${st.total_pnl:+,.4f}",
                f"{st.recent_win_rate:.0%}",
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 4:
                    item.setForeground(QColor(wr_col))
                elif c == 5:
                    item.setForeground(QColor(pnl_col))
                elif c == 6:
                    item.setForeground(QColor(rwr_col))
                self._stats_table.setItem(r, c, item)

    # ── Controls ───────────────────────────────────────────────────────────────

    def _on_auto_toggled(self, checked: bool) -> None:
        if not self._trader:
            return
        if checked:
            self._trader.start()
            self._status_lbl.setText("Auto-trader running")
            self._status_lbl.setStyleSheet(
                f"color:{GREEN}; font-size:11px; font-weight:700;"
            )
        else:
            self._trader.stop()
            self._status_lbl.setText("Auto-trader stopped")
            self._status_lbl.setStyleSheet(
                f"color:{FG2}; font-size:11px; font-weight:700;"
            )

    def _on_paper_toggled(self, checked: bool) -> None:
        if self._trader:
            self._trader.paper_mode = checked

    def _on_budget_changed(self, value: float) -> None:
        if self._trader:
            self._trader.budget_usdt = value

    def _on_add_pair(self) -> None:
        a = self._pair_a_edit.text().strip().upper()
        b = self._pair_b_edit.text().strip().upper()
        if not a or not b or a == b:
            return
        if self._det:
            try:
                self._det.add_pair(a, b)
            except Exception:
                pass
        self._pair_a_edit.clear()
        self._pair_b_edit.clear()

    def _on_execute_selected(self) -> None:
        """Manually execute the currently selected opportunity."""
        row = self._opp_table.currentRow()
        if row < 0 or not self._det or not self._trader:
            return
        min_score = self._min_score_spin.value()
        opps = [o for o in self._det.active_opportunities if o.score >= min_score]
        if row >= len(opps):
            return
        opp = opps[row]
        pair_key = (
            f"({min(opp.leg_buy, opp.leg_sell)},{max(opp.leg_buy, opp.leg_sell)})"
        )
        self._trader._open_position(opp, pair_key)
        QTimer.singleShot(500, self._refresh)

    def _on_close_position(self) -> None:
        row = self._pos_table.currentRow()
        if row < 0 or not self._trader:
            return
        positions = self._trader.active_positions
        if row >= len(positions):
            return
        pair_key = positions[row]["pair_key"]
        self._trader.close_position(pair_key, reason="MANUAL")
        QTimer.singleShot(300, self._refresh)

    def _on_close_all(self) -> None:
        if not self._trader:
            return
        for pos in list(self._trader.active_positions):
            self._trader.close_position(pos["pair_key"], reason="MANUAL_ALL")
        QTimer.singleShot(300, self._refresh)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _get_price(self, symbol: str, fallback: float) -> float:
        """Read latest price from detector buffer or return fallback."""
        if self._det:
            buf = self._det._price_buf.get(symbol, [])
            if buf:
                return float(buf[-1])
        return float(fallback)
