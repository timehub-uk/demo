"""
Volume Breakout Widget — Displays 4-stage volume breakout detection.

Visualises tokens progressing through:
  Stage 1 — LAUNCH       (first volume/price spike)
  Stage 2 — SMALL PUMP   (confirmed rapid price gain)
  Stage 3 — CONSOLIDATION (price stalls, volume elevated)
  Stage 4 — LARGE BREAKOUT (price breaks above consolidation)

Columns: Stage | Symbol | Score | Vol×Base | 4h% | RSI | ConsolBars | Price | Note
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QButtonGroup, QRadioButton, QFrame,
)
from loguru import logger

from ui.styles import (
    ACCENT, BG1, BG2, BG3, BG4, BORDER, BORDER2,
    FG0, FG1, FG2, GREEN, RED, YELLOW,
)

try:
    from ml.volume_breakout_detector import VolumeBreakoutDetector, BreakoutResult
except Exception:
    VolumeBreakoutDetector = None   # type: ignore[assignment, misc]
    BreakoutResult         = None   # type: ignore[assignment, misc]

_STAGE_COLORS = {
    0: "#555555",
    1: "#00BFFF",   # launch — cyan
    2: "#00CC66",   # pump — green
    3: "#FFD700",   # consolidation — gold
    4: "#FF4500",   # large breakout — red-orange
}

_STAGE_BG = {
    0: "#111111",
    1: "#0A1A2A",
    2: "#0A2A1A",
    3: "#2A2A0A",
    4: "#2A1000",
}

_STAGE_LABELS = {
    0: "NONE",
    1: "🚀 LAUNCH",
    2: "📈 PUMP",
    3: "⏸ CONSOL",
    4: "💥 BREAKOUT",
}

_COLS = ["Stage", "Symbol", "Score", "Vol×", "4h%", "RSI", "Consol", "Price", "Note"]


class BreakoutWidget(QWidget):
    """
    4-stage volume breakout detection dashboard.

    Instantiate with a ``VolumeBreakoutDetector`` instance (or None for demo).
    """

    _refresh_signal = pyqtSignal()

    def __init__(
        self,
        breakout_detector: Optional[VolumeBreakoutDetector] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._detector = breakout_detector
        self._results: list[BreakoutResult] = []
        self._filter_stage = -1   # -1 = ALL

        self._refresh_signal.connect(self._refresh_table)
        self._build_ui()
        self._connect_detector()

        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
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

        title = QLabel("Volume Breakout Detector")
        title.setStyleSheet(f"color:{FG0}; font-size:14px; font-weight:bold;")
        top.addWidget(title)
        top.addStretch()

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

        # Stage filter pills
        pill_row = QHBoxLayout()
        pill_row.setSpacing(6)
        stage_pill_lbl = QLabel("Filter:")
        stage_pill_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        pill_row.addWidget(stage_pill_lbl)

        self._stage_btns: dict[int, QPushButton] = {}
        btn_style = (
            f"QPushButton {{ background:{BG3}; color:{{color}}; border:1px solid {{color}}; "
            f"border-radius:4px; padding:2px 10px; font-size:11px; }}"
            f"QPushButton:checked {{ background:{{color}}; color:#000; }}"
        )

        pills = [(-1, "ALL", "#AAAAAA"), (1, "🚀 S1", "#00BFFF"), (2, "📈 S2", "#00CC66"),
                 (3, "⏸ S3", "#FFD700"), (4, "💥 S4", "#FF4500")]
        for stage, label, color in pills:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(stage == -1)
            btn.setStyleSheet(btn_style.replace("{color}", color))
            btn.clicked.connect(lambda checked, s=stage: self._on_stage_filter(s))
            self._stage_btns[stage] = btn
            pill_row.addWidget(btn)

        pill_row.addStretch()
        self._status_lbl = QLabel("Scanning…")
        self._status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        pill_row.addWidget(self._status_lbl)
        layout.addLayout(pill_row)

        # Legend
        legend = QHBoxLayout()
        legend.setSpacing(16)
        for stage, label, color in [
            (1, "Stage 1: LAUNCH — first volume spike", "#00BFFF"),
            (2, "Stage 2: PUMP — rapid price gain", "#00CC66"),
            (3, "Stage 3: CONSOLIDATION — price stalls", "#FFD700"),
            (4, "Stage 4: BREAKOUT — major move", "#FF4500"),
        ]:
            lbl = QLabel(f"<span style='color:{color};'>■</span>  {label}")
            lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
            legend.addWidget(lbl)
        legend.addStretch()
        layout.addLayout(legend)

        # Table
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        for i in range(2, 8):
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
            self._detector.on_breakout(self._on_breakout_update)
        except Exception as exc:
            logger.warning(f"BreakoutWidget: could not connect detector: {exc!r}")

    def _on_breakout_update(self, results: list) -> None:
        self._results = list(results)
        self._refresh_signal.emit()

    # ── Table refresh ───────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        if not self._results and self._detector:
            try:
                self._results = self._detector.get_all()
            except Exception:
                pass

        results = self._results
        if self._filter_stage >= 0:
            results = [r for r in results if r.stage == self._filter_stage]
        else:
            # Default: show stage >= 1 only (hide NONE)
            results = [r for r in results if r.stage >= 1]

        self._table.setRowCount(len(results))

        for row_idx, r in enumerate(results):
            stage_color = _STAGE_COLORS.get(r.stage, FG2)
            row_bg      = QColor(_STAGE_BG.get(r.stage, "#111111"))

            def _item(text: str, align=Qt.AlignmentFlag.AlignCenter, fg=None) -> QTableWidgetItem:
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                it.setBackground(row_bg)
                it.setForeground(QColor(fg or FG0))
                return it

            # Col 0 — stage label
            s_label = _STAGE_LABELS.get(r.stage, "?")
            s_item  = QTableWidgetItem(s_label)
            s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            s_item.setBackground(row_bg)
            s_item.setForeground(QColor(stage_color))
            s_item.setFont(QFont("monospace", 10, QFont.Weight.Bold))
            self._table.setItem(row_idx, 0, s_item)

            # Col 1 — symbol
            sym_item = _item(r.symbol, Qt.AlignmentFlag.AlignLeft, FG0)
            sym_item.setFont(QFont("monospace", 11, QFont.Weight.Bold))
            self._table.setItem(row_idx, 1, sym_item)

            # Col 2 — score
            self._table.setItem(row_idx, 2, _item(f"{r.breakout_score:.3f}", fg=stage_color))

            # Col 3 — volume spike
            vol_color = GREEN if r.volume_spike >= 3.0 else (YELLOW if r.volume_spike >= 1.5 else FG2)
            self._table.setItem(row_idx, 3, _item(f"{r.volume_spike:.1f}×", fg=vol_color))

            # Col 4 — 4h price change %
            chg_color = GREEN if r.price_change_4h >= 0 else RED
            sign = "+" if r.price_change_4h >= 0 else ""
            self._table.setItem(row_idx, 4, _item(f"{sign}{r.price_change_4h:.2f}%", fg=chg_color))

            # Col 5 — RSI
            rsi_color = RED if r.rsi > 70 else (GREEN if r.rsi < 35 else FG1)
            self._table.setItem(row_idx, 5, _item(f"{r.rsi:.1f}", fg=rsi_color))

            # Col 6 — consolidation bars
            consol_text = f"{r.consol_bars}b" if r.in_consolidation else "—"
            consol_color = YELLOW if r.in_consolidation else FG2
            self._table.setItem(row_idx, 6, _item(consol_text, fg=consol_color))

            # Col 7 — price
            self._table.setItem(row_idx, 7, _item(self._fmt_price(r.last_price), fg=FG1))

            # Col 8 — note
            self._table.setItem(row_idx, 8, _item(r.note, Qt.AlignmentFlag.AlignLeft, FG2))

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

    def _on_stage_filter(self, stage: int) -> None:
        self._filter_stage = stage
        # Uncheck others
        for s, btn in self._stage_btns.items():
            btn.setChecked(s == stage)
        self._refresh_table()
