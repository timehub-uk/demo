"""
Accumulation Widget — Displays stealth accumulation signals.

Shows tokens classified as WATCH / ALERT / STRONG based on the
AccumulationDetector analysis of range compression, rising volume,
taker-buy dominance, and duration.

Columns: Label | Symbol | Score | Range | Vol Trend | Buy Ratio | Duration | Stability | Price | Change% | Note
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox,
)
from loguru import logger

from ui.styles import (
    ACCENT, BG1, BG2, BG3, BG4, BORDER, BORDER2,
    FG0, FG1, FG2, GREEN, RED, YELLOW,
)

try:
    from ml.accumulation_detector import AccumulationDetector, AccumulationResult
except Exception:
    AccumulationDetector = None   # type: ignore[assignment, misc]
    AccumulationResult   = None   # type: ignore[assignment, misc]

_LABEL_COLORS = {
    "NONE":   "#555555",
    "WATCH":  "#8888FF",
    "ALERT":  "#FFB347",
    "STRONG": "#FF4040",
}

_LABEL_BG = {
    "NONE":   "#1A1A2E",
    "WATCH":  "#1A1A3A",
    "ALERT":  "#2A1A0A",
    "STRONG": "#2A0A0A",
}

_COLS = ["", "Symbol", "Score", "Range", "Vol↑", "BuyRatio", "Duration", "Stability", "Price", "Chg%", "Note"]


class AccumulationWidget(QWidget):
    """
    Stealth accumulation signal dashboard.

    Instantiate with an ``AccumulationDetector`` instance (or None for demo).
    """

    def __init__(
        self,
        accumulation_detector: Optional[AccumulationDetector] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._detector = accumulation_detector
        self._results: list[AccumulationResult] = []
        self._filter_label = "ALL"

        self._build_ui()
        self._connect_detector()

        self._timer = QTimer(self)
        self._timer.setInterval(60_000)   # refresh every minute
        self._timer.timeout.connect(self._refresh_table)
        self._timer.start()

    # ── UI construction ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Top bar
        top = QHBoxLayout()
        top.setSpacing(8)

        title = QLabel("Stealth Accumulation Detector")
        title.setStyleSheet(f"color:{FG0}; font-size:14px; font-weight:bold;")
        top.addWidget(title)
        top.addStretch()

        # Filter pills
        filter_lbl = QLabel("Show:")
        filter_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        top.addWidget(filter_lbl)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["ALL", "STRONG", "ALERT", "WATCH"])
        self._filter_combo.setFixedWidth(90)
        self._filter_combo.setStyleSheet(
            f"QComboBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 6px; }}"
        )
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        top.addWidget(self._filter_combo)

        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedWidth(32)
        refresh_btn.setToolTip("Force refresh")
        refresh_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; font-size:14px; }}"
            f"QPushButton:hover {{ color:{ACCENT}; border-color:{ACCENT}; }}"
        )
        refresh_btn.clicked.connect(self._refresh_table)
        top.addWidget(refresh_btn)

        layout.addLayout(top)

        # Legend
        legend = QHBoxLayout()
        legend.setSpacing(16)
        for label, color in [
            ("⬛ NONE", "#555555"),
            ("👁 WATCH", "#8888FF"),
            ("🔶 ALERT", "#FFB347"),
            ("🚨 STRONG", "#FF4040"),
        ]:
            lbl = QLabel(f"<span style='color:{color};'>{label}</span>")
            lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
            legend.addWidget(lbl)
        legend.addStretch()
        self._status_lbl = QLabel("Scanning…")
        self._status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        legend.addWidget(self._status_lbl)
        layout.addLayout(legend)

        # Table
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 60)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)
        for i in range(2, 10):
            self._table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(True)
        self._table.setSortingEnabled(False)
        self._table.setMinimumHeight(300)

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
                font-size:12px;
                font-weight:bold;
            }}
            QTableWidget::item {{ padding:4px 6px; }}
            QTableWidget::item:selected {{ background:{BG4}; color:{FG0}; }}
        """)
        layout.addWidget(self._table)

    # ── Detector wiring ─────────────────────────────────────────────────────────

    def _connect_detector(self) -> None:
        if not self._detector:
            return
        try:
            self._detector.on_alert(self._on_detector_update)
        except Exception as exc:
            logger.warning(f"AccumulationWidget: could not connect detector: {exc!r}")

    def _on_detector_update(self, results: list) -> None:
        """Called from background thread — defer to Qt main thread."""
        self._results = results
        QTimer.singleShot(0, self._refresh_table)

    # ── Table refresh ───────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        # Pull from detector if no callback results yet
        if not self._results and self._detector:
            try:
                self._results = self._detector.get_all()
            except Exception:
                pass

        results = self._results

        # Filter
        if self._filter_label != "ALL":
            results = [r for r in results if r.label == self._filter_label]

        self._table.setRowCount(len(results))

        for row_idx, r in enumerate(results):
            row_bg = QColor(_LABEL_BG.get(r.label, "#1A1A2E"))
            label_color = _LABEL_COLORS.get(r.label, FG2)

            def _item(text: str, align=Qt.AlignmentFlag.AlignCenter, fg=None) -> QTableWidgetItem:
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                it.setBackground(row_bg)
                it.setForeground(QColor(fg or FG0))
                return it

            # Col 0 — label emoji + text
            emoji_item = QTableWidgetItem(f"{r.label_emoji} {r.label}")
            emoji_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            emoji_item.setBackground(row_bg)
            emoji_item.setForeground(QColor(label_color))
            emoji_item.setFont(QFont("monospace", 10, QFont.Weight.Bold))
            self._table.setItem(row_idx, 0, emoji_item)

            # Col 1 — symbol
            sym_item = _item(r.symbol, Qt.AlignmentFlag.AlignLeft, FG0)
            sym_item.setFont(QFont("monospace", 11, QFont.Weight.Bold))
            self._table.setItem(row_idx, 1, sym_item)

            # Col 2 — score
            score_color = label_color
            self._table.setItem(row_idx, 2, _item(f"{r.accumulation_score:.3f}", fg=score_color))

            # Col 3 — range score
            self._table.setItem(row_idx, 3, _item(f"{r.range_score:.2f}"))

            # Col 4 — volume trend
            vol_color = GREEN if r.volume_trend > 0.5 else FG2
            self._table.setItem(row_idx, 4, _item(f"{r.volume_trend:.2f}", fg=vol_color))

            # Col 5 — buy ratio
            br_color = GREEN if r.buy_ratio > 0.55 else (RED if r.buy_ratio < 0.45 else FG1)
            self._table.setItem(row_idx, 5, _item(f"{r.buy_ratio:.2f}", fg=br_color))

            # Col 6 — duration score
            self._table.setItem(row_idx, 6, _item(f"{r.duration_score:.2f}"))

            # Col 7 — price stability
            self._table.setItem(row_idx, 7, _item(f"{r.price_stability:.2f}"))

            # Col 8 — price
            self._table.setItem(row_idx, 8, _item(self._fmt_price(r.last_price), fg=FG1))

            # Col 9 — price change %
            chg_color = GREEN if r.price_change_pct >= 0 else RED
            sign = "+" if r.price_change_pct >= 0 else ""
            self._table.setItem(row_idx, 9, _item(f"{sign}{r.price_change_pct:.2f}%", fg=chg_color))

            # Col 10 — note
            note_item = _item(r.note, Qt.AlignmentFlag.AlignLeft, FG2)
            self._table.setItem(row_idx, 10, note_item)

            self._table.setRowHeight(row_idx, 36)

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self._status_lbl.setText(f"Updated {ts}  ·  {len(results)} signals")

    @staticmethod
    def _fmt_price(price: float) -> str:
        if price >= 1000:
            return f"{price:,.2f}"
        if price >= 1:
            return f"{price:.4f}"
        if price >= 0.001:
            return f"{price:.6f}"
        return f"{price:.8f}"

    # ── Interactions ────────────────────────────────────────────────────────────

    def _on_filter_changed(self, text: str) -> None:
        self._filter_label = text
        self._refresh_table()
