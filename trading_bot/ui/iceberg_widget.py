"""
Iceberg Widget — Displays hidden iceberg order signals from IcebergDetector.

An iceberg order splits a large position into small visible slices.
Binance raised ICEBERG_PARTS from 50 → 100 slices, making it easier
for whales to hide their true order size.

Signal types:
  BID Iceberg → FLOOR   — green rows  — Whale defending a price, safe entry above it
  ASK Iceberg → CEILING — red rows    — Whale blocking a price, do NOT chase breakout

Columns:
  Level | Symbol | Side | Action | Price | Slice Qty | Refills | Hidden Est. | Hidden USD | Score | Age | Depth | Note
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QFrame,
)
from loguru import logger

from ui.styles import (
    ACCENT, BG1, BG2, BG3, BG4, BORDER, BORDER2,
    FG0, FG1, FG2, GREEN, RED, YELLOW,
)

try:
    from ml.iceberg_detector import IcebergDetector, IcebergSignal
except Exception:
    IcebergDetector = None   # type: ignore[assignment, misc]
    IcebergSignal   = None   # type: ignore[assignment, misc]


# ── Color maps ────────────────────────────────────────────────────────────────
_SIDE_COLOR = {
    "BID": "#00CC66",   # green  — buy wall / FLOOR
    "ASK": "#FF4444",   # red    — sell wall / CEILING
}
_SIDE_BG = {
    "BID": "#071A0E",
    "ASK": "#1A0707",
}
_ALERT_COLOR = {
    "WATCH":  "#8888FF",   # blue-purple
    "ALERT":  "#FFB347",   # amber
    "STRONG": "#FF4040",   # red
}

_COLS = [
    "",           # 0  alert emoji + level
    "Symbol",     # 1
    "Side",       # 2
    "Action",     # 3  FLOOR / CEILING
    "Price",      # 4
    "Slice Qty",  # 5
    "Refills",    # 6
    "Hidden Est", # 7  slice × refills
    "Hidden USD", # 8
    "Score",      # 9
    "Age",        # 10
    "Depth",      # 11 rank from best bid/ask
    "Note",       # 12
]


class IcebergSummaryBar(QFrame):
    """Compact stats strip: FLOOR count | CEILING count | STRONG count."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(38)
        self.setStyleSheet(f"QFrame {{ background:{BG2}; border-bottom:1px solid {BORDER}; }}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(20)

        self._lbl_floors   = self._make_stat("BID FLOORS",   "0", GREEN)
        self._lbl_ceilings = self._make_stat("ASK CEILINGS", "0", RED)
        self._lbl_strong   = self._make_stat("STRONG",       "0", "#FF4040")
        self._lbl_total    = self._make_stat("Total",        "0", FG1)

        for w in (self._lbl_floors, self._lbl_ceilings, self._lbl_strong, self._lbl_total):
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

    def update_stats(self, floors: int, ceilings: int, strong: int, ts: str) -> None:
        total = floors + ceilings
        self._lbl_floors.setText(
            f"<span style='color:{FG2}; font-size:10px;'>BID FLOORS: </span>"
            f"<span style='color:{GREEN}; font-size:14px; font-weight:bold;'>{floors}</span>"
        )
        self._lbl_ceilings.setText(
            f"<span style='color:{FG2}; font-size:10px;'>ASK CEILINGS: </span>"
            f"<span style='color:{RED}; font-size:14px; font-weight:bold;'>{ceilings}</span>"
        )
        self._lbl_strong.setText(
            f"<span style='color:{FG2}; font-size:10px;'>STRONG: </span>"
            f"<span style='color:#FF4040; font-size:14px; font-weight:bold;'>{strong}</span>"
        )
        self._lbl_total.setText(
            f"<span style='color:{FG2}; font-size:10px;'>Total: </span>"
            f"<span style='color:{FG1}; font-size:14px; font-weight:bold;'>{total}</span>"
        )
        self._scan_lbl.setText(f"Updated {ts}")


class IcebergWidget(QWidget):
    """
    Iceberg order discovery dashboard.

    Displays all detected iceberg orders across scanned pairs.
      BID iceberg → green rows → FLOOR  (safe entry, whale is defending this price)
      ASK iceberg → red rows  → CEILING (do NOT chase breakout above this level)

    Instantiate with an ``IcebergDetector`` instance (or None for demo mode).
    """

    symbol_selected  = pyqtSignal(str)
    _refresh_signal  = pyqtSignal()

    def __init__(
        self,
        iceberg_detector: Optional["IcebergDetector"] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._detector = iceberg_detector
        self._results:    list = []
        self._filter_side  = "ALL"
        self._filter_level = "ALL"

        self._refresh_signal.connect(self._refresh_table)
        self._build_ui()
        self._connect_detector()

        # Auto-refresh every 10 s to pick up new detections
        self._timer = QTimer(self)
        self._timer.setInterval(10_000)
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
        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(12, 0, 12, 0)
        tb.setSpacing(12)

        title_lbl = QLabel("Iceberg Detector  ·  Hidden Order Discovery (Binance ICEBERG_PARTS=100)")
        title_lbl.setStyleSheet(
            f"color:{FG0}; font-size:14px; font-weight:bold; font-family:monospace;"
        )
        tb.addWidget(title_lbl)

        desc = QLabel(
            "🟢 BID → FLOOR (whale defending price, safe entry)  |  "
            "🔴 ASK → CEILING (whale blocking, wait for wall to clear)"
        )
        desc.setStyleSheet(f"color:{FG2}; font-size:11px;")
        tb.addWidget(desc)
        tb.addStretch()

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFixedWidth(80)
        refresh_btn.setFixedHeight(26)
        refresh_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; font-size:12px; }}"
            f"QPushButton:hover {{ color:{ACCENT}; border-color:{ACCENT}; }}"
        )
        refresh_btn.clicked.connect(self._refresh_table)
        tb.addWidget(refresh_btn)

        layout.addWidget(title_bar)

        # ── Summary bar ───────────────────────────────────────────────────────
        self._summary = IcebergSummaryBar()
        layout.addWidget(self._summary)

        # ── Filter bar ────────────────────────────────────────────────────────
        filter_bar = QFrame()
        filter_bar.setFixedHeight(36)
        filter_bar.setStyleSheet(
            f"QFrame {{ background:{BG1}; border-bottom:1px solid {BORDER}; }}"
        )
        fb = QHBoxLayout(filter_bar)
        fb.setContentsMargins(12, 0, 12, 0)
        fb.setSpacing(10)

        def _lbl(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(f"color:{FG2}; font-size:11px;")
            return l

        def _combo(items: list, width: int = 110) -> QComboBox:
            cb = QComboBox()
            cb.addItems(items)
            cb.setFixedWidth(width)
            cb.setStyleSheet(
                f"QComboBox {{ background:{BG3}; color:{FG1}; "
                f"border:1px solid {BORDER}; border-radius:4px; padding:2px 6px; }}"
            )
            return cb

        fb.addWidget(_lbl("Side:"))
        self._side_combo = _combo(["ALL", "BID (Floor)", "ASK (Ceiling)"])
        self._side_combo.currentTextChanged.connect(self._on_filter_changed)
        fb.addWidget(self._side_combo)

        fb.addWidget(_lbl("Level:"))
        self._level_combo = _combo(["ALL", "STRONG", "ALERT", "WATCH"])
        self._level_combo.currentTextChanged.connect(self._on_filter_changed)
        fb.addWidget(self._level_combo)

        fb.addStretch()
        self._status_lbl = QLabel("Scanning…")
        self._status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        fb.addWidget(self._status_lbl)

        layout.addWidget(filter_bar)

        # ── Legend ────────────────────────────────────────────────────────────
        legend_bar = QFrame()
        legend_bar.setFixedHeight(26)
        legend_bar.setStyleSheet(f"QFrame {{ background:{BG1}; }}")
        leg = QHBoxLayout(legend_bar)
        leg.setContentsMargins(14, 0, 14, 0)
        leg.setSpacing(20)

        for text, color in [
            ("🟢 BID FLOOR — Safe entry, whale defending price", GREEN),
            ("🔴 ASK CEILING — Do NOT chase, whale blocking",    RED),
            ("👁 WATCH (3–9 refills)",   "#8888FF"),
            ("🔶 ALERT (10–29 refills)", "#FFB347"),
            ("🚨 STRONG (30+ refills)",  "#FF4040"),
        ]:
            lbl = QLabel(f"<span style='color:{color};'>{text}</span>")
            lbl.setStyleSheet("font-size:10px;")
            leg.addWidget(lbl)
        leg.addStretch()
        layout.addWidget(legend_bar)

        # ── Table ─────────────────────────────────────────────────────────────
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0,  QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 80)   # level pill
        hh.setSectionResizeMode(12, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 12):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

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
            self._detector.on_alert(self._on_detector_update)
        except Exception as exc:
            logger.warning(f"IcebergWidget: could not connect detector: {exc!r}")

    def _on_detector_update(self, signals: list) -> None:
        """Called from background thread — defer update to Qt main thread."""
        self._results = signals
        self._refresh_signal.emit()

    # ── Table refresh ─────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        if not self._results and self._detector:
            try:
                self._results = self._detector.get_all()
            except Exception:
                pass

        results = list(self._results)

        # ── Apply filters ─────────────────────────────────────────────────────
        side_filter  = self._filter_side
        level_filter = self._filter_level

        if side_filter == "BID (Floor)":
            results = [r for r in results if r.side == "BID"]
        elif side_filter == "ASK (Ceiling)":
            results = [r for r in results if r.side == "ASK"]

        if level_filter != "ALL":
            results = [r for r in results if r.alert_level == level_filter]

        # Sort by score descending
        results = sorted(results, key=lambda r: -r.iceberg_score)

        # ── Summary counts (from full unfiltered set) ──────────────────────────
        all_results = self._results
        floors   = sum(1 for r in all_results if r.side == "BID")
        ceilings = sum(1 for r in all_results if r.side == "ASK")
        strong   = sum(1 for r in all_results if r.alert_level == "STRONG")
        ts_str   = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self._summary.update_stats(floors, ceilings, strong, ts_str)

        # ── Populate table ────────────────────────────────────────────────────
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(results))

        for row_idx, r in enumerate(results):
            side_color   = _SIDE_COLOR.get(r.side, FG1)
            row_bg       = QColor(_SIDE_BG.get(r.side, "#0A0A12"))
            alert_color  = _ALERT_COLOR.get(r.alert_level, FG2)

            def _item(
                text: str,
                align=Qt.AlignmentFlag.AlignCenter,
                fg: str = None,
                bold: bool = False,
            ) -> QTableWidgetItem:
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                it.setBackground(row_bg)
                it.setForeground(QColor(fg or FG0))
                if bold:
                    it.setFont(QFont("monospace", 11, QFont.Weight.Bold))
                return it

            # Col 0 — alert emoji + level
            level_item = QTableWidgetItem(f"{r.alert_emoji} {r.alert_level}")
            level_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            level_item.setBackground(row_bg)
            level_item.setForeground(QColor(alert_color))
            level_item.setFont(QFont("monospace", 10, QFont.Weight.Bold))
            self._table.setItem(row_idx, 0, level_item)

            # Col 1 — symbol
            sym_item = _item(r.symbol, Qt.AlignmentFlag.AlignLeft, FG0, bold=True)
            self._table.setItem(row_idx, 1, sym_item)

            # Col 2 — side
            side_item = QTableWidgetItem(f"{r.side_emoji} {r.side}")
            side_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            side_item.setBackground(row_bg)
            side_item.setForeground(QColor(side_color))
            side_item.setFont(QFont("monospace", 10, QFont.Weight.Bold))
            self._table.setItem(row_idx, 2, side_item)

            # Col 3 — action (FLOOR / CEILING)
            action_color = GREEN if r.action == "FLOOR" else RED
            self._table.setItem(row_idx, 3, _item(r.action, fg=action_color, bold=True))

            # Col 4 — price
            self._table.setItem(row_idx, 4, _item(self._fmt_price(r.price), fg=FG1))

            # Col 5 — slice qty
            self._table.setItem(row_idx, 5, _item(f"{r.slice_qty:.4g}", fg=FG1))

            # Col 6 — refill count
            refill_fg = (
                "#FF4040" if r.refill_count >= 30
                else ("#FFB347" if r.refill_count >= 10
                      else "#8888FF")
            )
            self._table.setItem(
                row_idx, 6,
                _item(str(r.refill_count), fg=refill_fg, bold=r.refill_count >= 10)
            )

            # Col 7 — hidden estimate (qty)
            self._table.setItem(row_idx, 7, _item(f"{r.hidden_total:.4g}", fg=side_color))

            # Col 8 — hidden USD
            usd_fg = (
                "#FF4040" if r.hidden_usd >= 500_000
                else ("#FFB347" if r.hidden_usd >= 100_000
                      else FG1)
            )
            self._table.setItem(
                row_idx, 8,
                _item(f"${r.hidden_usd:,.0f}", fg=usd_fg)
            )

            # Col 9 — iceberg score
            score_fg = (
                GREEN if r.iceberg_score >= 0.65
                else (YELLOW if r.iceberg_score >= 0.40 else FG2)
            )
            self._table.setItem(row_idx, 9, _item(f"{r.iceberg_score:.3f}", fg=score_fg))

            # Col 10 — age
            age_str = self._fmt_age(r.age_seconds)
            age_fg  = FG1 if r.age_seconds < 300 else FG2
            self._table.setItem(row_idx, 10, _item(age_str, fg=age_fg))

            # Col 11 — depth rank
            depth_fg = GREEN if r.depth_rank <= 5 else FG2
            self._table.setItem(row_idx, 11, _item(f"#{r.depth_rank}", fg=depth_fg))

            # Col 12 — note
            self._table.setItem(
                row_idx, 12,
                _item(r.note, Qt.AlignmentFlag.AlignLeft, FG2)
            )

            self._table.setRowHeight(row_idx, 34)

        self._table.setSortingEnabled(True)
        self._status_lbl.setText(f"Updated {ts_str}  ·  {len(results)} icebergs shown")

    # ── Interactions ──────────────────────────────────────────────────────────

    def _on_filter_changed(self, _: str) -> None:
        self._filter_side  = self._side_combo.currentText()
        self._filter_level = self._level_combo.currentText()
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

    @staticmethod
    def _fmt_age(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds / 60)}m"
        return f"{seconds / 3600:.1f}h"
