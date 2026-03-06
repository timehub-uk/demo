"""
Trade Journal UI Widget.

Displays the full trade audit trail with performance statistics,
source attribution, and export functionality.

Layout:
  ┌─────────────────────────────────────────────────────────┐
  │  [Today] [All] [Export CSV]         Summary stats row   │
  ├─────────────┬───────────────────────────────────────────┤
  │ Open Trades │ Closed Trades table                       │
  │ (live)      │ Symbol | Side | Entry | Exit | P&L | ...  │
  ├─────────────┴───────────────────────────────────────────┤
  │ Source Attribution table (win rates per ML signal src)  │
  └─────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import csv
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QGroupBox, QFileDialog, QMessageBox, QFrame,
)

from ui.styles import ACCENT, GREEN, RED, YELLOW, BG2, BG3, BG4, BORDER, FG0, FG1, FG2


def _hdr(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{ACCENT}; font-size:13px; font-weight:700; letter-spacing:1px;"
    )
    return lbl


def _stat(label: str, value: str, col: str = FG1) -> QWidget:
    w = QFrame()
    w.setStyleSheet(
        f"QFrame {{ background:{BG3}; border:1px solid {BORDER}; border-radius:4px; padding:4px; }}"
    )
    lay = QVBoxLayout(w)
    lay.setContentsMargins(8, 4, 8, 4)
    lay.setSpacing(1)
    lbl = QLabel(value)
    lbl.setStyleSheet(f"color:{col}; font-size:16px; font-weight:700; font-family:monospace;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cap = QLabel(label)
    cap.setStyleSheet(f"color:{FG2}; font-size:10px;")
    cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(lbl)
    lay.addWidget(cap)
    return w


class TradeJournalWidget(QWidget):
    """Full trade journal panel."""

    def __init__(self, trade_journal=None, parent=None) -> None:
        super().__init__(parent)
        self._journal = trade_journal
        self._show_all = False
        self._setup_ui()
        QTimer(self, interval=10_000, timeout=self._refresh).start()
        QTimer.singleShot(500, self._refresh)

    # ── UI ─────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Header row
        hdr = QHBoxLayout()
        hdr.addWidget(_hdr("📒  TRADE JOURNAL"))
        hdr.addStretch()
        btn_today = QPushButton("Today")
        btn_today.setFixedWidth(70)
        btn_today.clicked.connect(self._show_today)
        btn_all = QPushButton("All Trades")
        btn_all.setFixedWidth(80)
        btn_all.clicked.connect(self._show_all_trades)
        btn_export = QPushButton("Export CSV")
        btn_export.setFixedWidth(90)
        btn_export.clicked.connect(self._export_csv)
        for b in (btn_today, btn_all, btn_export):
            b.setStyleSheet(
                f"QPushButton {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
                f"border-radius:4px; padding:4px 8px; font-size:11px; }}"
                f"QPushButton:hover {{ background:{BG4}; color:{FG0}; }}"
            )
            hdr.addWidget(b)
        root.addLayout(hdr)

        # Stats row
        self._stats_row = QHBoxLayout()
        self.stat_trades = _stat("Trades Today", "—")
        self.stat_pnl    = _stat("P&L Today",    "—")
        self.stat_winrate = _stat("Win Rate",     "—")
        self.stat_avg_dur = _stat("Avg Duration", "—")
        self.stat_open    = _stat("Open Trades",  "—")
        for w in (self.stat_trades, self.stat_pnl, self.stat_winrate,
                  self.stat_avg_dur, self.stat_open):
            self._stats_row.addWidget(w)
        root.addLayout(self._stats_row)

        # Main splitter: open trades (left) + closed trades (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Open trades
        open_grp = QGroupBox("Open Trades")
        open_grp.setStyleSheet(
            f"QGroupBox {{ color:{ACCENT}; font-weight:700; border:1px solid {BORDER}; "
            f"border-radius:4px; margin-top:6px; padding-top:8px; }}"
        )
        og_lay = QVBoxLayout(open_grp)
        self.open_table = QTableWidget(0, 6)
        self.open_table.setHorizontalHeaderLabels(
            ["Symbol", "Side", "Entry", "SL", "TP", "Regime"]
        )
        self.open_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.open_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.open_table.setAlternatingRowColors(True)
        self.open_table.setStyleSheet(
            f"QTableWidget {{ background:{BG2}; color:{FG1}; border:none; font-size:11px; }}"
            f"QHeaderView::section {{ background:{BG3}; color:{FG2}; border:none; padding:4px; }}"
        )
        og_lay.addWidget(self.open_table)
        splitter.addWidget(open_grp)

        # Closed trades
        closed_grp = QGroupBox("Closed Trades")
        closed_grp.setStyleSheet(
            f"QGroupBox {{ color:{ACCENT}; font-weight:700; border:1px solid {BORDER}; "
            f"border-radius:4px; margin-top:6px; padding-top:8px; }}"
        )
        cg_lay = QVBoxLayout(closed_grp)
        self.closed_table = QTableWidget(0, 9)
        self.closed_table.setHorizontalHeaderLabels(
            ["Symbol", "Side", "Entry", "Exit", "P&L", "Duration",
             "Regime", "Exit Reason", "Council"]
        )
        self.closed_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.closed_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.closed_table.setAlternatingRowColors(True)
        self.closed_table.setStyleSheet(
            f"QTableWidget {{ background:{BG2}; color:{FG1}; border:none; font-size:11px; }}"
            f"QHeaderView::section {{ background:{BG3}; color:{FG2}; border:none; padding:4px; }}"
        )
        cg_lay.addWidget(self.closed_table)
        splitter.addWidget(closed_grp)

        splitter.setSizes([280, 720])
        root.addWidget(splitter, 2)

        # Source attribution table
        attr_grp = QGroupBox("Signal Source Attribution (Win Rate)")
        attr_grp.setStyleSheet(
            f"QGroupBox {{ color:{ACCENT}; font-weight:700; border:1px solid {BORDER}; "
            f"border-radius:4px; margin-top:6px; padding-top:8px; }}"
        )
        ag_lay = QVBoxLayout(attr_grp)
        self.attr_table = QTableWidget(0, 5)
        self.attr_table.setHorizontalHeaderLabels(
            ["Source", "Total", "Wins", "Losses", "Win Rate"]
        )
        self.attr_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.attr_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.attr_table.setFixedHeight(160)
        self.attr_table.setStyleSheet(
            f"QTableWidget {{ background:{BG2}; color:{FG1}; border:none; font-size:11px; }}"
            f"QHeaderView::section {{ background:{BG3}; color:{FG2}; border:none; padding:4px; }}"
        )
        ag_lay.addWidget(self.attr_table)
        root.addWidget(attr_grp)

    # ── Refresh ─────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if not self._journal:
            return
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _fetch_and_update(self) -> None:
        try:
            open_trades = self._journal.get_open_trades()
            closed = self._journal.get_closed_trades(limit=200)
            summary = self._journal.daily_summary()
            attribution = self._journal.source_attribution()
        except Exception:
            return

        # Filter if showing today only
        if not self._show_all:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            closed = [t for t in closed if t.get("exit_time", "").startswith(today)]

        from PyQt6.QtCore import QTimer as _QT
        _QT.singleShot(0, lambda: self._update_ui(
            open_trades, closed, summary, attribution))

    def _update_ui(self, open_trades, closed, summary, attribution) -> None:
        # Stats
        n = summary.get("total_trades", 0)
        pnl = summary.get("pnl", 0.0)
        wr = summary.get("win_rate", 0.0)
        dur = summary.get("avg_duration_min", 0.0)

        def _set_stat(widget, label, value, col):
            for w in widget.children():
                from PyQt6.QtWidgets import QLabel
                if isinstance(w, QLabel) and w.styleSheet() and "font-size:16px" in w.styleSheet():
                    w.setText(value)
                    w.setStyleSheet(
                        f"color:{col}; font-size:16px; font-weight:700; font-family:monospace;"
                    )
                    break

        pnl_col = GREEN if pnl >= 0 else RED
        _set_stat(self.stat_trades, "Trades Today", str(n), FG1)
        _set_stat(self.stat_pnl,    "P&L Today", f"${pnl:+,.2f}", pnl_col)
        _set_stat(self.stat_winrate, "Win Rate", f"{wr:.0%}", GREEN if wr >= 0.5 else RED)
        _set_stat(self.stat_avg_dur, "Avg Duration", f"{dur:.0f}m", FG1)
        _set_stat(self.stat_open, "Open Trades", str(len(open_trades)), YELLOW)

        # Open trades
        self.open_table.setRowCount(len(open_trades))
        for r, t in enumerate(open_trades):
            vals = [
                t.symbol, t.side, f"{t.entry_price:.4f}",
                f"{t.stop_loss:.4f}", f"{t.take_profit:.4f}", t.regime,
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                col = GREEN if t.side == "BUY" else RED
                if c == 1:
                    item.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(col))
                self.open_table.setItem(r, c, item)

        # Closed trades
        self.closed_table.setRowCount(len(closed))
        for r, t in enumerate(closed):
            pnl_val = t.get("pnl", 0.0)
            pnl_col_t = GREEN if pnl_val > 0 else RED
            vals = [
                t.get("symbol", ""),
                t.get("side", ""),
                f"{t.get('entry_price', 0):.4f}",
                f"{t.get('exit_price', 0):.4f}",
                f"${pnl_val:+,.2f}",
                f"{t.get('duration_minutes', 0):.0f}m",
                t.get("regime", ""),
                t.get("exit_reason", ""),
                f"{t.get('council_final', '')} {t.get('council_confidence', 0):.0%}",
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 4:  # P&L column
                    from PyQt6.QtGui import QColor
                    item.setForeground(QColor(pnl_col_t))
                self.closed_table.setItem(r, c, item)

        # Attribution
        rows = sorted(attribution.items(), key=lambda x: -x[1].get("total", 0))
        self.attr_table.setRowCount(len(rows))
        for r, (src, d) in enumerate(rows):
            wr_val = d.get("win_rate", 0.0)
            wr_col = GREEN if wr_val >= 0.5 else RED
            vals = [
                src, str(d.get("total", 0)), str(d.get("wins", 0)),
                str(d.get("losses", 0)), f"{wr_val:.0%}",
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 4:
                    from PyQt6.QtGui import QColor
                    item.setForeground(QColor(wr_col))
                self.attr_table.setItem(r, c, item)

    # ── Filter toggles ──────────────────────────────────────────────────

    def _show_today(self) -> None:
        self._show_all = False
        self._refresh()

    def _show_all_trades(self) -> None:
        self._show_all = True
        self._refresh()

    # ── Export ──────────────────────────────────────────────────────────

    def _export_csv(self) -> None:
        if not self._journal:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Trade Journal", "trade_journal.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            trades = self._journal.get_closed_trades(limit=10000)
            if not trades:
                QMessageBox.information(self, "Export", "No closed trades to export.")
                return
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=trades[0].keys())
                writer.writeheader()
                writer.writerows(trades)
            QMessageBox.information(self, "Export",
                f"Exported {len(trades)} trades to:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", str(exc))
