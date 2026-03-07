"""
Simulation Menu / Live Simulation Twin Widget
=============================================
UI panel for the Live Simulation Twin engine.

Shortcut: Shift+Alt+9 (Layer 9 – Simulation)
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from ui.styles import DARK_BG, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, TEXT_MUTED
except Exception:
    DARK_BG = "#0A0A12"
    ACCENT_BLUE = "#00D4FF"
    ACCENT_GREEN = "#00FF88"
    ACCENT_RED = "#FF4444"
    TEXT_MUTED = "#8888AA"


class SimulationTwinWidget(QWidget):
    """
    Live Simulation Twin control panel.

    Shows:
    - Twin running status
    - Current live accuracy vs baseline
    - Drift alerts
    - Variant comparison table (which alternative performs best)
    - Recent shadow decisions
    - Missed opportunity cost

    Keyboard shortcut: Shift+Alt+9
    """

    def __init__(self, twin=None, parent=None):
        super().__init__(parent)
        self._twin = twin
        self._setup_ui()
        self._setup_timer()
        self._setup_shortcut()

    def _setup_shortcut(self):
        sc = QShortcut(QKeySequence("Shift+Alt+9"), self)
        sc.activated.connect(self.show)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Live Simulation Twin  ·  Shadow Engine")
        title.setStyleSheet(f"color:{ACCENT_BLUE}; font-size:16px; font-weight:bold;")
        hdr.addWidget(title)
        hdr.addStretch()

        self._status_lbl = QLabel("● STOPPED")
        self._status_lbl.setStyleSheet(f"color:{ACCENT_RED}; font-weight:bold;")
        hdr.addWidget(self._status_lbl)

        self._start_btn = QPushButton("Start Twin")
        self._start_btn.setFixedWidth(110)
        self._start_btn.clicked.connect(self._toggle_twin)
        self._start_btn.setStyleSheet(
            f"background:{ACCENT_BLUE}; color:#000; font-weight:bold; border-radius:4px; padding:4px;"
        )
        hdr.addWidget(self._start_btn)
        root.addLayout(hdr)

        # ── Metrics row ───────────────────────────────────────────────────────
        metrics_row = QHBoxLayout()
        self._accuracy_card = self._make_metric_card("Live Accuracy", "—", ACCENT_BLUE)
        self._baseline_card = self._make_metric_card("Baseline", "52.0%", TEXT_MUTED)
        self._decisions_card = self._make_metric_card("Decisions Tracked", "0", ACCENT_GREEN)
        self._drift_card = self._make_metric_card("Drift Alerts", "0", ACCENT_RED)
        for card in (self._accuracy_card, self._baseline_card,
                     self._decisions_card, self._drift_card):
            metrics_row.addWidget(card)
        root.addLayout(metrics_row)

        # ── Splitter: variant table | drift alerts ────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Variant performance table
        var_grp = QGroupBox("Variant Performance vs Live")
        var_grp.setStyleSheet(f"QGroupBox {{ color:{ACCENT_BLUE}; }}")
        var_lay = QVBoxLayout(var_grp)
        self._variant_table = QTableWidget(0, 4)
        self._variant_table.setHorizontalHeaderLabels(
            ["Variant", "Win Rate vs Live", "Avg Δ PnL", "Evaluations"]
        )
        self._variant_table.horizontalHeader().setStretchLastSection(True)
        self._variant_table.setStyleSheet(self._table_style())
        var_lay.addWidget(self._variant_table)
        splitter.addWidget(var_grp)

        # Drift alerts panel
        drift_grp = QGroupBox("Drift Alerts")
        drift_grp.setStyleSheet(f"QGroupBox {{ color:{ACCENT_RED}; }}")
        drift_lay = QVBoxLayout(drift_grp)
        self._drift_scroll = QScrollArea()
        self._drift_scroll.setWidgetResizable(True)
        self._drift_content = QWidget()
        self._drift_vbox = QVBoxLayout(self._drift_content)
        self._drift_vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._drift_scroll.setWidget(self._drift_content)
        drift_lay.addWidget(self._drift_scroll)
        splitter.addWidget(drift_grp)

        splitter.setSizes([600, 350])
        root.addWidget(splitter, stretch=1)

        # ── Description ───────────────────────────────────────────────────────
        desc = QLabel(
            "The Simulation Twin replays every live decision in parallel across 6 variants: "
            "size_half, size_2x, delayed_5m, tighter_stop, wider_stop, skip. "
            "Model drift is detected when live accuracy deviates >5% from backtested baseline."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        root.addWidget(desc)

    def _make_metric_card(self, label: str, value: str, color: str) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet(f"background:#12121E; border-radius:6px; border:1px solid #2A2A4A;")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 8, 12, 8)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{TEXT_MUTED}; font-size:10px;")
        val = QLabel(value)
        val.setStyleSheet(f"color:{color}; font-size:18px; font-weight:bold;")
        val.setObjectName(f"metric_{label.replace(' ', '_')}")
        lay.addWidget(lbl)
        lay.addWidget(val)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return frame

    def _setup_timer(self):
        self._timer = QTimer()
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _toggle_twin(self):
        if not self._twin:
            return
        if self._twin.is_running:
            self._twin.stop()
            self._start_btn.setText("Start Twin")
            self._status_lbl.setText("● STOPPED")
            self._status_lbl.setStyleSheet(f"color:{ACCENT_RED}; font-weight:bold;")
        else:
            self._twin.start()
            self._start_btn.setText("Stop Twin")
            self._status_lbl.setText("● RUNNING")
            self._status_lbl.setStyleSheet(f"color:{ACCENT_GREEN}; font-weight:bold;")

    def _refresh(self):
        if not self._twin:
            return

        # Status
        if self._twin.is_running:
            self._status_lbl.setText("● RUNNING")
            self._status_lbl.setStyleSheet(f"color:{ACCENT_GREEN}; font-weight:bold;")
            self._start_btn.setText("Stop Twin")

        # Accuracy
        acc = self._twin.get_current_accuracy()
        self._set_metric_value("Live Accuracy", f"{acc:.1%}" if acc else "—")
        self._set_metric_value("Decisions Tracked", str(self._twin.get_decision_count()))

        # Drift alerts
        alerts = self._twin.get_drift_alerts()
        self._set_metric_value("Drift Alerts", str(len(alerts)))
        self._update_drift_panel(alerts)

        # Variant stats
        stats = self._twin.get_best_variant_stats()
        self._update_variant_table(stats)

    def _set_metric_value(self, label: str, value: str):
        key = f"metric_{label.replace(' ', '_')}"
        lbl = self.findChild(QLabel, key)
        if lbl:
            lbl.setText(value)

    def _update_drift_panel(self, alerts):
        # Clear existing
        while self._drift_vbox.count():
            item = self._drift_vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for alert in alerts[-10:]:
            color = ACCENT_RED if alert.severity == "severe" else "#FFA500"
            lbl = QLabel(
                f"[{time.strftime('%H:%M', time.localtime(alert.timestamp))}] "
                f"{alert.metric}: {alert.current_value:.3f} "
                f"(baseline {alert.baseline_value:.3f}) "
                f"{alert.drift_pct:+.1f}%  [{alert.severity.upper()}]"
            )
            lbl.setStyleSheet(f"color:{color}; font-size:11px; padding:2px;")
            lbl.setWordWrap(True)
            self._drift_vbox.addWidget(lbl)

        if not alerts:
            lbl = QLabel("No drift detected")
            lbl.setStyleSheet(f"color:{ACCENT_GREEN}; font-size:11px;")
            self._drift_vbox.addWidget(lbl)

    def _update_variant_table(self, stats: dict):
        self._variant_table.setRowCount(len(stats))
        for row, (variant, data) in enumerate(sorted(
            stats.items(), key=lambda x: x[1]["win_rate"], reverse=True
        )):
            wr = data["win_rate"]
            total = data["total_evaluations"]
            color = ACCENT_GREEN if wr > 0.5 else ACCENT_RED
            self._variant_table.setItem(row, 0, QTableWidgetItem(variant))
            item = QTableWidgetItem(f"{wr:.0%}")
            item.setForeground(QColor(color))
            self._variant_table.setItem(row, 1, item)
            self._variant_table.setItem(row, 2, QTableWidgetItem("—"))
            self._variant_table.setItem(row, 3, QTableWidgetItem(str(total)))

    def _table_style(self) -> str:
        return (
            "QTableWidget { background:#0A0A12; color:#C0C0E0; "
            "gridline-color:#2A2A4A; border:none; font-size:11px; }"
            "QHeaderView::section { background:#16162A; color:#8888AA; border:none; padding:4px; }"
        )
