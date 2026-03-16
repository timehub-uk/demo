"""
Gap Detector Widget — Displays price gap signals from the GapDetector ML tool.

Two action types:
  GAP DOWN ↓ — green rows  — Action: BUY (buy cheap, target = prior close above = profit)
  GAP UP   ↑ — gold rows   — Action: WATCH (gap fill needs a short; spot platform = monitor only)

Columns:
  Type | Symbol | TF | State | Action | Gap% | Fill% | Fill Target | Distance | Score | Age | VolX | RSI | Note
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QFrame, QSplitter,
)
from loguru import logger

from ui.styles import (
    ACCENT, BG1, BG2, BG3, BG4, BORDER, BORDER2,
    FG0, FG1, FG2, GREEN, RED, YELLOW,
)

try:
    from ml.gap_detector import GapDetector, GapResult
except Exception:
    GapDetector = None   # type: ignore[assignment, misc]
    GapResult   = None   # type: ignore[assignment, misc]


# ── Color maps ────────────────────────────────────────────────────────────────
_GAP_TYPE_COLOR = {
    "DOWN": "#00CC66",   # green  — BUY opportunity (cheap entry, target above)
    "UP":   "#FFD700",   # gold   — WATCH (gap fill needs short; spot only = monitor)
}
_GAP_TYPE_BG = {
    "DOWN": "#0A1A0A",
    "UP":   "#1A1800",
}
_STATE_COLOR = {
    "OPEN":    "#00D4FF",   # cyan  — active signal
    "PARTIAL": "#FFB347",   # amber — partially filled
    "FILLED":  "#888888",   # grey  — no longer actionable
    "STALE":   "#555555",   # dim   — too old
}
_ACTION_BG = {
    "BUY":   "#0A2010",
    "WATCH": "#1A1800",
}

_COLS = [
    "",           # 0  type emoji
    "Symbol",     # 1
    "TF",         # 2  timeframe
    "State",      # 3
    "Action",     # 4
    "Gap %",      # 5
    "Fill %",     # 6  fill progress
    "FillProb",   # 7  ML fill probability
    "Fill Target",# 8
    "Dist %",     # 9  distance from current price to fill target
    "Score",      # 10
    "Age",        # 11 age in bars
    "Vol×",       # 12 volume ratio
    "RSI",        # 13
    "Note",       # 14
]


class GapSummaryBar(QFrame):
    """
    Compact stats strip showing counts of open gap-up (BUY) and gap-down (WATCH) signals.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(38)
        self.setStyleSheet(f"QFrame {{ background:{BG2}; border-bottom:1px solid {BORDER}; }}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(20)

        self._lbl_ups   = self._make_stat("GAP DOWN (BUY)", "0", GREEN)
        self._lbl_downs = self._make_stat("GAP UP (WATCH)", "0", YELLOW)
        self._lbl_total = self._make_stat("Total Open", "0", FG1)

        for w in (self._lbl_ups, self._lbl_downs, self._lbl_total):
            layout.addWidget(w)

        layout.addStretch()

        self._scan_lbl = QLabel("—")
        self._scan_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        layout.addWidget(self._scan_lbl)

    def _make_stat(self, label: str, value: str, color: str) -> QLabel:
        lbl = QLabel()
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setText(
            f"<span style='color:{FG2}; font-size:10px;'>{label}: </span>"
            f"<span style='color:{color}; font-size:14px; font-weight:bold;'>{value}</span>"
        )
        return lbl

    def update(self, downs_buy: int, ups_watch: int, ts: str) -> None:
        total = downs_buy + ups_watch
        self._lbl_ups.setText(
            f"<span style='color:{FG2}; font-size:10px;'>GAP DOWN (BUY): </span>"
            f"<span style='color:{GREEN}; font-size:14px; font-weight:bold;'>{downs_buy}</span>"
        )
        self._lbl_downs.setText(
            f"<span style='color:{FG2}; font-size:10px;'>GAP UP (WATCH): </span>"
            f"<span style='color:{YELLOW}; font-size:14px; font-weight:bold;'>{ups_watch}</span>"
        )
        self._lbl_total.setText(
            f"<span style='color:{FG2}; font-size:10px;'>Total Open: </span>"
            f"<span style='color:{FG1}; font-size:14px; font-weight:bold;'>{total}</span>"
        )
        self._scan_lbl.setText(f"Updated {ts}")


class GapDetectorWidget(QWidget):
    """
    Price gap detector dashboard.

    Shows all detected gaps across all scanned pairs and timeframes.
    GAP UP  → green rows, BUY action  (target = gap fill level)
    GAP DOWN → gold rows, WATCH action

    Instantiate with a ``GapDetector`` instance (or None for demo mode).
    """

    # Emitted when user double-clicks a symbol row → main window follows the symbol
    symbol_selected  = pyqtSignal(str)
    _refresh_signal  = pyqtSignal()

    def __init__(
        self,
        gap_detector: Optional[GapDetector] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._detector = gap_detector
        self._results:  list[GapResult] = []
        self._filter_type  = "ALL"
        self._filter_state = "OPEN"
        self._filter_tf    = "ALL"

        self._refresh_signal.connect(self._refresh_table)
        self._build_ui()
        self._connect_detector()

        self._timer = QTimer(self)
        self._timer.setInterval(60_000)   # auto-refresh every minute
        self._timer.timeout.connect(self._refresh_table)
        self._timer.start()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Title bar ─────────────────────────────────────────────────────────
        title_bar = QFrame()
        title_bar.setFixedHeight(42)
        title_bar.setStyleSheet(
            f"QFrame {{ background:{BG2}; border-bottom:1px solid {BORDER2}; }}"
        )
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(12, 0, 12, 0)
        tb_layout.setSpacing(12)

        title_lbl = QLabel("Gap Detector — ML Chart Gap Scanner")
        title_lbl.setStyleSheet(
            f"color:{FG0}; font-size:14px; font-weight:bold; font-family:monospace;"
        )
        tb_layout.addWidget(title_lbl)

        desc = QLabel("↓ Gap Down → BUY (cheap entry, target = prior close above)  |  ↑ Gap Up → WATCH")
        desc.setStyleSheet(f"color:{FG2}; font-size:11px;")
        tb_layout.addWidget(desc)
        tb_layout.addStretch()

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFixedWidth(80)
        refresh_btn.setFixedHeight(26)
        refresh_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; font-size:12px; }}"
            f"QPushButton:hover {{ color:{ACCENT}; border-color:{ACCENT}; }}"
        )
        refresh_btn.clicked.connect(self._refresh_table)
        tb_layout.addWidget(refresh_btn)

        layout.addWidget(title_bar)

        # ── Summary bar ───────────────────────────────────────────────────────
        self._summary = GapSummaryBar()
        layout.addWidget(self._summary)

        # ── Filter bar ────────────────────────────────────────────────────────
        filter_bar = QFrame()
        filter_bar.setFixedHeight(36)
        filter_bar.setStyleSheet(
            f"QFrame {{ background:{BG1}; border-bottom:1px solid {BORDER}; }}"
        )
        fb_layout = QHBoxLayout(filter_bar)
        fb_layout.setContentsMargins(12, 0, 12, 0)
        fb_layout.setSpacing(10)

        def _lbl(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(f"color:{FG2}; font-size:11px;")
            return l

        def _combo(items: list[str], width: int = 90) -> QComboBox:
            cb = QComboBox()
            cb.addItems(items)
            cb.setFixedWidth(width)
            cb.setStyleSheet(
                f"QComboBox {{ background:{BG3}; color:{FG1}; "
                f"border:1px solid {BORDER}; border-radius:4px; padding:2px 6px; }}"
            )
            return cb

        fb_layout.addWidget(_lbl("Type:"))
        self._type_combo = _combo(["ALL", "UP (BUY)", "DOWN (WATCH)"])
        self._type_combo.currentTextChanged.connect(self._on_filter_changed)
        fb_layout.addWidget(self._type_combo)

        fb_layout.addWidget(_lbl("State:"))
        self._state_combo = _combo(["OPEN", "ALL", "PARTIAL", "FILLED", "STALE"])
        self._state_combo.currentTextChanged.connect(self._on_filter_changed)
        fb_layout.addWidget(self._state_combo)

        fb_layout.addWidget(_lbl("Timeframe:"))
        self._tf_combo = _combo(["ALL", "1d", "4h"])
        self._tf_combo.currentTextChanged.connect(self._on_filter_changed)
        fb_layout.addWidget(self._tf_combo)

        fb_layout.addStretch()
        self._status_lbl = QLabel("Scanning…")
        self._status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        fb_layout.addWidget(self._status_lbl)

        layout.addWidget(filter_bar)

        # ── Legend ────────────────────────────────────────────────────────────
        legend_bar = QFrame()
        legend_bar.setFixedHeight(26)
        legend_bar.setStyleSheet(f"QFrame {{ background:{BG1}; }}")
        leg_layout = QHBoxLayout(legend_bar)
        leg_layout.setContentsMargins(14, 0, 14, 0)
        leg_layout.setSpacing(20)

        for text, color in [
            ("↓ GAP DOWN — BUY (entry below target)",   GREEN),
            ("↑ GAP UP — WATCH (no spot trade)",        YELLOW),
            ("⬤ OPEN",   "#00D4FF"),
            ("◑ PARTIAL", "#FFB347"),
            ("✓ FILLED",  "#888888"),
        ]:
            lbl = QLabel(f"<span style='color:{color};'>{text}</span>")
            lbl.setStyleSheet("font-size:10px;")
            leg_layout.addWidget(lbl)
        leg_layout.addStretch()
        layout.addWidget(legend_bar)

        # ── Table ─────────────────────────────────────────────────────────────
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)

        # Column sizing
        self._table.horizontalHeader().setSectionResizeMode(0,  QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 50)   # type emoji
        self._table.horizontalHeader().setSectionResizeMode(14, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 14):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )

        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(True)
        self._table.setSortingEnabled(True)
        self._table.setMinimumHeight(300)
        self._table.doubleClicked.connect(self._on_row_double_click)

        self._table.setStyleSheet(f"""
            QTableWidget {{
                background:{BG1};
                color:{FG0};
                gridline-color:{BORDER};
                border:1px solid {BORDER2};
                border-radius:6px;
                font-size:12px;
            }}
            QHeaderView::section {{
                background:{BG3};
                color:{FG1};
                border:none;
                border-bottom:1px solid {BORDER2};
                padding:5px 8px;
                font-size:11px;
                font-weight:bold;
            }}
            QTableWidget::item {{ padding:4px 6px; }}
            QTableWidget::item:selected {{ background:{BG4}; color:{FG0}; }}
        """)

        layout.addWidget(self._table, 1)

    # ── Detector wiring ───────────────────────────────────────────────────────

    def _connect_detector(self) -> None:
        if not self._detector:
            return
        try:
            self._detector.on_gap_up(self._on_gap_up_signal)
            self._detector.on_gap_down(self._on_gap_down_signal)
        except Exception as exc:
            logger.warning(f"GapDetectorWidget: could not connect detector: {exc!r}")

    def _on_gap_up_signal(self, results: list) -> None:
        """Called from background thread — defer to Qt main thread."""
        self._refresh_signal.emit()

    def _on_gap_down_signal(self, results: list) -> None:
        """Called from background thread — defer to Qt main thread."""
        self._refresh_signal.emit()

    # ── Table refresh ─────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        if self._detector:
            try:
                self._results = self._detector.get_all()
            except Exception:
                pass

        results = self._results

        # ── Apply filters ─────────────────────────────────────────────────────
        type_filter  = self._filter_type
        state_filter = self._filter_state
        tf_filter    = self._filter_tf

        if type_filter == "UP (BUY)":
            results = [r for r in results if r.gap_type == "UP"]
        elif type_filter == "DOWN (WATCH)":
            results = [r for r in results if r.gap_type == "DOWN"]

        if state_filter != "ALL":
            results = [r for r in results if r.state == state_filter]

        if tf_filter != "ALL":
            results = [r for r in results if r.timeframe == tf_filter]

        # ── Sort by gap_score descending ──────────────────────────────────────
        results = sorted(results, key=lambda r: -r.gap_score)

        # ── Summary counts ────────────────────────────────────────────────────
        all_open = self._results if self._results else []
        downs_open = sum(1 for r in all_open if r.gap_type == "DOWN" and r.state == "OPEN")  # BUY
        ups_open   = sum(1 for r in all_open if r.gap_type == "UP"   and r.state == "OPEN")  # WATCH
        from datetime import datetime, timezone
        ts_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self._summary.update(downs_open, ups_open, ts_str)

        # ── Populate table ────────────────────────────────────────────────────
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(results))

        for row_idx, r in enumerate(results):
            gap_color   = _GAP_TYPE_COLOR.get(r.gap_type, FG2)
            row_bg      = QColor(_GAP_TYPE_BG.get(r.gap_type, "#0A0A12"))
            state_color = _STATE_COLOR.get(r.state, FG2)

            def _item(
                text: str,
                align=Qt.AlignmentFlag.AlignCenter,
                fg=None,
                bold=False,
            ) -> QTableWidgetItem:
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                it.setBackground(row_bg)
                it.setForeground(QColor(fg or FG0))
                if bold:
                    it.setFont(QFont("monospace", 11, QFont.Weight.Bold))
                return it

            # Col 0 — type arrow
            type_item = QTableWidgetItem(
                f"{r.type_emoji} {'UP' if r.gap_type == 'UP' else 'DN'}"
            )
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            type_item.setBackground(row_bg)
            type_item.setForeground(QColor(gap_color))
            type_item.setFont(QFont("monospace", 11, QFont.Weight.Bold))
            self._table.setItem(row_idx, 0, type_item)

            # Col 1 — symbol
            sym_item = _item(r.symbol, Qt.AlignmentFlag.AlignLeft, FG0, bold=True)
            self._table.setItem(row_idx, 1, sym_item)

            # Col 2 — timeframe
            self._table.setItem(row_idx, 2, _item(r.timeframe, fg=FG2))

            # Col 3 — state
            state_item = QTableWidgetItem(f"{r.state_emoji} {r.state}")
            state_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            state_item.setBackground(row_bg)
            state_item.setForeground(QColor(state_color))
            self._table.setItem(row_idx, 3, state_item)

            # Col 4 — action
            action_color = GREEN if r.action == "BUY" else YELLOW
            action_item  = _item(r.action, fg=action_color, bold=True)
            self._table.setItem(row_idx, 4, action_item)

            # Col 5 — gap %
            sign = "+" if r.gap_pct >= 0 else ""
            gap_fg = GREEN if r.gap_pct > 0 else RED
            self._table.setItem(row_idx, 5, _item(f"{sign}{r.gap_pct:.2f}%", fg=gap_fg))

            # Col 6 — fill progress %
            fill_prog_fg = GREEN if r.fill_progress_pct >= 50 else FG1
            self._table.setItem(row_idx, 6, _item(f"{r.fill_progress_pct:.0f}%", fg=fill_prog_fg))

            # Col 7 — fill probability
            fp_fg = GREEN if r.fill_probability >= 0.65 else (YELLOW if r.fill_probability >= 0.45 else RED)
            self._table.setItem(row_idx, 7, _item(f"{r.fill_probability:.2f}", fg=fp_fg))

            # Col 8 — fill target price
            self._table.setItem(row_idx, 8, _item(self._fmt_price(r.fill_target), fg=FG1))

            # Col 9 — distance to fill %
            dist_fg = GREEN if abs(r.distance_to_fill_pct) < 2.0 else FG2
            dist_sign = "+" if r.distance_to_fill_pct >= 0 else ""
            self._table.setItem(
                row_idx, 9,
                _item(f"{dist_sign}{r.distance_to_fill_pct:.2f}%", fg=dist_fg)
            )

            # Col 10 — gap score
            score_fg = GREEN if r.gap_score >= 0.65 else (YELLOW if r.gap_score >= 0.40 else FG2)
            self._table.setItem(row_idx, 10, _item(f"{r.gap_score:.3f}", fg=score_fg))

            # Col 11 — age (bars)
            age_fg = FG1 if r.age_bars <= 5 else FG2
            self._table.setItem(row_idx, 11, _item(str(r.age_bars), fg=age_fg))

            # Col 12 — volume ratio
            vol_fg = RED if r.volume_ratio >= 3.0 else (YELLOW if r.volume_ratio >= 1.5 else FG2)
            self._table.setItem(row_idx, 12, _item(f"{r.volume_ratio:.1f}×", fg=vol_fg))

            # Col 13 — RSI
            rsi_fg = RED if r.rsi >= 70 else (GREEN if r.rsi <= 30 else FG2)
            self._table.setItem(row_idx, 13, _item(f"{r.rsi:.0f}", fg=rsi_fg))

            # Col 14 — note
            self._table.setItem(
                row_idx, 14,
                _item(r.note, Qt.AlignmentFlag.AlignLeft, FG2)
            )

            self._table.setRowHeight(row_idx, 34)

        self._table.setSortingEnabled(True)
        self._status_lbl.setText(f"Updated {ts_str}  ·  {len(results)} gaps shown")

    # ── Interactions ──────────────────────────────────────────────────────────

    def _on_filter_changed(self, _: str) -> None:
        self._filter_type  = self._type_combo.currentText()
        self._filter_state = self._state_combo.currentText()
        self._filter_tf    = self._tf_combo.currentText()
        self._refresh_table()

    def _on_row_double_click(self, index) -> None:
        row = index.row()
        sym_item = self._table.item(row, 1)
        if sym_item:
            self.symbol_selected.emit(sym_item.text())

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_price(price: float) -> str:
        if price >= 10_000:
            return f"{price:,.2f}"
        if price >= 1:
            return f"{price:.4f}"
        if price >= 0.001:
            return f"{price:.6f}"
        return f"{price:.8f}"
