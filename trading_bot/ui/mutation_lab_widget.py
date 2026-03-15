"""
Strategy Mutation Lab Widget
============================
UI panel for the automated strategy evolution engine.

Shortcut: Shift+Alt+8 (Layer 8 – Evolution)
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
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


class MutationLabWidget(QWidget):
    """
    Strategy Mutation Lab control panel.

    Shows:
    - Evolution status (generation, population)
    - Fitness leaderboard
    - Generation history chart
    - Promoted strategies
    - Configuration controls

    Keyboard shortcut: Shift+Alt+8
    """

    def __init__(self, lab=None, parent=None):
        super().__init__(parent)
        self._lab = lab
        self._setup_ui()
        self._setup_timer()
        self._setup_shortcut()

    def _setup_shortcut(self):
        sc = QShortcut(QKeySequence("Shift+Alt+8"), self)
        sc.activated.connect(self.show)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Strategy Mutation Lab  ·  Automated Evolution")
        title.setStyleSheet(f"color:{ACCENT_BLUE}; font-size:16px; font-weight:bold;")
        hdr.addWidget(title)
        hdr.addStretch()

        self._status_lbl = QLabel("● IDLE")
        self._status_lbl.setStyleSheet(f"color:{TEXT_MUTED}; font-weight:bold;")
        hdr.addWidget(self._status_lbl)

        self._toggle_btn = QPushButton("Start Evolution")
        self._toggle_btn.setFixedWidth(130)
        self._toggle_btn.setStyleSheet(
            f"background:{ACCENT_GREEN}; color:#000; font-weight:bold; "
            f"border-radius:4px; padding:4px;"
        )
        self._toggle_btn.clicked.connect(self._toggle_lab)
        hdr.addWidget(self._toggle_btn)
        root.addLayout(hdr)

        # ── Stats row ─────────────────────────────────────────────────────────
        stats = QHBoxLayout()
        self._gen_card = self._metric_card("Generation", "0", ACCENT_BLUE)
        self._pop_card = self._metric_card("Population", "0", ACCENT_BLUE)
        self._best_card = self._metric_card("Best Fitness", "0.000", ACCENT_GREEN)
        self._promoted_card = self._metric_card("Promoted", "0", "#FFA500")
        self._failed_card = self._metric_card("Eliminated", "0", ACCENT_RED)
        for c in (self._gen_card, self._pop_card, self._best_card,
                  self._promoted_card, self._failed_card):
            stats.addWidget(c)
        root.addLayout(stats)

        # ── Config bar ────────────────────────────────────────────────────────
        cfg_grp = QGroupBox("Evolution Parameters")
        cfg_grp.setStyleSheet(f"QGroupBox {{ color:{ACCENT_BLUE}; }}")
        cfg_lay = QHBoxLayout(cfg_grp)

        cfg_lay.addWidget(QLabel("Population:"))
        self._pop_spin = QSpinBox()
        self._pop_spin.setRange(5, 100)
        self._pop_spin.setValue(20)
        self._pop_spin.setFixedWidth(60)
        cfg_lay.addWidget(self._pop_spin)

        cfg_lay.addWidget(QLabel("Mutation Rate:"))
        self._mut_slider = QSlider(Qt.Orientation.Horizontal)
        self._mut_slider.setRange(5, 50)
        self._mut_slider.setValue(20)
        self._mut_slider.setFixedWidth(100)
        self._mut_rate_lbl = QLabel("20%")
        self._mut_slider.valueChanged.connect(
            lambda v: self._mut_rate_lbl.setText(f"{v}%")
        )
        cfg_lay.addWidget(self._mut_slider)
        cfg_lay.addWidget(self._mut_rate_lbl)

        cfg_lay.addWidget(QLabel("Max DD Gate:"))
        self._dd_spin = QSpinBox()
        self._dd_spin.setRange(5, 50)
        self._dd_spin.setValue(20)
        self._dd_spin.setSuffix("%")
        self._dd_spin.setFixedWidth(70)
        cfg_lay.addWidget(self._dd_spin)

        cfg_lay.addStretch()
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(70)
        apply_btn.clicked.connect(self._apply_config)
        apply_btn.setStyleSheet(
            f"background:{ACCENT_BLUE}; color:#000; border-radius:4px; padding:3px;"
        )
        cfg_lay.addWidget(apply_btn)
        root.addWidget(cfg_grp)

        # ── Splitter: leaderboard | generation history ─────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Leaderboard
        lb_grp = QGroupBox("Fitness Leaderboard (Current Population)")
        lb_grp.setStyleSheet(f"QGroupBox {{ color:{ACCENT_BLUE}; }}")
        lb_lay = QVBoxLayout(lb_grp)
        self._leader_table = QTableWidget(0, 5)
        self._leader_table.setHorizontalHeaderLabels(
            ["Variant ID", "Fitness", "Sharpe", "Max DD", "Status"]
        )
        self._leader_table.horizontalHeader().setStretchLastSection(True)
        self._leader_table.setStyleSheet(self._table_style())
        lb_lay.addWidget(self._leader_table)
        splitter.addWidget(lb_grp)

        # Generation history
        gen_grp = QGroupBox("Generation History")
        gen_grp.setStyleSheet(f"QGroupBox {{ color:{ACCENT_BLUE}; }}")
        gen_lay = QVBoxLayout(gen_grp)
        self._gen_table = QTableWidget(0, 5)
        self._gen_table.setHorizontalHeaderLabels(
            ["Gen", "Best Fitness", "Avg Fitness", "Promotions", "Duration"]
        )
        self._gen_table.horizontalHeader().setStretchLastSection(True)
        self._gen_table.setStyleSheet(self._table_style())
        gen_lay.addWidget(self._gen_table)
        splitter.addWidget(gen_grp)

        splitter.setSizes([500, 450])
        root.addWidget(splitter, stretch=1)

        # ── Description ───────────────────────────────────────────────────────
        desc = QLabel(
            "The Mutation Lab evolves strategy parameter sets using genetic algorithms. "
            "Each generation mutates and crossbreeds parameters, evaluates via backtest + "
            "walk-forward + regime tests, eliminates underperformers, and promotes survivors "
            "to the Strategy Registry automatically."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        root.addWidget(desc)

    def _metric_card(self, label: str, value: str, color: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("background:#12121E; border-radius:6px; border:1px solid #2A2A4A;")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 6, 10, 6)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{TEXT_MUTED}; font-size:10px;")
        val = QLabel(value)
        val.setStyleSheet(f"color:{color}; font-size:17px; font-weight:bold;")
        val.setObjectName(f"mlm_{label.replace(' ', '_')}")
        lay.addWidget(lbl)
        lay.addWidget(val)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return frame

    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _toggle_lab(self):
        if not self._lab:
            return
        if self._lab._running:
            self._lab.stop()
            self._toggle_btn.setText("Start Evolution")
            self._toggle_btn.setStyleSheet(
                f"background:{ACCENT_GREEN}; color:#000; font-weight:bold; "
                f"border-radius:4px; padding:4px;"
            )
            self._status_lbl.setText("● IDLE")
            self._status_lbl.setStyleSheet(f"color:{TEXT_MUTED}; font-weight:bold;")
        else:
            self._lab.start("default_strategy")
            self._toggle_btn.setText("Stop Evolution")
            self._toggle_btn.setStyleSheet(
                f"background:{ACCENT_RED}; color:#FFF; font-weight:bold; "
                f"border-radius:4px; padding:4px;"
            )
            self._status_lbl.setText("● EVOLVING")
            self._status_lbl.setStyleSheet(f"color:{ACCENT_GREEN}; font-weight:bold;")

    def _apply_config(self):
        if not self._lab:
            return
        self._lab.configure(
            population_size=self._pop_spin.value(),
            mutation_rate=self._mut_slider.value() / 100,
            max_drawdown_pct=float(self._dd_spin.value()),
        )

    def _refresh(self):
        if not self._lab:
            return

        stats = self._lab.get_stats()
        self._set_val("Generation", str(stats.get("generations", 0)))
        self._set_val("Population", str(stats.get("population_size", 0)))
        self._set_val("Promoted", str(stats.get("promoted", 0)))
        self._set_val("Eliminated", str(stats.get("failed", 0)))

        # Leaderboard
        population = self._lab.get_population()
        passed = [v for v in population if v.status in ("passed", "promoted", "evaluating")]
        passed.sort(key=lambda v: v.fitness_score or 0, reverse=True)
        self._leader_table.setRowCount(len(passed))
        best_fit = 0.0
        for row, v in enumerate(passed):
            fit = v.fitness_score or 0.0
            if row == 0:
                best_fit = fit
            color = ACCENT_GREEN if fit > 0.6 else ("#FFA500" if fit > 0.4 else ACCENT_RED)
            status_color = {"promoted": ACCENT_GREEN, "passed": ACCENT_BLUE,
                           "evaluating": "#FFA500"}.get(v.status, TEXT_MUTED)
            self._leader_table.setItem(row, 0, QTableWidgetItem(v.variant_id))
            fit_item = QTableWidgetItem(f"{fit:.4f}")
            fit_item.setForeground(QColor(color))
            self._leader_table.setItem(row, 1, fit_item)
            self._leader_table.setItem(row, 2, QTableWidgetItem(
                f"{v.sharpe_ratio:.2f}" if v.sharpe_ratio is not None else "—"
            ))
            self._leader_table.setItem(row, 3, QTableWidgetItem(
                f"{v.max_drawdown_pct:.1f}%" if v.max_drawdown_pct is not None else "—"
            ))
            status_item = QTableWidgetItem(v.status.upper())
            status_item.setForeground(QColor(status_color))
            self._leader_table.setItem(row, 4, status_item)

        self._set_val("Best Fitness", f"{best_fit:.4f}")

        # Generation history
        history = self._lab.get_generation_history()
        self._gen_table.setRowCount(len(history))
        for row, report in enumerate(reversed(history[-20:])):
            self._gen_table.setItem(row, 0, QTableWidgetItem(str(report.generation)))
            bf_item = QTableWidgetItem(f"{report.best_fitness:.4f}")
            bf_item.setForeground(QColor(ACCENT_GREEN))
            self._gen_table.setItem(row, 1, bf_item)
            self._gen_table.setItem(row, 2, QTableWidgetItem(f"{report.avg_fitness:.4f}"))
            promo_item = QTableWidgetItem(str(report.promotions))
            if report.promotions > 0:
                promo_item.setForeground(QColor("#FFA500"))
            self._gen_table.setItem(row, 3, promo_item)
            self._gen_table.setItem(row, 4, QTableWidgetItem(f"{report.duration_seconds:.1f}s"))

        if self._lab._running:
            self._status_lbl.setText(
                f"● GEN {stats.get('generations', 0)}/{self._lab._config.max_generations}"
            )
            self._status_lbl.setStyleSheet(f"color:{ACCENT_GREEN}; font-weight:bold;")

    def _set_val(self, label: str, value: str):
        key = f"mlm_{label.replace(' ', '_')}"
        lbl = self.findChild(QLabel, key)
        if lbl:
            lbl.setText(value)

    def _table_style(self) -> str:
        return (
            "QTableWidget { background:#0A0A12; color:#C0C0E0; "
            "gridline-color:#2A2A4A; border:none; font-size:11px; }"
            "QHeaderView::section { background:#16162A; color:#8888AA; border:none; padding:4px; }"
        )
