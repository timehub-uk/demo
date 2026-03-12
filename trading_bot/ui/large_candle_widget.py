"""
Large Candle Widget — Displays alerts for rapidly expanding candles.

Shows tokens classified as WATCH / ALERT / STRONG based on the
LargeCandleWatcher analysis of candle range expansion, volume surge,
and body-to-range ratio across 1m / 5m / 15m timeframes.

Columns: Label | Symbol | TF | Dir | ×Avg | Range% | AvgRange% | Body | Vol× | Score | Chg% | Note
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
    from ml.large_candle_watcher import LargeCandleWatcher, LargeCandleResult
except Exception:
    LargeCandleWatcher = None   # type: ignore[assignment, misc]
    LargeCandleResult  = None   # type: ignore[assignment, misc]


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

_DIR_COLORS = {
    "BULL":  "#00CC66",
    "BEAR":  "#FF4444",
    "MIXED": "#AAAAAA",
}

_COLS = ["", "Symbol", "TF", "Dir", "×Avg", "Range%", "Avg%", "Body", "Vol×", "Score", "Chg%", "Note"]


class LargeCandleWidget(QWidget):
    """
    Large candle expansion alert dashboard.

    Fires ``symbol_selected`` signal when user double-clicks a row.
    """

    symbol_selected = pyqtSignal(str)

    def __init__(
        self,
        large_candle_watcher: Optional[LargeCandleWatcher] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._watcher = large_candle_watcher
        self._results: list[LargeCandleResult] = []
        self._filter_label = "ALL"
        self._filter_tf    = "ALL"

        self._build_ui()
        self._connect_watcher()

        self._timer = QTimer(self)
        self._timer.setInterval(30_000)   # refresh every 30 s
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

        title = QLabel("Large Candle Watch  —  Rapid Expansion Alerts")
        title.setStyleSheet(f"color:{FG0}; font-size:14px; font-weight:bold;")
        top.addWidget(title)
        top.addStretch()

        # Label filter
        lbl_f = QLabel("Level:")
        lbl_f.setStyleSheet(f"color:{FG2}; font-size:11px;")
        top.addWidget(lbl_f)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["ALL", "STRONG", "ALERT", "WATCH"])
        self._filter_combo.setFixedWidth(90)
        self._filter_combo.setStyleSheet(
            f"QComboBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 6px; }}"
        )
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        top.addWidget(self._filter_combo)

        # Timeframe filter
        tf_f = QLabel("TF:")
        tf_f.setStyleSheet(f"color:{FG2}; font-size:11px;")
        top.addWidget(tf_f)

        self._tf_combo = QComboBox()
        self._tf_combo.addItems(["ALL", "1m", "5m", "15m"])
        self._tf_combo.setFixedWidth(72)
        self._tf_combo.setStyleSheet(
            f"QComboBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 6px; }}"
        )
        self._tf_combo.currentTextChanged.connect(self._on_tf_filter_changed)
        top.addWidget(self._tf_combo)

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

        # Legend + description
        desc = QLabel(
            "↑ BULL expansion (green)  |  ↓ BEAR expansion (red)  |  "
            "↔ MIXED (wick only)  ·  ×Avg = how many times bigger than recent average"
        )
        desc.setStyleSheet(f"color:{FG2}; font-size:11px;")
        layout.addWidget(desc)

        legend = QHBoxLayout()
        legend.setSpacing(16)
        for lbl, col in [
            ("⬛ NONE",   "#555555"),
            ("👁 WATCH",  "#8888FF"),
            ("🔶 ALERT",  "#FFB347"),
            ("🚨 STRONG", "#FF4040"),
        ]:
            w = QLabel(f"<span style='color:{col};'>{lbl}</span>")
            w.setStyleSheet(f"color:{FG2}; font-size:11px;")
            legend.addWidget(w)
        legend.addStretch()
        self._status_lbl = QLabel("Scanning…")
        self._status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        legend.addWidget(self._status_lbl)
        layout.addLayout(legend)

        # Table
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.horizontalHeader().setSectionResizeMode(0,  QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 68)
        self._table.horizontalHeader().setSectionResizeMode(11, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 11):
            self._table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(True)
        self._table.setSortingEnabled(False)
        self._table.setMinimumHeight(300)
        self._table.doubleClicked.connect(self._on_row_double_clicked)

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

    # ── Watcher wiring ──────────────────────────────────────────────────────────

    def _connect_watcher(self) -> None:
        if not self._watcher:
            return
        try:
            self._watcher.on_alert(self._on_watcher_update)
        except Exception as exc:
            logger.warning(f"LargeCandleWidget: could not connect watcher: {exc!r}")

    def _on_watcher_update(self, results: list) -> None:
        """Called from background thread — defer to Qt main thread."""
        self._results = results
        QTimer.singleShot(0, self._refresh_table)

    # ── Table refresh ───────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        if not self._results and self._watcher:
            try:
                self._results = self._watcher.get_alerts()
            except Exception:
                pass

        results = self._results

        # Label filter
        if self._filter_label != "ALL":
            results = [r for r in results if r.label == self._filter_label]

        # TF filter
        if self._filter_tf != "ALL":
            results = [r for r in results if r.timeframe == self._filter_tf]

        self._table.setRowCount(len(results))

        for row_idx, r in enumerate(results):
            row_bg      = QColor(_LABEL_BG.get(r.label, "#1A1A2E"))
            label_color = _LABEL_COLORS.get(r.label, FG2)
            dir_color   = _DIR_COLORS.get(r.direction, FG2)

            def _item(text: str, align=Qt.AlignmentFlag.AlignCenter, fg=None) -> QTableWidgetItem:
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                it.setBackground(row_bg)
                it.setForeground(QColor(fg or FG0))
                return it

            # Col 0 — label emoji + text
            lbl_item = QTableWidgetItem(f"{r.label_emoji} {r.label}")
            lbl_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            lbl_item.setBackground(row_bg)
            lbl_item.setForeground(QColor(label_color))
            lbl_item.setFont(QFont("monospace", 10, QFont.Weight.Bold))
            self._table.setItem(row_idx, 0, lbl_item)

            # Col 1 — symbol
            sym_item = _item(r.symbol, Qt.AlignmentFlag.AlignLeft, FG0)
            sym_item.setFont(QFont("monospace", 11, QFont.Weight.Bold))
            self._table.setItem(row_idx, 1, sym_item)

            # Col 2 — timeframe
            self._table.setItem(row_idx, 2, _item(r.timeframe, fg=FG2))

            # Col 3 — direction
            dir_item = _item(f"{r.direction_emoji} {r.direction}", fg=dir_color)
            dir_item.setFont(QFont("monospace", 10, QFont.Weight.Bold))
            self._table.setItem(row_idx, 3, dir_item)

            # Col 4 — expansion ratio
            exp_color = (
                "#FF4040" if r.expansion_ratio >= STRONG_RATIO
                else "#FFB347" if r.expansion_ratio >= ALERT_RATIO
                else "#8888FF" if r.expansion_ratio >= WATCH_RATIO
                else FG2
            )
            self._table.setItem(row_idx, 4, _item(f"×{r.expansion_ratio:.1f}", fg=exp_color))

            # Col 5 — current range %
            self._table.setItem(row_idx, 5, _item(f"{r.candle_range_pct:.3f}%"))

            # Col 6 — avg range %
            self._table.setItem(row_idx, 6, _item(f"{r.avg_range_pct:.3f}%", fg=FG2))

            # Col 7 — body ratio
            body_color = GREEN if r.body_ratio >= 0.7 else (FG2 if r.body_ratio >= 0.4 else YELLOW)
            self._table.setItem(row_idx, 7, _item(f"{r.body_ratio:.2f}", fg=body_color))

            # Col 8 — volume ratio
            vol_color = GREEN if r.volume_ratio >= 3.0 else (YELLOW if r.volume_ratio >= 1.5 else FG2)
            self._table.setItem(row_idx, 8, _item(f"×{r.volume_ratio:.1f}", fg=vol_color))

            # Col 9 — score
            self._table.setItem(row_idx, 9, _item(f"{r.candle_score:.3f}", fg=label_color))

            # Col 10 — price change %
            chg_color = GREEN if r.price_change_pct >= 0 else RED
            sign = "+" if r.price_change_pct >= 0 else ""
            self._table.setItem(row_idx, 10, _item(f"{sign}{r.price_change_pct:.2f}%", fg=chg_color))

            # Col 11 — note
            self._table.setItem(row_idx, 11, _item(r.note, Qt.AlignmentFlag.AlignLeft, FG2))

            self._table.setRowHeight(row_idx, 36)

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self._status_lbl.setText(f"Updated {ts}  ·  {len(results)} alerts")

    # ── Interactions ────────────────────────────────────────────────────────────

    def _on_filter_changed(self, text: str) -> None:
        self._filter_label = text
        self._refresh_table()

    def _on_tf_filter_changed(self, text: str) -> None:
        self._filter_tf = text
        self._refresh_table()

    def _on_row_double_clicked(self, index) -> None:
        row = index.row()
        sym_item = self._table.item(row, 1)
        if sym_item:
            self.symbol_selected.emit(sym_item.text().strip())


# Import thresholds for color coding in _refresh_table
try:
    from ml.large_candle_watcher import WATCH_RATIO, ALERT_RATIO, STRONG_RATIO
except Exception:
    WATCH_RATIO  = 2.5
    ALERT_RATIO  = 4.0
    STRONG_RATIO = 6.0
