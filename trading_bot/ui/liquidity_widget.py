"""
Liquidity Depth Widget — Displays order-book depth and liquidity grades.

Shows the liquidity quality of each pair as assessed by the
LiquidityDepthAnalyzer: spread, depth, slippage estimate, wall detection.

Columns: Grade | Symbol | Score | Spread% | BidDepth | AskDepth | Imbalance | Walls | Slippage% | Levels | Note
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
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
    from ml.liquidity_depth_analyzer import LiquidityDepthAnalyzer, LiquidityResult
except Exception:
    LiquidityDepthAnalyzer = None   # type: ignore[assignment, misc]
    LiquidityResult        = None   # type: ignore[assignment, misc]

_GRADE_COLORS = {
    "DEEP":     "#00CC88",
    "ADEQUATE": "#FFD700",
    "THIN":     "#FF8C00",
    "ILLIQUID": "#FF3333",
}

_GRADE_BG = {
    "DEEP":     "#0A2A1A",
    "ADEQUATE": "#2A2A0A",
    "THIN":     "#2A1500",
    "ILLIQUID": "#2A0A0A",
}

_COLS = ["Grade", "Symbol", "Score", "Spread%", "Bid Depth", "Ask Depth", "Imbalance", "Walls%", "Slippage%", "Levels", "Note"]


class LiquidityWidget(QWidget):
    """
    Order-book liquidity depth dashboard.

    Instantiate with a ``LiquidityDepthAnalyzer`` instance (or None for demo).
    """

    _refresh_signal = pyqtSignal()

    def __init__(
        self,
        liquidity_analyzer: Optional[LiquidityDepthAnalyzer] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._analyzer = liquidity_analyzer
        self._results: list[LiquidityResult] = []
        self._filter_grade = "ALL"

        self._refresh_signal.connect(self._refresh_table)
        self._build_ui()
        self._connect_analyzer()

        self._timer = QTimer(self)
        self._timer.setInterval(120_000)   # refresh every 2 min
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

        title = QLabel("Liquidity Depth Analyzer")
        title.setStyleSheet(f"color:{FG0}; font-size:14px; font-weight:bold;")
        top.addWidget(title)
        top.addStretch()

        filter_lbl = QLabel("Grade:")
        filter_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        top.addWidget(filter_lbl)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["ALL", "DEEP", "ADEQUATE", "THIN", "ILLIQUID"])
        self._filter_combo.setFixedWidth(100)
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
        for grade, color in [
            ("💧 DEEP", "#00CC88"),
            ("🟡 ADEQUATE", "#FFD700"),
            ("🔴 THIN", "#FF8C00"),
            ("💀 ILLIQUID", "#FF3333"),
        ]:
            lbl = QLabel(f"<span style='color:{color};'>{grade}</span>")
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
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
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

    # ── Analyzer wiring ─────────────────────────────────────────────────────────

    def _connect_analyzer(self) -> None:
        if not self._analyzer:
            return
        try:
            self._analyzer.on_update(self._on_analyzer_update)
        except Exception as exc:
            logger.warning(f"LiquidityWidget: could not connect analyzer: {exc!r}")

    def _on_analyzer_update(self, results: list) -> None:
        self._results = list(results)
        self._refresh_signal.emit()

    # ── Table refresh ───────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        if not self._results and self._analyzer:
            try:
                self._results = self._analyzer.get_all()
            except Exception:
                pass

        results = self._results
        if self._filter_grade != "ALL":
            results = [r for r in results if r.grade == self._filter_grade]

        self._table.setRowCount(len(results))

        for row_idx, r in enumerate(results):
            row_bg      = QColor(_GRADE_BG.get(r.grade, "#1A1A2E"))
            grade_color = _GRADE_COLORS.get(r.grade, FG2)

            def _item(text: str, align=Qt.AlignmentFlag.AlignCenter, fg=None) -> QTableWidgetItem:
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                it.setBackground(row_bg)
                it.setForeground(QColor(fg or FG0))
                return it

            # Col 0 — grade
            g_item = QTableWidgetItem(f"{r.grade_emoji} {r.grade}")
            g_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            g_item.setBackground(row_bg)
            g_item.setForeground(QColor(grade_color))
            g_item.setFont(QFont("monospace", 10, QFont.Weight.Bold))
            self._table.setItem(row_idx, 0, g_item)

            # Col 1 — symbol
            sym_item = _item(r.symbol, Qt.AlignmentFlag.AlignLeft, FG0)
            sym_item.setFont(QFont("monospace", 11, QFont.Weight.Bold))
            self._table.setItem(row_idx, 1, sym_item)

            # Col 2 — score
            self._table.setItem(row_idx, 2, _item(f"{r.liquidity_score:.3f}", fg=grade_color))

            # Col 3 — spread %
            spread_color = GREEN if r.spread_pct < 0.05 else (YELLOW if r.spread_pct < 0.2 else RED)
            self._table.setItem(row_idx, 3, _item(f"{r.spread_pct:.4f}%", fg=spread_color))

            # Col 4 — bid depth
            self._table.setItem(row_idx, 4, _item(f"${r.bid_depth_usdt:,.0f}"))

            # Col 5 — ask depth
            self._table.setItem(row_idx, 5, _item(f"${r.ask_depth_usdt:,.0f}"))

            # Col 6 — imbalance (0.5=balanced)
            imb_color = GREEN if r.imbalance > 0.55 else (RED if r.imbalance < 0.45 else FG1)
            self._table.setItem(row_idx, 6, _item(f"{r.imbalance:.2f}", fg=imb_color))

            # Col 7 — wall penalty %
            wall_color = RED if r.wall_penalty > 0.3 else (YELLOW if r.wall_penalty > 0.1 else FG1)
            self._table.setItem(row_idx, 7, _item(f"{r.wall_penalty:.1%}", fg=wall_color))

            # Col 8 — slippage %
            slip_color = GREEN if r.slippage_pct < 0.1 else (YELLOW if r.slippage_pct < 0.5 else RED)
            self._table.setItem(row_idx, 8, _item(f"{r.slippage_pct:.4f}%", fg=slip_color))

            # Col 9 — levels
            self._table.setItem(row_idx, 9, _item(f"{r.bid_levels}×{r.ask_levels}", fg=FG2))

            # Col 10 — note
            self._table.setItem(row_idx, 10, _item(r.note, Qt.AlignmentFlag.AlignLeft, FG2))

            self._table.setRowHeight(row_idx, 36)

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self._status_lbl.setText(f"Updated {ts}  ·  {len(results)} pairs")

    # ── Interactions ────────────────────────────────────────────────────────────

    def _on_filter_changed(self, text: str) -> None:
        self._filter_grade = text
        self._refresh_table()
