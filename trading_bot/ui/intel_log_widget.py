"""
Intel Log Widget – real-time, dynamic activity log panel.
Shows ALL system events: trades, signals, ML updates, API calls,
webhooks, errors, and system events, updated on the fly.

Features:
  - Category colour-coding
  - Live filtering by category and severity
  - Search / highlight
  - Auto-scroll (can be paused)
  - Export to JSON
  - Expandable detail view for each entry
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSortFilterProxyModel, QThread
from PyQt6.QtGui import QColor, QBrush, QFont, QTextCursor, QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QComboBox, QLineEdit, QCheckBox, QFrame,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QSizePolicy,
)

from ui.styles import (
    ACCENT, GREEN, RED, YELLOW, BG2, BG3, BG4, BORDER, FG0, FG1, FG2
)
from utils.logger import get_intel_logger, IntelLogEntry


CATEGORY_COLOURS = {
    "TRADE":   GREEN,
    "SIGNAL":  ACCENT,
    "ML":      "#CE93D8",
    "TAX":     "#FFD740",
    "SYSTEM":  FG1,
    "API":     "#80CBC4",
    "WEBHOOK": "#FF8A65",
    "ORDER":   "#64B5F6",
}

LEVEL_COLOURS = {
    "DEBUG":    FG2,
    "INFO":     FG1,
    "SUCCESS":  GREEN,
    "WARNING":  YELLOW,
    "ERROR":    RED,
    "CRITICAL": "#FF0000",
    "TRADE":    GREEN,
    "SIGNAL":   ACCENT,
    "ML":       "#CE93D8",
    "TAX":      YELLOW,
    "SYSTEM":   FG1,
    "API":      "#80CBC4",
    "WEBHOOK":  "#FF8A65",
}

MAX_VISIBLE = 2000   # Entries visible in log panel

# ── Resize-mode helpers ────────────────────────────────────────────────────────

_RESIZE_TOGGLE_SS = f"""
QPushButton {{
    background: {BG4}; border: 1px solid {BORDER}; color: {FG1};
    border-radius: 5px; font-size: 15px; font-weight: 700; padding: 0;
}}
QPushButton:hover  {{ background: {BG3}; }}
QPushButton:checked {{
    background: {ACCENT}; border-color: {ACCENT}; color: #000;
    border-radius: 5px;
}}
"""


def _toolbar_sep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setFixedWidth(1)
    sep.setStyleSheet(f"color: {BORDER};")
    return sep


def _arrow_btn(symbol: str, tip: str) -> QPushButton:
    btn = QPushButton(symbol)
    btn.setFixedSize(30, 30)
    btn.setToolTip(tip)
    btn.setAutoRepeat(False)          # manual repeat via QTimer for smooth feel
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {ACCENT}22; border: 1px solid {ACCENT}66;
            color: {ACCENT}; border-radius: 5px;
            font-size: 15px; font-weight: 900; padding: 0;
        }}
        QPushButton:hover   {{ background: {ACCENT}44; border-color: {ACCENT}; }}
        QPushButton:pressed {{ background: {ACCENT}66; }}
    """)
    return btn


