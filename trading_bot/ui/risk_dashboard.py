"""
Live Risk Dashboard UI.

Real-time visual risk monitoring with:
  - Circuit breaker status (large coloured banner)
  - Market regime indicator with description
  - Daily P&L vs limit gauges
  - Current drawdown meter
  - Rolling win rate chart
  - Monte Carlo equity forecast (P10/P50/P90 paths)
  - Source attribution table (which signals are actually making money)
  - Ensemble weight display (live adaptive weights)
  - Walk-forward validation result badge

Refreshes every 5 seconds from dynamic risk manager and trade journal.
"""

from __future__ import annotations

import time
from typing import Optional

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QProgressBar, QSplitter, QGridLayout, QPushButton, QComboBox,
)

from ui.styles import ACCENT, GREEN, RED, YELLOW, BG2, BG3, BG4, BORDER, FG0, FG1, FG2

pg.setConfigOption("background", BG2)
pg.setConfigOption("foreground", FG1)

ORANGE = "#FF9800"
PURPLE = "#9C27B0"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _label(text: str, colour: str = FG0, size: int = 11,
           bold: bool = False, parent=None) -> QLabel:
    lbl = QLabel(text, parent)
    weight = "700" if bold else "400"
    lbl.setStyleSheet(f"color:{colour}; font-size:{size}px; font-weight:{weight};")
    return lbl


