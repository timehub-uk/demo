"""
ML Central Command Widget — Unified signal pipeline dashboard.

Shows the aggregated ranked signal list from all ML tools in one place.
Each row represents one symbol with its combined_score, number of
contributing ML sources, dominant signal type, and source breakdown.

Columns: Rank | Symbol | Score | Count | Signal | MaxConf | Buy▲ | Watch▲ | Sources | Note
"""

from __future__ import annotations

from typing import Optional

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
    from ml.ml_central_command import MLCentralCommand, AggregatedSignal
except Exception:
    MLCentralCommand = None   # type: ignore[assignment, misc]
    AggregatedSignal = None   # type: ignore[assignment, misc]


_SIGNAL_COLORS = {
    "BUY":  "#00CC66",
    "SELL": "#FF4444",
    "WATCH":"#FFD700",
    "HOLD": "#888888",
}

_SCORE_BG = {
    "hot":    "#2A1A0A",   # score ≥ 0.7
    "warm":   "#1A1A2A",   # score ≥ 0.4
    "cool":   "#0A1A0A",   # score ≥ 0.2
    "cold":   "#111118",   # score < 0.2
}

_COLS = ["#", "Symbol", "Score", "Sources", "Signal", "MaxConf", "BUY▲", "WATCH▲", "Source List", "Note"]


def _score_bg(score: float) -> str:
    if score >= 0.7:
        return _SCORE_BG["hot"]
    if score >= 0.4:
        return _SCORE_BG["warm"]
    if score >= 0.2:
        return _SCORE_BG["cool"]
    return _SCORE_BG["cold"]


def _score_color(score: float) -> str:
    if score >= 0.7:
        return "#FF4040"
    if score >= 0.5:
        return "#FFB347"
    if score >= 0.3:
        return "#8888FF"
    return FG2