class IntelLogWidget(QWidget):
    """
    Dynamic real-time Intel Log panel.
    Subscribes to IntelLogger and updates the display on every new event.
    """

    # Signal used to safely marshal log entries from any thread → UI thread.
    # QTimer.singleShot() called from non-QThread threads triggers the
    # "QBasicTimer can only be used with threads started with QThread" flood.
    # A queued signal/slot connection is the correct cross-thread mechanism.
    _new_entry_signal = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._intel = get_intel_logger()
        self._paused = False
        self._filter_category = "ALL"
        self._filter_level = "ALL"
        self._search_text = ""
        self._entry_count = 0
        self._new_entry_signal.connect(self._append_entry)
        self._setup_ui()
        self._subscribe()
        self._populate_existing()

    # ── UI setup ───────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar ────────────────────────────────────────────────────
        self._toolbar = QFrame()
        self._toolbar.setFixedHeight(44)
        self._toolbar.setStyleSheet(f"background:{BG3}; border-bottom:1px solid {BORDER};")
        tbl = QHBoxLayout(self._toolbar)
        tbl.setContentsMargins(10, 4, 10, 4)
        tbl.setSpacing(8)

        icon_lbl = QLabel("🧠 INTEL LOG")
        icon_lbl.setStyleSheet(f"color:{ACCENT}; font-size:11px; font-weight:700; letter-spacing:1px;")
        tbl.addWidget(icon_lbl)

        tbl.addSpacing(10)

        # Category filter
        self.cat_combo = QComboBox()
        self.cat_combo.setFixedWidth(100)
        self.cat_combo.addItems(["ALL", "TRADE", "SIGNAL", "ML", "TAX", "SYSTEM", "API", "WEBHOOK", "ORDER"])
        self.cat_combo.currentTextChanged.connect(self._on_filter_changed)
        tbl.addWidget(QLabel("Category:"))
        tbl.addWidget(self.cat_combo)

        # Level filter
        self.lvl_combo = QComboBox()
        self.lvl_combo.setFixedWidth(90)
        self.lvl_combo.addItems(["ALL", "SUCCESS", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.lvl_combo.currentTextChanged.connect(self._on_filter_changed)
        tbl.addWidget(QLabel("Level:"))
        tbl.addWidget(self.lvl_combo)

        # Search
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search logs…")
        self.search_input.setFixedWidth(200)
        self.search_input.textChanged.connect(self._on_search_changed)
        tbl.addWidget(self.search_input)

        tbl.addStretch()

        # Entry count
        self.count_lbl = QLabel("0 entries")
        self.count_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        tbl.addWidget(self.count_lbl)

        # Auto-scroll
        self.auto_scroll_cb = QCheckBox("Auto-scroll")
        self.auto_scroll_cb.setChecked(True)
        tbl.addWidget(self.auto_scroll_cb)

        # Pause
        self.pause_btn = QPushButton("⏸ Pause")
        self.pause_btn.setFixedWidth(80)
        self.pause_btn.clicked.connect(self._toggle_pause)
        tbl.addWidget(self.pause_btn)

        # Clear
        clear_btn = QPushButton("🗑 Clear")
        clear_btn.setFixedWidth(70)
        clear_btn.clicked.connect(self._clear)
        tbl.addWidget(clear_btn)

        # Export
        export_btn = QPushButton("📥 Export")
        export_btn.setFixedWidth(80)
        export_btn.clicked.connect(self._export)
        tbl.addWidget(export_btn)

        tbl.addSpacing(6)
        tbl.addWidget(_toolbar_sep())

        # ── Resize-mode toggle ⇕ ──────────────────────────────────────
        self._resize_toggle = QPushButton("⇕")
        self._resize_toggle.setFixedSize(30, 30)
        self._resize_toggle.setCheckable(True)
        self._resize_toggle.setToolTip(
            "Toggle height-adjust mode\n"
            "▲ / ▼ arrows appear — hold to resize"
        )
        self._resize_toggle.setStyleSheet(_RESIZE_TOGGLE_SS)
        self._resize_toggle.toggled.connect(self._on_resize_mode_toggled)
        tbl.addWidget(self._resize_toggle)

        # ▲ / ▼ arrow buttons — hidden until resize mode is active
        self._up_btn = _arrow_btn("▲", "Make log panel taller  (hold for continuous)")
        self._dn_btn = _arrow_btn("▼", "Make log panel shorter  (hold for continuous)")
        self._up_btn.hide()
        self._dn_btn.hide()
        tbl.addWidget(self._up_btn)
        tbl.addWidget(self._dn_btn)

        # Repeat-resize timer — fires while an arrow button is held
        self._resize_timer = QTimer(self)
        self._resize_timer.setInterval(35)          # ~28 fps feel
        self._resize_delta = 0
        self._resize_timer.timeout.connect(self._do_resize_step)

        self._up_btn.pressed.connect(lambda: self._start_resize(+12))   # taller
        self._up_btn.released.connect(self._stop_resize)
        self._dn_btn.pressed.connect(lambda: self._start_resize(-12))   # shorter
        self._dn_btn.released.connect(self._stop_resize)

        layout.addWidget(self._toolbar)

        # Main log display (QTextEdit for rich text)
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("Menlo", 11))  # CSS font-family fallback handles SF Mono / Consolas
        self.log_display.setStyleSheet(f"""
            QTextEdit {{
                background: {BG2};
                color: {FG0};
                border: none;
                padding: 4px;
                font-family: "SF Mono", "Menlo", "Consolas", "Courier New", monospace;
                font-size: 12px;
                line-height: 1.4;
            }}
        """)
        layout.addWidget(self.log_display, 1)

        # Status bar
        status_bar = QFrame()
        status_bar.setFixedHeight(24)
        status_bar.setStyleSheet(f"background:{BG3}; border-top:1px solid {BORDER};")
        sl = QHBoxLayout(status_bar)
        sl.setContentsMargins(10, 2, 10, 2)
        self.status_lbl = QLabel("Live – connected")
        self.status_lbl.setStyleSheet(f"color:{GREEN}; font-size:10px;")
        sl.addWidget(self.status_lbl)
        sl.addStretch()
        self.rate_lbl = QLabel("")
        self.rate_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        sl.addWidget(self.rate_lbl)
        layout.addWidget(status_bar)

        # Rate counter timer
        self._rate_count = 0
        self._rate_timer = QTimer(self)
        self._rate_timer.timeout.connect(self._update_rate)
        self._rate_timer.start(1000)

    # ── Resize-mode ─────────────────────────────────────────────────────

    def _on_resize_mode_toggled(self, active: bool) -> None:
        """Show / hide ▲ ▼ arrows and highlight toolbar while in resize mode."""
        self._up_btn.setVisible(active)
        self._dn_btn.setVisible(active)

        if active:
            # Highlight the toolbar border to signal active state
            self._toolbar.setStyleSheet(
                f"background:{BG3}; border-bottom:2px solid {ACCENT};"
            )
            # Switch cursor for the whole widget so the user knows they're in resize mode
            self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
            self._resize_toggle.setToolTip("Click to exit height-adjust mode")
        else:
            self._stop_resize()
            self._toolbar.setStyleSheet(
                f"background:{BG3}; border-bottom:1px solid {BORDER};"
            )
            self.unsetCursor()
            self._resize_toggle.setToolTip(
                "Toggle height-adjust mode\n▲ / ▼ arrows appear — hold to resize"
            )

    def _start_resize(self, delta: int) -> None:
        """Begin continuous resize; delta > 0 = taller, delta < 0 = shorter."""
        self._resize_delta = delta
        self._do_resize_step()      # immediate first step
        self._resize_timer.start()

    def _stop_resize(self) -> None:
        self._resize_timer.stop()
        self._resize_delta = 0

    def _do_resize_step(self) -> None:
        """Adjust the parent QDockWidget height by one step."""
        from PyQt6.QtWidgets import QMainWindow
        dock = self.parent()         # IntelLogWidget → QDockWidget
        if dock is None:
            return
        # Walk the parent chain to find the QMainWindow reliably
        main = None
        p = dock.parent()
        while p is not None:
            if isinstance(p, QMainWindow):
                main = p
                break
            p = p.parent()
        if main is None:
            return
        try:
            current = dock.height()
            new_h = max(80, current + self._resize_delta)
            # resizeDocks is the correct API for programmatic dock resizing
            main.resizeDocks([dock], [new_h], Qt.Orientation.Vertical)
        except Exception:
            pass

    # ── Subscription ────────────────────────────────────────────────────
    def _subscribe(self) -> None:
        self._intel.subscribe(self._on_new_entry)

    def _on_new_entry(self, entry: IntelLogEntry) -> None:
        """Called from any thread – emit signal to queue onto UI thread."""
        self._new_entry_signal.emit(entry)

    # ── Entry rendering ─────────────────────────────────────────────────
    def _append_entry(self, entry: IntelLogEntry) -> None:
        if self._paused:
            return
        if not self._matches_filter(entry):
            return

        self._entry_count += 1
        self._rate_count += 1

        cat_colour = CATEGORY_COLOURS.get(entry.category, FG1)
        lvl_colour = LEVEL_COLOURS.get(entry.level, FG1)

        html = (
            f'<span style="color:{FG2};">{entry.ts_str}</span>'
            f' <span style="color:{cat_colour}; font-weight:600;">[{entry.category}]</span>'
            f' <span style="color:{lvl_colour};">{entry.icon} {entry.level}</span>'
            f' <span style="color:{FG2};">│</span>'
            f' <span style="color:{ACCENT};">[{entry.source}]</span>'
            f' <span style="color:{FG0};">{self._escape(entry.message)}</span>'
        )
        if entry.data:
            import json
            try:
                data_str = json.dumps(entry.data, default=str)[:200]
                html += f' <span style="color:{FG2}; font-size:10px;">  {self._escape(data_str)}</span>'
            except Exception:
                pass

        self.log_display.append(html)

        # Trim if too many lines
        doc = self.log_display.document()
        while doc.blockCount() > MAX_VISIBLE:
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

        if self.auto_scroll_cb.isChecked():
            self.log_display.moveCursor(QTextCursor.MoveOperation.End)

        self.count_lbl.setText(f"{self._entry_count:,} entries")

    # ── Filtering ────────────────────────────────────────────────────────
    def _matches_filter(self, entry: IntelLogEntry) -> bool:
        if self._filter_category != "ALL" and entry.category != self._filter_category:
            return False
        if self._filter_level != "ALL" and entry.level != self._filter_level:
            return False
        if self._search_text and self._search_text.lower() not in entry.message.lower():
            return False
        return True

    def _on_filter_changed(self) -> None:
        self._filter_category = self.cat_combo.currentText()
        self._filter_level = self.lvl_combo.currentText()
        self._rebuild()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text
        self._rebuild()

    def _rebuild(self) -> None:
        """Rebuild log display from buffer after filter change."""
        self.log_display.clear()
        self._entry_count = 0
        entries = self._intel.recent(n=2000)
        for e in entries:
            self._append_entry(e)

    def _populate_existing(self) -> None:
        """Show entries that arrived before widget was created."""
        for entry in self._intel.recent(n=200):
            self._append_entry(entry)

    # ── Controls ─────────────────────────────────────────────────────────
    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        if self._paused:
            self.pause_btn.setText("▶ Resume")
            self.status_lbl.setText("Paused")
            self.status_lbl.setStyleSheet(f"color:{YELLOW}; font-size:10px;")
        else:
            self.pause_btn.setText("⏸ Pause")
            self.status_lbl.setText("Live – connected")
            self.status_lbl.setStyleSheet(f"color:{GREEN}; font-size:10px;")
            self._rebuild()

    def _clear(self) -> None:
        self.log_display.clear()
        self._intel.clear()
        self._entry_count = 0
        self.count_lbl.setText("0 entries")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Intel Log", "intel_log.json", "JSON Files (*.json)"
        )
        if path:
            self._intel.export_json(Path(path))

    def _update_rate(self) -> None:
        self.rate_lbl.setText(f"{self._rate_count} events/s")
        self._rate_count = 0

    @staticmethod
    def _escape(text: str) -> str:
        return (text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))