def _card(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    grp = QGroupBox(title)
    grp.setStyleSheet(
        f"QGroupBox {{ background:{BG3}; border:1px solid {BORDER}; border-radius:6px; "
        f"color:{ACCENT}; font-size:11px; font-weight:700; padding-top:8px; }}"
        f"QGroupBox::title {{ subcontrol-origin:margin; left:10px; }}"
    )
    lay = QVBoxLayout(grp)
    lay.setContentsMargins(8, 14, 8, 8)
    lay.setSpacing(4)
    return grp, lay


# ── Risk dashboard ────────────────────────────────────────────────────────────

class RiskDashboard(QWidget):
    """
    Central risk monitoring panel.
    Pass in the service objects; it polls them every 5 seconds.
    """

    _opt_done = pyqtSignal()

    def __init__(
        self,
        dynamic_risk=None,
        regime_detector=None,
        ensemble=None,
        trade_journal=None,
        monte_carlo=None,
        walk_forward=None,
        engine=None,
        port_opt=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._drm     = dynamic_risk
        self._regime  = regime_detector
        self._ens     = ensemble
        self._journal = trade_journal
        self._mc      = monte_carlo
        self._wf      = walk_forward
        self._engine  = engine
        self._port_opt = port_opt
        self._opt_done.connect(self._on_opt_done)
        self._setup_ui()
        self._timer  = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(5000)
        self._refresh()

    # ── UI setup ───────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Header ───────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = _label("⚡ LIVE RISK DASHBOARD", ACCENT, 13, bold=True)
        hdr.addWidget(title)
        hdr.addStretch()
        self.last_update_lbl = _label("Updated: —", FG2, 10)
        hdr.addWidget(self.last_update_lbl)
        layout.addLayout(hdr)

        # ── Circuit breaker banner ────────────────────────────────────
        self.circuit_banner = QLabel("TRADING ACTIVE")
        self.circuit_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.circuit_banner.setFixedHeight(36)
        self.circuit_banner.setStyleSheet(
            f"background:{GREEN}; color:#000; font-size:13px; font-weight:700; border-radius:4px;"
        )
        layout.addWidget(self.circuit_banner)

        # ── Top row: regime + daily P&L ──────────────────────────────
        top_row = QHBoxLayout()

        # Regime card
        regime_grp, regime_lay = _card("Market Regime")
        self.regime_lbl = _label("UNKNOWN", YELLOW, 20, bold=True)
        self.regime_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        regime_lay.addWidget(self.regime_lbl)
        self.regime_desc = _label("Detecting…", FG1, 10)
        self.regime_desc.setWordWrap(True)
        regime_lay.addWidget(self.regime_desc)
        self.regime_conf = _label("Confidence: —", FG2, 10)
        regime_lay.addWidget(self.regime_conf)
        top_row.addWidget(regime_grp)

        # Daily P&L card
        pnl_grp, pnl_lay = _card("Daily P&L")
        self.pnl_lbl = _label("$0.00", FG0, 22, bold=True)
        self.pnl_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pnl_lay.addWidget(self.pnl_lbl)
        self.pnl_bar = QProgressBar()
        self.pnl_bar.setRange(0, 100)
        self.pnl_bar.setValue(0)
        self.pnl_bar.setTextVisible(False)
        self.pnl_bar.setFixedHeight(10)
        pnl_lay.addWidget(self.pnl_bar)
        self.pnl_limit_lbl = _label("Daily loss limit: 3%", FG2, 10)
        pnl_lay.addWidget(self.pnl_limit_lbl)
        top_row.addWidget(pnl_grp)

        # Win rate card
        wr_grp, wr_lay = _card("Win Rate (Rolling 20)")
        self.wr_lbl = _label("—%", FG0, 22, bold=True)
        self.wr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wr_lay.addWidget(self.wr_lbl)
        self.wr_bar = QProgressBar()
        self.wr_bar.setRange(0, 100)
        self.wr_bar.setValue(50)
        self.wr_bar.setTextVisible(False)
        self.wr_bar.setFixedHeight(10)
        wr_lay.addWidget(self.wr_bar)
        self.consec_lbl = _label("Consecutive losses: 0", FG2, 10)
        wr_lay.addWidget(self.consec_lbl)
        top_row.addWidget(wr_grp)

        # Drawdown card
        dd_grp, dd_lay = _card("Current Drawdown")
        self.dd_lbl = _label("0.0%", GREEN, 22, bold=True)
        self.dd_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dd_lay.addWidget(self.dd_lbl)
        self.dd_bar = QProgressBar()
        self.dd_bar.setRange(0, 20)
        self.dd_bar.setValue(0)
        self.dd_bar.setTextVisible(False)
        self.dd_bar.setFixedHeight(10)
        dd_lay.addWidget(self.dd_bar)
        self.dd_peak_lbl = _label("Peak: —", FG2, 10)
        dd_lay.addWidget(self.dd_peak_lbl)
        top_row.addWidget(dd_grp)

        layout.addLayout(top_row)

        # ── Middle: MC forecast + attribution ─────────────────────────
        mid_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Monte Carlo equity forecast
        mc_grp, mc_lay = _card("Monte Carlo Equity Forecast (5,000 paths)")
        self.mc_plot = pg.PlotWidget()
        self.mc_plot.showGrid(x=True, y=True, alpha=0.15)
        self.mc_plot.setLabel("left", "Capital $")
        self.mc_plot.setLabel("bottom", "Trades Forward")
        mc_lay.addWidget(self.mc_plot)
        self.mc_ror_lbl = _label("Risk of Ruin: —", FG2, 10)
        mc_lay.addWidget(self.mc_ror_lbl)
        self.mc_max_pos_lbl = _label("Safe max position: —", FG2, 10)
        mc_lay.addWidget(self.mc_max_pos_lbl)
        mid_splitter.addWidget(mc_grp)

        # Right side: attribution + ensemble weights
        right_widget = QWidget()
        right_lay = QVBoxLayout(right_widget)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)

        # Source attribution table
        attr_grp, attr_lay = _card("Signal Source Attribution")
        self.attr_tbl = QTableWidget(0, 4)
        self.attr_tbl.setHorizontalHeaderLabels(["Source", "Wins", "Losses", "Win Rate"])
        self.attr_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.attr_tbl.verticalHeader().setVisible(False)
        self.attr_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.attr_tbl.setMaximumHeight(180)
        attr_lay.addWidget(self.attr_tbl)
        right_lay.addWidget(attr_grp)

        # Ensemble weights
        wt_grp, wt_lay = _card("Ensemble Adaptive Weights")
        self.weights_tbl = QTableWidget(0, 2)
        self.weights_tbl.setHorizontalHeaderLabels(["Model", "Weight"])
        self.weights_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.weights_tbl.verticalHeader().setVisible(False)
        self.weights_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.weights_tbl.setMaximumHeight(180)
        wt_lay.addWidget(self.weights_tbl)
        right_lay.addWidget(wt_grp)

        # Walk-forward badge
        wf_grp, wf_lay = _card("Walk-Forward Validation")
        self.wf_lbl = _label("Not yet validated", YELLOW, 12, bold=True)
        self.wf_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wf_lay.addWidget(self.wf_lbl)
        self.wf_detail = _label("", FG2, 10)
        self.wf_detail.setWordWrap(True)
        wf_lay.addWidget(self.wf_detail)
        right_lay.addWidget(wf_grp)

        mid_splitter.addWidget(right_widget)
        mid_splitter.setSizes([550, 350])
        layout.addWidget(mid_splitter, 1)

        # ── Portfolio Optimiser panel ──────────────────────────────────
        po_grp, po_lay = _card("Portfolio Optimiser (Layer 4 – Research & Quant)")
        po_hdr = QHBoxLayout()

        self._po_method_combo = QComboBox()
        self._po_method_combo.addItems(["max_sharpe", "risk_parity", "kelly", "equal_weight"])
        self._po_method_combo.setStyleSheet(
            f"background:{BG4}; color:{FG0}; border:1px solid {BORDER}; padding:3px 8px; border-radius:3px;"
        )
        po_hdr.addWidget(_label("Method:", FG1, 10))
        po_hdr.addWidget(self._po_method_combo)

        self._po_run_btn = QPushButton("▶ Optimise")
        self._po_run_btn.setFixedHeight(26)
        self._po_run_btn.setStyleSheet(
            f"QPushButton {{ background:{ACCENT}; color:#000; font-weight:700; font-size:11px; "
            f"border:none; border-radius:3px; padding:0 12px; }}"
            f"QPushButton:hover {{ background:#00B8D9; }}"
        )
        self._po_run_btn.clicked.connect(self._run_portfolio_opt)
        po_hdr.addWidget(self._po_run_btn)
        po_hdr.addStretch()

        self._po_stats_lbl = _label("", FG1, 10)
        po_hdr.addWidget(self._po_stats_lbl)
        po_lay.addLayout(po_hdr)

        # Weights table
        self._po_table = QTableWidget(0, 4)
        self._po_table.setHorizontalHeaderLabels(["Symbol", "Weight %", "Kelly Size %", "Est. Return %"])
        self._po_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._po_table.setMaximumHeight(160)
        self._po_table.setStyleSheet(
            f"QTableWidget {{ background:{BG3}; color:{FG0}; gridline-color:{BORDER}; "
            f"selection-background-color:{BG4}; border:none; font-size:11px; }}"
            f"QHeaderView::section {{ background:{BG4}; color:{ACCENT}; border:none; "
            f"padding:4px; font-size:10px; font-weight:700; }}"
        )
        self._po_table.verticalHeader().setVisible(False)
        po_lay.addWidget(self._po_table)

        # Rebalance suggestions
        self._po_rebalance_lbl = _label("", FG2, 10)
        self._po_rebalance_lbl.setWordWrap(True)
        po_lay.addWidget(self._po_rebalance_lbl)

        layout.addWidget(po_grp)

    # ── Refresh logic ──────────────────────────────────────────────────

    def _refresh(self) -> None:
        try:
            self._refresh_circuit()
            self._refresh_regime()
            self._refresh_risk_status()
            self._refresh_attribution()
            self._refresh_weights()
            self._refresh_portfolio_opt()
            self._refresh_mc()
            self.last_update_lbl.setText(f"Updated: {time.strftime('%H:%M:%S')}")
        except Exception:
            pass

    def _refresh_circuit(self) -> None:
        if self._drm:
            broken = self._drm.circuit_broken
            reason = self._drm.circuit_reason if broken else ""
            if broken:
                self.circuit_banner.setText(f"⛔  CIRCUIT BREAKER ACTIVE  |  {reason}")
                self.circuit_banner.setStyleSheet(
                    f"background:{RED}; color:#fff; font-size:13px; font-weight:700; border-radius:4px;"
                )
            else:
                self.circuit_banner.setText("✅  TRADING ACTIVE – All systems nominal")
                self.circuit_banner.setStyleSheet(
                    f"background:#1B5E20; color:{GREEN}; font-size:13px; font-weight:700; border-radius:4px;"
                )

    def _refresh_regime(self) -> None:
        if not self._regime:
            return
        snap = self._regime.current
        regime = snap.regime.value
        colour = {
            "TRENDING_UP": GREEN, "TRENDING_DOWN": RED,
            "RANGING": YELLOW, "VOLATILE": ORANGE, "UNKNOWN": FG2,
        }.get(regime, FG2)
        self.regime_lbl.setText(regime.replace("_", " "))
        self.regime_lbl.setStyleSheet(f"color:{colour}; font-size:18px; font-weight:700;")
        try:
            from ml.regime_detector import REGIME_PARAMS, Regime
            desc = REGIME_PARAMS.get(Regime(regime), {}).get("description", "")
            self.regime_desc.setText(desc)
        except Exception:
            pass
        self.regime_conf.setText(f"Confidence: {snap.confidence:.0%}")

    def _refresh_risk_status(self) -> None:
        if not self._drm:
            return
        status = self._drm.status
        wr  = status.get("rolling_win_rate", 0.5)
        dd  = status.get("drawdown_pct", 0.0)
        cl  = status.get("consecutive_losses", 0)

        # Win rate
        self.wr_lbl.setText(f"{wr:.0%}")
        colour = GREEN if wr >= 0.55 else YELLOW if wr >= 0.40 else RED
        self.wr_lbl.setStyleSheet(f"color:{colour}; font-size:22px; font-weight:700;")
        self.wr_bar.setValue(int(wr * 100))
        self.wr_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background:{colour}; border-radius:3px; }}"
        )
        self.consec_lbl.setText(f"Consecutive losses: {cl}")
        self.consec_lbl.setStyleSheet(
            f"color:{'#fff' if cl < 3 else YELLOW if cl < 5 else RED}; font-size:10px;"
        )

        # Drawdown
        dd_pct = max(0.0, dd * 100)
        self.dd_lbl.setText(f"{dd_pct:.1f}%")
        dd_colour = GREEN if dd_pct < 5 else YELLOW if dd_pct < 12 else RED
        self.dd_lbl.setStyleSheet(f"color:{dd_colour}; font-size:22px; font-weight:700;")
        self.dd_bar.setValue(int(min(20, dd_pct)))
        self.dd_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background:{dd_colour}; border-radius:3px; }}"
        )

        # Daily P&L from journal
        if self._journal:
            try:
                summary = self._journal.daily_summary()
                pnl = summary.get("pnl", 0.0)
                self.pnl_lbl.setText(f"{'+'if pnl>=0 else ''}${pnl:,.2f}")
                pnl_colour = GREEN if pnl >= 0 else RED
                self.pnl_lbl.setStyleSheet(
                    f"color:{pnl_colour}; font-size:22px; font-weight:700;"
                )
            except Exception:
                pass

    def _refresh_attribution(self) -> None:
        if not self._journal:
            return
        try:
            attr = self._journal.source_attribution()
            self.attr_tbl.setRowCount(0)
            for src, data in sorted(attr.items(), key=lambda x: -x[1]["win_rate"]):
                row = self.attr_tbl.rowCount()
                self.attr_tbl.insertRow(row)
                wr = data["win_rate"]
                colour = GREEN if wr >= 0.55 else YELLOW if wr >= 0.45 else RED
                items = [
                    (src, FG0), (str(data["wins"]), GREEN),
                    (str(data["losses"]), RED), (f"{wr:.0%}", colour),
                ]
                for col, (txt, fg) in enumerate(items):
                    item = QTableWidgetItem(txt)
                    item.setForeground(QBrush(QColor(fg)))
                    self.attr_tbl.setItem(row, col, item)
        except Exception:
            pass

    def _refresh_weights(self) -> None:
        if not self._ens:
            return
        try:
            weights = self._ens.weights
            self.weights_tbl.setRowCount(0)
            for src, w in sorted(weights.items(), key=lambda x: -x[1]):
                row = self.weights_tbl.rowCount()
                self.weights_tbl.insertRow(row)
                bar_filled = "█" * int(w * 10)
                colour = GREEN if w >= 1.2 else YELLOW if w >= 0.8 else FG2
                for col, (txt, fg) in enumerate([(src, FG0), (f"{w:.2f}  {bar_filled}", colour)]):
                    item = QTableWidgetItem(txt)
                    item.setForeground(QBrush(QColor(fg)))
                    self.weights_tbl.setItem(row, col, item)
        except Exception:
            pass

    def _refresh_mc(self) -> None:
        if not self._journal or not self._mc:
            return
        try:
            trades = self._journal.get_closed_trades()
            if len(trades) < 10:
                return
            returns = [t.get("pnl_pct", 0) / 100 for t in trades if "pnl_pct" in t]
            mc_result = self._mc.run(returns, n_paths=500, n_periods=100)

            self.mc_plot.clear()
            x = list(range(len(mc_result.equity_p10)))
            self.mc_plot.plot(x, mc_result.equity_p10, pen=pg.mkPen(RED, width=1), name="P10")
            self.mc_plot.plot(x, mc_result.equity_p50, pen=pg.mkPen(ACCENT, width=2), name="P50")
            self.mc_plot.plot(x, mc_result.equity_p90, pen=pg.mkPen(GREEN, width=1), name="P90")
            # Fill between P10 and P90
            fill = pg.FillBetweenItem(
                self.mc_plot.plot(x, mc_result.equity_p10),
                self.mc_plot.plot(x, mc_result.equity_p90),
                brush=pg.mkBrush(255, 255, 255, 15),
            )
            self.mc_plot.addItem(fill)

            ror = mc_result.risk_of_ruin_pct
            ror_colour = GREEN if ror < 5 else YELLOW if ror < 15 else RED
            self.mc_ror_lbl.setStyleSheet(f"color:{ror_colour}; font-size:10px;")
            self.mc_ror_lbl.setText(
                f"Risk of Ruin (50% DD): {ror:.1f}% | "
                f"P50 return: {mc_result.p50_return_pct:+.1f}% | "
                f"ExpMaxDD: {mc_result.expected_max_dd_pct:.1f}%"
            )
            self.mc_max_pos_lbl.setText(
                f"Safe max position size: {mc_result.recommended_max_position_pct:.0%} | "
                f"Half-Kelly: {mc_result.current_kelly_fraction:.0%}"
            )
        except Exception:
            pass

    def update_walk_forward(self, report) -> None:
        """Call with a WalkForwardReport to update the WF badge."""
        if report is None:
            return
        colour = {"DEPLOY": GREEN, "RETRAIN": YELLOW, "UNSAFE": RED}.get(
            report.recommendation, YELLOW
        )
        self.wf_lbl.setText(f"{report.recommendation} – {report.symbol}/{report.interval}")
        self.wf_lbl.setStyleSheet(f"color:{colour}; font-size:12px; font-weight:700;")
        self.wf_detail.setText(
            f"OOS Sharpe: {report.oos_sharpe_avg:.2f} | "
            f"IS Sharpe: {report.is_sharpe_avg:.2f} | "
            f"OOS/IS ratio: {report.oos_is_ratio:.2f} | "
            f"Folds: {report.n_folds}"
        )

    # ── Portfolio Optimiser ────────────────────────────────────────────

    def _run_portfolio_opt(self) -> None:
        """Trigger a fresh optimisation run in a background thread."""
        if not self._port_opt:
            return
        method = self._po_method_combo.currentText()
        self._po_run_btn.setEnabled(False)
        self._po_run_btn.setText("Running…")

        import threading

        def _run():
            try:
                result = self._port_opt.optimise(symbols=[], method=method)
                # Cache on the optimiser so _refresh_portfolio_opt can read it
                self._port_opt._last_result = result
            except Exception:
                pass
            finally:
                self._opt_done.emit()

        threading.Thread(target=_run, daemon=True, name="port-opt-ui").start()

    def _on_opt_done(self) -> None:
        self._po_run_btn.setEnabled(True)
        self._po_run_btn.setText("▶ Optimise")
        self._refresh_portfolio_opt()

    def _refresh_portfolio_opt(self) -> None:
        """Populate the Portfolio Optimiser table from the last cached result."""
        if not self._port_opt:
            return
        result = getattr(self._port_opt, "_last_result", None)
        if result is None:
            return
        try:
            weights = result.weights
            kelly   = result.kelly_sizes
            exp_ret = result.expected_return_pct
            sharpe  = result.sharpe_ratio
            rebal   = result.rebalance_needed
            notes   = result.notes

            # Update stats label
            self._po_stats_lbl.setText(
                f"Sharpe: {sharpe:.2f}  |  E[ret]: {exp_ret:.1f}%  |  "
                f"Vol: {result.expected_volatility_pct:.1f}%  |  "
                f"Method: {result.method}"
            )

            # Fill table (sorted by weight descending)
            sorted_syms = sorted(weights, key=lambda s: -weights[s])
            self._po_table.setRowCount(len(sorted_syms))
            for row, sym in enumerate(sorted_syms):
                w   = weights[sym] * 100
                k   = kelly.get(sym, weights[sym]) * 100
                colour = GREEN if w >= 15 else YELLOW if w >= 8 else FG0

                def _item(text, col=colour):
                    it = QTableWidgetItem(text)
                    it.setForeground(QColor(col))
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    return it

                self._po_table.setItem(row, 0, _item(sym, FG0))
                self._po_table.setItem(row, 1, _item(f"{w:.1f}%"))
                self._po_table.setItem(row, 2, _item(f"{k:.1f}%"))
                self._po_table.setItem(row, 3, _item(f"{exp_ret / max(len(weights), 1):.2f}%", FG2))

            # Rebalance hint
            if rebal:
                self._po_rebalance_lbl.setText(
                    "⚡ Rebalance recommended.  " +
                    ("  ".join(notes[:3]) if notes else "")
                )
                self._po_rebalance_lbl.setStyleSheet(f"color:{YELLOW};")
            else:
                self._po_rebalance_lbl.setText("Portfolio within tolerance – no rebalance needed.")
                self._po_rebalance_lbl.setStyleSheet(f"color:{GREEN};")
        except Exception:
            pass
