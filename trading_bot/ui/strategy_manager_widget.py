"""
Strategy Manager UI Widget.

Shows all available strategies, their performance scores, the current
regime-based ML selection, and lets the user override manually.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QProgressBar, QCheckBox,
)

from ui.styles import ACCENT, ACCENT2, GREEN, RED, YELLOW, PURPLE,\
    BG2, BG3, BG4, BORDER, FG0, FG1, FG2


STRATEGY_DESCRIPTIONS = {
    "trend_follow": "Ride directional trends using EMA crossover + MACD",
    "mean_revert":  "Buy dips / sell rips inside established range",
    "ping_pong":    "Tight buy/sell between channel high and low",
    "momentum":     "Breakout + volume surge confirmation",
    "sentiment":    "News/social sentiment-driven contrarian trades",
    "ml_pure":      "Pure ML ensemble signal with no additional overlay",
}

STRATEGY_BEST_REGIME = {
    "trend_follow": "TRENDING",
    "mean_revert":  "RANGING",
    "ping_pong":    "RANGING / VOLATILE",
    "momentum":     "VOLATILE / TRENDING",
    "sentiment":    "ANY",
    "ml_pure":      "ANY",
}


class StrategyManagerWidget(QWidget):
    """Live strategy manager panel."""

    _strategy_changed = pyqtSignal()

    def __init__(self, strategy_manager=None, parent=None) -> None:
        super().__init__(parent)
        self._mgr = strategy_manager
        self._setup_ui()
        self._connect_backend()
        self._strategy_changed.connect(self._refresh)
        QTimer(self, interval=5000, timeout=self._refresh).start()
        QTimer.singleShot(1000, self._refresh)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("🧠  ML STRATEGY SELECTOR")
        title.setStyleSheet(
            f"color:{ACCENT}; font-size:13px; font-weight:700; letter-spacing:1px;"
        )
        hdr.addWidget(title)
        hdr.addStretch()
        self.active_lbl = QLabel("Active: —")
        self.active_lbl.setStyleSheet(
            f"color:{GREEN}; font-size:12px; font-weight:700; font-family:monospace;"
        )
        hdr.addWidget(self.active_lbl)
        root.addLayout(hdr)

        # Info
        info = QLabel(
            "The ML strategy selector scores all strategies using win rate, R:R ratio, "
            "regime fit, and recent momentum — then automatically activates the best match."
        )
        info.setStyleSheet(f"color:{FG2}; font-size:11px;")
        info.setWordWrap(True)
        root.addWidget(info)

        # Manual override row
        ovr_grp = QGroupBox("Manual Override")
        ovr_grp.setStyleSheet(
            f"QGroupBox {{ color:{ACCENT}; font-weight:700; border:1px solid {BORDER}; "
            f"border-radius:4px; margin-top:6px; padding-top:8px; }}"
        )
        ovr_lay = QHBoxLayout(ovr_grp)
        self.override_check = QCheckBox("Override auto-selection:")
        self.override_check.setStyleSheet(f"color:{FG1}; font-size:11px;")
        self.override_check.toggled.connect(self._on_override_toggled)
        ovr_lay.addWidget(self.override_check)
        self.override_combo = QComboBox()
        self.override_combo.addItems(list(STRATEGY_DESCRIPTIONS.keys()))
        self.override_combo.setEnabled(False)
        self.override_combo.setFixedWidth(140)
        self.override_combo.currentTextChanged.connect(self._on_override_changed)
        ovr_lay.addWidget(self.override_combo)
        ovr_lay.addStretch()
        self.regime_lbl = QLabel("Regime: —")
        self.regime_lbl.setStyleSheet(
            f"color:{ACCENT}; font-size:12px; font-weight:700; font-family:monospace;"
        )
        ovr_lay.addWidget(self.regime_lbl)
        root.addWidget(ovr_grp)

        # Strategy scores table
        score_grp = QGroupBox("Strategy Scores  (ML auto-ranks these)")
        score_grp.setStyleSheet(
            f"QGroupBox {{ color:{ACCENT}; font-weight:700; border:1px solid {BORDER}; "
            f"border-radius:4px; margin-top:6px; padding-top:8px; }}"
        )
        sg_lay = QVBoxLayout(score_grp)
        self.score_table = QTableWidget(0, 8)
        self.score_table.setHorizontalHeaderLabels([
            "Strategy", "Score", "Regime Fit", "Win Rate", "Avg R:R",
            "Recent Momentum", "Best Regime", "Description",
        ])
        self.score_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.score_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.score_table.setAlternatingRowColors(True)
        self.score_table.setStyleSheet(
            f"QTableWidget {{ background:{BG2}; color:{FG1}; border:none; font-size:11px; }}"
            f"QHeaderView::section {{ background:{BG3}; color:{FG2}; border:none; padding:4px; }}"
        )
        sg_lay.addWidget(self.score_table)
        root.addWidget(score_grp)

        # Per-strategy performance stats
        perf_grp = QGroupBox("Strategy Performance")
        perf_grp.setStyleSheet(
            f"QGroupBox {{ color:{ACCENT}; font-weight:700; border:1px solid {BORDER}; "
            f"border-radius:4px; margin-top:6px; padding-top:8px; }}"
        )
        pg_lay = QVBoxLayout(perf_grp)
        self.perf_table = QTableWidget(0, 6)
        self.perf_table.setHorizontalHeaderLabels([
            "Strategy", "Trades", "Wins", "Losses", "Win Rate", "Total P&L",
        ])
        self.perf_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.perf_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.perf_table.setAlternatingRowColors(True)
        self.perf_table.setStyleSheet(
            f"QTableWidget {{ background:{BG2}; color:{FG1}; border:none; font-size:11px; }}"
            f"QHeaderView::section {{ background:{BG3}; color:{FG2}; border:none; padding:4px; }}"
        )
        pg_lay.addWidget(self.perf_table)
        root.addWidget(perf_grp, 1)

        # Force evaluate button
        eval_btn = QPushButton("⟳  Force Re-Evaluate Now")
        eval_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{ACCENT}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:5px 14px; font-size:11px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{BG4}; }}"
        )
        eval_btn.clicked.connect(self._on_force_eval)
        root.addWidget(eval_btn)

    # ── Backend wiring ─────────────────────────────────────────────────────────

    def _connect_backend(self) -> None:
        if not self._mgr:
            return
        try:
            self._mgr.on_strategy_changed(lambda sel: self._strategy_changed.emit())
        except Exception:
            pass

    # ── Refresh ────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if not self._mgr:
            return

        active = self._mgr.active_strategy
        self.active_lbl.setText(f"Active: {active.upper()}")

        sel = self._mgr.last_selection
        if sel:
            regime_cols = {
                "TRENDING_UP": GREEN, "TRENDING_DOWN": RED,
                "RANGING": ACCENT, "VOLATILE": YELLOW, "UNKNOWN": FG2,
            }
            col = regime_cols.get(sel.regime, FG2)
            self.regime_lbl.setText(f"Regime: {sel.regime}")
            self.regime_lbl.setStyleSheet(
                f"color:{col}; font-size:12px; font-weight:700; font-family:monospace;"
            )
            scores = sorted(sel.scores, key=lambda s: -s.score)
        else:
            scores = []

        # Score table
        self.score_table.setRowCount(len(scores))
        for r, s in enumerate(scores):
            is_active = s.name == active
            vals = [
                s.name.replace("_", " ").upper(),
                f"{s.score:.3f}",
                f"{s.regime_fit:.0%}",
                f"{s.win_rate:.0%}",
                f"{s.avg_rr:.2f}×",
                f"{s.recent_momentum:.0%}",
                STRATEGY_BEST_REGIME.get(s.name, "—"),
                STRATEGY_DESCRIPTIONS.get(s.name, ""),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if is_active:
                    item.setBackground(QColor(BG4))
                    item.setForeground(QColor(GREEN))
                elif c == 1:  # Score column
                    score_col = GREEN if s.score >= 0.65 else YELLOW if s.score >= 0.5 else FG2
                    item.setForeground(QColor(score_col))
                self.score_table.setItem(r, c, item)

        # Performance table
        stats = self._mgr.all_stats
        rows = sorted(stats.values(), key=lambda s: -s.total_trades)
        self.perf_table.setRowCount(len(rows))
        for r, st in enumerate(rows):
            wr_col = GREEN if st.win_rate >= 0.5 else RED
            pnl_col = GREEN if st.total_pnl >= 0 else RED
            is_active = st.name == active
            vals = [
                st.name.replace("_", " ").upper(),
                str(st.total_trades),
                str(st.wins),
                str(st.losses),
                f"{st.win_rate:.0%}",
                f"${st.total_pnl:+,.4f}",
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if is_active:
                    item.setBackground(QColor(BG4))
                if c == 4:
                    item.setForeground(QColor(wr_col))
                elif c == 5:
                    item.setForeground(QColor(pnl_col))
                self.perf_table.setItem(r, c, item)

    # ── Controls ───────────────────────────────────────────────────────────────

    def _on_override_toggled(self, checked: bool) -> None:
        self.override_combo.setEnabled(checked)
        if not checked and self._mgr:
            self._mgr.set_manual_override(None)
        elif checked and self._mgr:
            self._mgr.set_manual_override(self.override_combo.currentText())

    def _on_override_changed(self, strategy: str) -> None:
        if self.override_check.isChecked() and self._mgr:
            try:
                self._mgr.set_manual_override(strategy)
            except Exception:
                pass

    def _on_force_eval(self) -> None:
        if self._mgr:
            try:
                self._mgr.evaluate_now()
                self._refresh()
            except Exception:
                pass
