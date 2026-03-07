"""
Trend Widget — Multi-timeframe trend dashboard.

Displays a colour-coded table showing trend direction (UP / SIDEWAYS / DOWN)
and strength for every monitored symbol across 7 timeframes.

Columns: Symbol | Price | 15m | 30m | 1h | 12h | 24h | 7d | 30d

Cell colour legend:
  Green  → UP      (intensity scales with strength)
  Yellow → SIDEWAYS
  Red    → DOWN    (intensity scales with strength)

Each cell shows:
  Line 1: arrow + direction label (↑ UP / → SIDE / ↓ DOWN)
  Line 2: % change over the timeframe window
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QAbstractItemView, QFrame, QComboBox, QSizePolicy,
)
from loguru import logger

try:
    from ml.trend_scanner import TrendScanner, TrendSnapshot, TrendResult, TIMEFRAMES
except Exception:
    TrendScanner = None   # type: ignore[assignment, misc]
    TIMEFRAMES = ["15m", "30m", "1h", "12h", "24h", "7d", "30d"]
    TrendResult = None  # type: ignore[assignment, misc]
    TrendSnapshot = None  # type: ignore[assignment, misc]

from ui.styles import (
    ACCENT, BG1, BG2, BG3, BG4, BORDER, BORDER2,
    FG0, FG1, FG2, GREEN, RED, YELLOW,
)


# ── Colour helpers ─────────────────────────────────────────────────────────────

def _cell_bg(direction: str, strength: float) -> QColor:
    """Return a QColor for the cell background based on direction + strength."""
    alpha = int(40 + 140 * min(1.0, strength))   # 40–180 alpha range
    if direction == "UP":
        return QColor(0, 200, 100, alpha)
    if direction == "DOWN":
        return QColor(220, 60, 60, alpha)
    return QColor(200, 180, 0, 50)   # sideways — always faint yellow


def _cell_text_color(direction: str) -> str:
    if direction == "UP":
        return GREEN
    if direction == "DOWN":
        return RED
    return YELLOW


def _direction_arrow(direction: str) -> str:
    return {"UP": "↑", "DOWN": "↓", "SIDEWAYS": "→"}.get(direction, "?")


def _strength_dots(strength: float) -> str:
    """Visual strength bar using block characters (▪ / ▫)."""
    filled = round(strength * 5)
    return "▪" * filled + "▫" * (5 - filled)


# ── Main widget ────────────────────────────────────────────────────────────────

class TrendWidget(QWidget):
    """
    Multi-timeframe trend dashboard widget.

    Instantiate with a ``TrendScanner`` instance (or None for offline demo).
    """

    symbol_selected = pyqtSignal(str)   # emitted when user double-clicks a row

    # Column layout
    _COL_SYMBOL = 0
    _COL_PRICE  = 1
    _COL_TF_START = 2   # timeframe columns start here

    def __init__(self, trend_scanner: Optional[TrendScanner] = None, parent=None) -> None:
        super().__init__(parent)
        self._scanner = trend_scanner
        self._snapshots: dict[str, TrendSnapshot] = {}
        self._sort_col  = "symbol"
        self._sort_asc  = True

        self._build_ui()
        self._connect_scanner()

        # Auto-refresh timer (fallback in case callbacks are sparse)
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)   # 30 s
        self._timer.timeout.connect(self._refresh_table)
        self._timer.start()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Top bar ────────────────────────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(8)

        title = QLabel("Multi-Timeframe Trend Scanner")
        title.setStyleSheet(f"color:{FG0}; font-size:14px; font-weight:bold;")
        top.addWidget(title)

        top.addStretch()

        # Sort control
        sort_lbl = QLabel("Sort:")
        sort_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        top.addWidget(sort_lbl)

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["Symbol", "Price"] + TIMEFRAMES)
        self._sort_combo.setFixedWidth(90)
        self._sort_combo.setStyleSheet(
            f"QComboBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 6px; }}"
        )
        self._sort_combo.currentTextChanged.connect(self._on_sort_changed)
        top.addWidget(self._sort_combo)

        # Add symbol
        self._sym_input = QLineEdit()
        self._sym_input.setPlaceholderText("Add symbol…")
        self._sym_input.setFixedWidth(120)
        self._sym_input.setStyleSheet(
            f"QLineEdit {{ background:{BG3}; color:{FG0}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 6px; }}"
        )
        self._sym_input.returnPressed.connect(self._on_add_symbol)
        top.addWidget(self._sym_input)

        add_btn = QPushButton("+ Add")
        add_btn.setFixedWidth(60)
        add_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{ACCENT}; border:1px solid {ACCENT}; "
            f"border-radius:4px; padding:3px 8px; }}"
            f"QPushButton:hover {{ background:{ACCENT}; color:#000; }}"
        )
        add_btn.clicked.connect(self._on_add_symbol)
        top.addWidget(add_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setFixedWidth(70)
        remove_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{RED}; border:1px solid {RED}; "
            f"border-radius:4px; padding:3px 8px; }}"
            f"QPushButton:hover {{ background:{RED}; color:#fff; }}"
        )
        remove_btn.clicked.connect(self._on_remove_selected)
        top.addWidget(remove_btn)

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

        # ── Legend bar ─────────────────────────────────────────────────────────
        legend = QHBoxLayout()
        legend.setSpacing(16)
        for label, color in [("↑ Uptrend", GREEN), ("→ Sideways", YELLOW), ("↓ Downtrend", RED)]:
            lbl = QLabel(f"<span style='color:{color};'>■</span>  {label}")
            lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
            legend.addWidget(lbl)
        legend.addStretch()
        self._status_lbl = QLabel("Scanning…")
        self._status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        legend.addWidget(self._status_lbl)
        layout.addLayout(legend)

        # ── Table ──────────────────────────────────────────────────────────────
        n_cols = 2 + len(TIMEFRAMES)
        self._table = QTableWidget(0, n_cols)
        headers = ["Symbol", "Price"] + TIMEFRAMES
        self._table.setHorizontalHeaderLabels(headers)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for i in range(2, n_cols):
            self._table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)

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

    # ── Scanner wiring ─────────────────────────────────────────────────────────

    def _connect_scanner(self) -> None:
        if not self._scanner:
            return
        try:
            self._scanner.on_update(self._on_scanner_update)
        except Exception as exc:
            logger.warning(f"TrendWidget: could not connect scanner: {exc!r}")

    def _on_scanner_update(self, snapshots: dict) -> None:
        """Called from scanner background thread — defer UI update to Qt thread."""
        from PyQt6.QtCore import QTimer
        self._snapshots = dict(snapshots)
        QTimer.singleShot(0, self._refresh_table)

    # ── Table refresh ──────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        snaps = dict(self._snapshots)
        if not snaps and self._scanner:
            snaps = self._scanner.get_all_snapshots()

        rows = sorted(snaps.values(), key=self._sort_key)

        self._table.setRowCount(len(rows))

        for row_idx, snap in enumerate(rows):
            # Symbol
            sym_item = QTableWidgetItem(snap.symbol)
            sym_item.setForeground(QColor(FG0))
            sym_item.setFont(QFont("monospace", 11, QFont.Weight.Bold))
            self._table.setItem(row_idx, 0, sym_item)

            # Price
            price_str = self._fmt_price(snap.last_price)
            price_item = QTableWidgetItem(price_str)
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            price_item.setForeground(QColor(FG1))
            self._table.setItem(row_idx, 1, price_item)

            # Timeframe cells
            for col_offset, tf in enumerate(TIMEFRAMES):
                col = 2 + col_offset
                tr = snap.trends.get(tf)
                if tr is None:
                    item = QTableWidgetItem("—")
                    item.setForeground(QColor(FG2))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self._table.setItem(row_idx, col, item)
                    continue

                arrow   = _direction_arrow(tr.direction)
                sign    = "+" if tr.change_pct >= 0 else ""
                text    = f"{arrow} {tr.direction[:4]}\n{sign}{tr.change_pct:.2f}%"
                item    = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(_cell_bg(tr.direction, tr.strength))
                item.setForeground(QColor(_cell_text_color(tr.direction)))
                item.setToolTip(
                    f"<b>{snap.symbol} — {tf}</b><br>"
                    f"Direction: {tr.direction}<br>"
                    f"Strength: {tr.strength_label} ({tr.strength:.0%})<br>"
                    f"Change: {sign}{tr.change_pct:.3f}%<br>"
                    f"R²: {tr.r_squared:.2f}<br>"
                    f"Slope/price: {tr.slope_norm:.2e}"
                )
                self._table.setItem(row_idx, col, item)

            self._table.setRowHeight(row_idx, 42)

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self._status_lbl.setText(f"Updated {ts}  ·  {len(rows)} symbols")

    def _sort_key(self, snap: "TrendSnapshot"):
        col = self._sort_col.lower()
        if col == "symbol":
            return snap.symbol
        if col == "price":
            return -snap.last_price
        # Sort by change_pct for timeframe columns
        tr = snap.trends.get(col)
        if tr is None:
            return 0.0
        # UP first, then SIDE, then DOWN when ascending
        direction_rank = {"UP": -1, "SIDEWAYS": 0, "DOWN": 1}
        return (direction_rank.get(tr.direction, 0), -tr.strength)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_price(price: float) -> str:
        if price >= 1000:
            return f"{price:,.2f}"
        if price >= 1:
            return f"{price:.4f}"
        if price >= 0.001:
            return f"{price:.6f}"
        return f"{price:.8f}"

    # ── Interactions ───────────────────────────────────────────────────────────

    def _on_sort_changed(self, text: str) -> None:
        self._sort_col = text.lower()
        self._refresh_table()

    def _on_add_symbol(self) -> None:
        sym = self._sym_input.text().strip().upper()
        if not sym:
            return
        if not sym.endswith("USDT"):
            sym += "USDT"
        self._sym_input.clear()
        if self._scanner:
            self._scanner.add_symbol(sym)
        logger.info(f"TrendWidget: added symbol {sym}")

    def _on_remove_selected(self) -> None:
        rows = self._table.selectedItems()
        if not rows:
            return
        row = self._table.currentRow()
        sym_item = self._table.item(row, 0)
        if not sym_item:
            return
        sym = sym_item.text()
        if self._scanner:
            self._scanner.remove_symbol(sym)
        self._snapshots.pop(sym, None)
        self._refresh_table()

    def _on_row_double_clicked(self, index) -> None:
        row = index.row()
        item = self._table.item(row, 0)
        if item:
            self.symbol_selected.emit(item.text())
