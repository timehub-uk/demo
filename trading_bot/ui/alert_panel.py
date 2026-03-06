"""
Alert Panel – Configurable Alert Settings + Live Alert History.

Embedded in the main window as a collapsible dock or a tab in the trading view.

Layout:
  ┌──────────────────────────────────────────────────────────────────┐
  │  ALERT SETTINGS                                                  │
  │  [✓ BUY] [✓ SELL] [✓ WIN] [✓ LOSS] [✓ WASH]                    │
  │  [✓ NEW TOKEN] [✓ NEW HIGH] [✓ NEW LOW]                          │
  │  [✓ VOLUME SPIKE] [✓ EARLY PUMP]  [Test Alert]                   │
  ├──────────────────────────────────────────────────────────────────┤
  │  RECENT ALERTS  (scrolling live feed)                            │
  │  🟢 [BUY]  BTCUSDT @ 65432.00  12:34:01                        │
  │  ✅ [WIN]  BTCUSDT +$12.50 (+1.2%)  12:35:30                   │
  │  🚀 [PUMP] ETHUSDT vol 3.2×  12:36:00                           │
  └──────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QScrollArea, QFrame, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from ui.styles import ACCENT, GREEN, RED, YELLOW, BG3, BG4, BORDER, FG0, FG1, FG2

_ALERT_ROW_COLOURS = {
    "BUY":          GREEN,
    "SELL":         RED,
    "WIN":          GREEN,
    "LOSS":         RED,
    "NEW_TOKEN":    ACCENT,
    "NEW_HIGH":     YELLOW,
    "NEW_LOW":      RED,
    "VOLUME_SPIKE": YELLOW,
    "EARLY_PUMP":   ACCENT,
    "WASH":         "#FF8800",
    "CIRCUIT_BREAK": RED,
}


class AlertPanel(QWidget):
    """
    Shows alert enable/disable toggles and a live scrolling alert history.
    Thread-safe via pyqtSignal.
    """

    _alert_received = pyqtSignal(object)   # Alert dataclass

    def __init__(self, alert_manager=None, parent=None) -> None:
        super().__init__(parent)
        self._mgr = alert_manager
        self._setup_ui()

        if self._mgr:
            self._mgr.register_callback(self._on_alert_bg)

        # Connect signal (fires on main thread)
        self._alert_received.connect(self._append_alert_row)

        # Populate existing history
        QTimer.singleShot(200, self._load_history)

    # ── UI ───────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Settings ─────────────────────────────────────────────────────
        settings_grp = QGroupBox("Alert Settings")
        settings_grp.setStyleSheet(
            f"QGroupBox {{ font-size:11px; font-weight:700; }}"
        )
        sg_layout = QVBoxLayout(settings_grp)
        sg_layout.setSpacing(4)

        self._checks: dict[str, QCheckBox] = {}

        row1_types = ["BUY", "SELL", "WIN", "LOSS", "WASH"]
        row2_types = ["NEW_TOKEN", "NEW_HIGH", "NEW_LOW", "VOLUME_SPIKE", "EARLY_PUMP", "CIRCUIT_BREAK"]

        for row_types in (row1_types, row2_types):
            hl = QHBoxLayout()
            for t in row_types:
                cb = QCheckBox(t)
                cb.setChecked(True)
                cb.setStyleSheet(f"color:{FG0}; font-size:11px;")
                cb.stateChanged.connect(lambda state, name=t: self._toggle_alert(name, state))
                self._checks[t] = cb
                hl.addWidget(cb)
            hl.addStretch()
            sg_layout.addLayout(hl)

        # Test button
        test_btn = QPushButton("🔔 Test Alert")
        test_btn.setFixedHeight(26)
        test_btn.setStyleSheet(f"""
            QPushButton {{ background:{BG4}; color:{ACCENT}; border:1px solid {ACCENT}55;
                           border-radius:4px; font-size:11px; padding:0 10px; }}
            QPushButton:hover {{ background:{ACCENT}22; }}
        """)
        test_btn.clicked.connect(self._fire_test_alert)
        hl_btn = QHBoxLayout()
        hl_btn.addWidget(test_btn)
        hl_btn.addStretch()
        sg_layout.addLayout(hl_btn)
        root.addWidget(settings_grp)

        # ── Alert history table ───────────────────────────────────────────
        hist_grp = QGroupBox("Live Alert Feed")
        hg_layout = QVBoxLayout(hist_grp)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Time", "Type", "Symbol", "Message", "P&L"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(f"""
            QTableWidget {{ font-size:11px; border:none; }}
            QTableWidget::item:alternate {{ background:{BG4}; }}
        """)
        hg_layout.addWidget(self.table)

        # Clear button
        clear_btn = QPushButton("Clear History")
        clear_btn.setFixedHeight(24)
        clear_btn.setStyleSheet(f"""
            QPushButton {{ background:{BG4}; color:{FG2}; border:1px solid {BORDER};
                           border-radius:3px; font-size:10px; padding:0 8px; }}
            QPushButton:hover {{ background:{BG3}; }}
        """)
        clear_btn.clicked.connect(self.table.setRowCount)
        clear_btn.clicked.connect(lambda: self.table.setRowCount(0))
        hg_layout.addWidget(clear_btn)
        root.addWidget(hist_grp, 1)

    # ── Toggle ───────────────────────────────────────────────────────────────

    def _toggle_alert(self, name: str, state: int) -> None:
        if not self._mgr:
            return
        try:
            from core.alert_manager import AlertType
            atype = AlertType(name)
            if state:
                self._mgr.enable(atype)
            else:
                self._mgr.disable(atype)
        except Exception:
            pass

    # ── Receive alert from background thread ─────────────────────────────────

    def _on_alert_bg(self, alert) -> None:
        """Called from any thread – marshal to main thread via signal."""
        self._alert_received.emit(alert)

    def _append_alert_row(self, alert) -> None:
        """Always called on main thread via pyqtSignal."""
        ts   = alert.timestamp[11:19] if alert.timestamp else "—"
        atype = alert.alert_type.value if hasattr(alert.alert_type, "value") else str(alert.alert_type)
        sym  = alert.symbol
        msg  = alert.message
        pnl_text = f"{alert.pnl:+.4f}" if alert.pnl != 0 else "—"
        pnl_pct_text = f" ({alert.pnl_pct:+.1f}%)" if alert.pnl_pct != 0 else ""

        col = _ALERT_ROW_COLOURS.get(atype, FG0)

        r = 0   # Insert at top
        self.table.insertRow(r)
        cells = [ts, f"{alert.emoji} {atype}", sym, msg, pnl_text + pnl_pct_text]
        for c, text in enumerate(cells):
            it = QTableWidgetItem(text)
            it.setForeground(QBrush(QColor(col if c in (1, 4) else FG0)))
            self.table.setItem(r, c, it)

        # Keep max 200 rows
        while self.table.rowCount() > 200:
            self.table.removeRow(self.table.rowCount() - 1)

    def _load_history(self) -> None:
        if not self._mgr:
            return
        for alert in reversed(self._mgr.recent_alerts):
            self._append_alert_row(alert)

    def _fire_test_alert(self) -> None:
        if self._mgr:
            self._mgr.fire(
                __import__("core.alert_manager", fromlist=["AlertType"]).AlertType.WIN,
                "TESTUSDT",
                "Test alert fired from settings panel",
                price=100.0, pnl=5.0, pnl_pct=5.0,
            )