class SummaryBar(QFrame):
    """Compact stats strip across the top of the widget."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"background:{BG2}; border:1px solid {BORDER}; border-radius:6px;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(24)

        self._total_lbl  = self._make_stat("Active Symbols", "–")
        self._buy_lbl    = self._make_stat("BUY Signals", "–", GREEN)
        self._watch_lbl  = self._make_stat("WATCH Signals", "–", YELLOW)
        self._sources_lbl = self._make_stat("ML Sources", "–", ACCENT)

        for stat in (self._total_lbl, self._buy_lbl, self._watch_lbl, self._sources_lbl):
            layout.addWidget(stat)
        layout.addStretch()

    def _make_stat(self, title: str, value: str, color: str = FG1) -> QLabel:
        lbl = QLabel(f"<b style='color:{color};'>{value}</b><br><span style='color:{FG2};font-size:10px;'>{title}</span>")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl

    def update_stats(self, signals: list) -> None:
        total = len(signals)
        buy   = sum(1 for s in signals if s.dominant_signal == "BUY")
        watch = sum(1 for s in signals if s.dominant_signal == "WATCH")
        srcs  = len({src for s in signals for src in s.sources})

        self._total_lbl.setText(
            f"<b style='color:{FG0};'>{total}</b><br>"
            f"<span style='color:{FG2};font-size:10px;'>Active Symbols</span>"
        )
        self._buy_lbl.setText(
            f"<b style='color:{GREEN};'>{buy}</b><br>"
            f"<span style='color:{FG2};font-size:10px;'>BUY Signals</span>"
        )
        self._watch_lbl.setText(
            f"<b style='color:{YELLOW};'>{watch}</b><br>"
            f"<span style='color:{FG2};font-size:10px;'>WATCH Signals</span>"
        )
        self._sources_lbl.setText(
            f"<b style='color:{ACCENT};'>{srcs}</b><br>"
            f"<span style='color:{FG2};font-size:10px;'>ML Sources</span>"
        )


class MLCentralCommandWidget(QWidget):
    """
    ML Central Command dashboard — all ML tools' output in one unified ranked view.

    Emits ``symbol_selected`` on row double-click.
    """

    symbol_selected = pyqtSignal(str)

    def __init__(
        self,
        central_command: Optional[MLCentralCommand] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._hub = central_command
        self._signals: list[AggregatedSignal] = []
        self._filter_signal = "ALL"
        self._min_sources   = 1

        self._build_ui()
        self._connect_hub()

        self._timer = QTimer(self)
        self._timer.setInterval(15_000)   # refresh every 15 s
        self._timer.timeout.connect(self._refresh_table)
        self._timer.start()

    # ── UI construction ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Title bar
        top = QHBoxLayout()
        top.setSpacing(8)

        title = QLabel("ML Central Command  —  Unified AI Signal Pipeline")
        title.setStyleSheet(f"color:{FG0}; font-size:14px; font-weight:bold;")
        top.addWidget(title)
        top.addStretch()

        # Signal filter
        sig_f = QLabel("Signal:")
        sig_f.setStyleSheet(f"color:{FG2}; font-size:11px;")
        top.addWidget(sig_f)

        self._signal_combo = QComboBox()
        self._signal_combo.addItems(["ALL", "BUY", "WATCH", "HOLD"])
        self._signal_combo.setFixedWidth(80)
        self._signal_combo.setStyleSheet(
            f"QComboBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 6px; }}"
        )
        self._signal_combo.currentTextChanged.connect(self._on_signal_filter_changed)
        top.addWidget(self._signal_combo)

        # Min sources filter
        src_f = QLabel("Min sources:")
        src_f.setStyleSheet(f"color:{FG2}; font-size:11px;")
        top.addWidget(src_f)

        self._src_combo = QComboBox()
        self._src_combo.addItems(["1+", "2+", "3+", "4+"])
        self._src_combo.setFixedWidth(60)
        self._src_combo.setStyleSheet(
            f"QComboBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 6px; }}"
        )
        self._src_combo.currentTextChanged.connect(self._on_src_filter_changed)
        top.addWidget(self._src_combo)

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

        # Summary bar
        self._summary = SummaryBar()
        layout.addWidget(self._summary)

        # Description
        desc = QLabel(
            "Combined score = weighted sum of all ML tool confidences per symbol  ·  "
            "Score ≥ 0.7 🚨  ≥ 0.5 🔶  ≥ 0.3 👁  ·  Double-click to follow symbol on chart"
        )
        desc.setStyleSheet(f"color:{FG2}; font-size:11px;")
        layout.addWidget(desc)

        # Status
        status_row = QHBoxLayout()
        self._status_lbl = QLabel("Waiting for ML signals…")
        self._status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        status_row.addWidget(self._status_lbl)
        status_row.addStretch()
        layout.addLayout(status_row)

        # Table
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.horizontalHeader().setSectionResizeMode(0,  QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 36)
        self._table.horizontalHeader().setSectionResizeMode(9,  QHeaderView.ResizeMode.Stretch)
        for i in range(1, 9):
            self._table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(True)
        self._table.setSortingEnabled(False)
        self._table.setMinimumHeight(350)
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

    # ── Hub wiring ──────────────────────────────────────────────────────────────

    def _connect_hub(self) -> None:
        if not self._hub:
            return
        try:
            self._hub.on_update(self._on_hub_update)
        except Exception as exc:
            logger.warning(f"MLCentralCommandWidget: could not connect hub: {exc!r}")

    def _on_hub_update(self, signals: list) -> None:
        """Called from background thread — defer to Qt main thread."""
        self._signals = signals
        QTimer.singleShot(0, self._refresh_table)

    # ── Table refresh ───────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        if not self._signals and self._hub:
            try:
                self._signals = self._hub.get_top_signals(100)
            except Exception:
                pass

        signals = self._signals

        # Signal filter
        if self._filter_signal != "ALL":
            signals = [s for s in signals if s.dominant_signal == self._filter_signal]

        # Min sources filter
        signals = [s for s in signals if s.signal_count >= self._min_sources]

        self._table.setRowCount(len(signals))
        self._summary.update_stats(signals)

        for row_idx, s in enumerate(signals):
            row_bg      = QColor(_score_bg(s.combined_score))
            score_color = _score_color(s.combined_score)
            sig_color   = _SIGNAL_COLORS.get(s.dominant_signal, FG2)

            def _item(text: str, align=Qt.AlignmentFlag.AlignCenter, fg=None) -> QTableWidgetItem:
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                it.setBackground(row_bg)
                it.setForeground(QColor(fg or FG0))
                return it

            # Col 0 — rank emoji
            self._table.setItem(row_idx, 0, _item(s.rank_emoji))

            # Col 1 — symbol
            sym_item = _item(s.symbol, Qt.AlignmentFlag.AlignLeft, FG0)
            sym_item.setFont(QFont("monospace", 11, QFont.Weight.Bold))
            self._table.setItem(row_idx, 1, sym_item)

            # Col 2 — combined score
            score_item = _item(f"{s.combined_score:.3f}", fg=score_color)
            score_item.setFont(QFont("monospace", 10, QFont.Weight.Bold))
            self._table.setItem(row_idx, 2, score_item)

            # Col 3 — source count
            src_color = ACCENT if s.signal_count >= 4 else (YELLOW if s.signal_count >= 2 else FG2)
            self._table.setItem(row_idx, 3, _item(str(s.signal_count), fg=src_color))

            # Col 4 — dominant signal
            self._table.setItem(row_idx, 4, _item(s.dominant_signal, fg=sig_color))

            # Col 5 — max confidence
            self._table.setItem(row_idx, 5, _item(f"{s.max_confidence:.3f}", fg=FG1))

            # Col 6 — buy weight
            buy_color = GREEN if s.buy_weight > 0.5 else FG2
            self._table.setItem(row_idx, 6, _item(f"{s.buy_weight:.3f}", fg=buy_color))

            # Col 7 — watch weight
            wtch_color = YELLOW if s.watch_weight > 0.5 else FG2
            self._table.setItem(row_idx, 7, _item(f"{s.watch_weight:.3f}", fg=wtch_color))

            # Col 8 — source list (comma-separated short names)
            src_short = ", ".join(s.sources[:5]) + ("…" if len(s.sources) > 5 else "")
            self._table.setItem(row_idx, 8, _item(src_short, Qt.AlignmentFlag.AlignLeft, FG2))

            # Col 9 — note
            self._table.setItem(row_idx, 9, _item(s.note, Qt.AlignmentFlag.AlignLeft, FG2))

            self._table.setRowHeight(row_idx, 34)

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self._status_lbl.setText(f"Updated {ts}  ·  {len(signals)} symbols active")

    # ── Interactions ────────────────────────────────────────────────────────────

    def _on_signal_filter_changed(self, text: str) -> None:
        self._filter_signal = text
        self._refresh_table()

    def _on_src_filter_changed(self, text: str) -> None:
        try:
            self._min_sources = int(text.rstrip("+"))
        except ValueError:
            self._min_sources = 1
        self._refresh_table()

    def _on_row_double_clicked(self, index) -> None:
        row = index.row()
        sym_item = self._table.item(row, 1)
        if sym_item:
            self.symbol_selected.emit(sym_item.text().strip())
