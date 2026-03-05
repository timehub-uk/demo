"""
Backtest Results UI Widget.

Displays a full backtest results panel:
  - Config panel (symbol, dates, capital, strategy)
  - Progress bar
  - Equity curve chart
  - Trade log table
  - Performance metrics
  - PDF export
"""

from __future__ import annotations

import time
import threading
from typing import Optional

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QGroupBox, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QDoubleSpinBox, QDateEdit, QFrame,
    QMessageBox,
)
from PyQt6.QtCore import QDate

from ui.styles import ACCENT, GREEN, RED, YELLOW, BG2, BG3, BG4, BORDER, FG0, FG1, FG2

pg.setConfigOption("background", BG2)
pg.setConfigOption("foreground", FG1)

ORANGE = "#FF9800"


class BacktestWidget(QWidget):
    """Full backtest configuration, execution, and results panel."""

    def __init__(self, backtester=None, parent=None) -> None:
        super().__init__(parent)
        self._backtester = backtester
        self._result = None
        self._thread: Optional[threading.Thread] = None
        self._setup_ui()

    # ── UI setup ───────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("📊 BACKTESTING ENGINE")
        title.setStyleSheet(f"color:{ACCENT}; font-size:13px; font-weight:700; letter-spacing:1px;")
        hdr.addWidget(title)
        hdr.addStretch()
        self.status_lbl = QLabel("Status: IDLE")
        self.status_lbl.setStyleSheet(f"color:{YELLOW}; font-size:12px; font-weight:600;")
        hdr.addWidget(self.status_lbl)
        layout.addLayout(hdr)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: config + metrics ─────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 4, 0)
        ll.setSpacing(8)

        # Config
        cfg_grp = QGroupBox("Backtest Configuration")
        cgl = QVBoxLayout(cfg_grp)

        sym_row = QHBoxLayout()
        sym_row.addWidget(QLabel("Symbol:"))
        self.symbol_combo = QComboBox()
        self.symbol_combo.setEditable(True)
        for sym in ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT"]:
            self.symbol_combo.addItem(sym)
        sym_row.addWidget(self.symbol_combo)
        sym_row.addWidget(QLabel("Interval:"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["1m","5m","15m","1h","4h","1d"])
        self.interval_combo.setCurrentText("1h")
        sym_row.addWidget(self.interval_combo)
        cgl.addLayout(sym_row)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Start:"))
        self.start_date = QDateEdit()
        self.start_date.setDate(QDate.currentDate().addYears(-1))
        self.start_date.setCalendarPopup(True)
        date_row.addWidget(self.start_date)
        date_row.addWidget(QLabel("End:"))
        self.end_date = QDateEdit()
        self.end_date.setDate(QDate.currentDate())
        self.end_date.setCalendarPopup(True)
        date_row.addWidget(self.end_date)
        cgl.addLayout(date_row)

        cap_row = QHBoxLayout()
        cap_row.addWidget(QLabel("Initial capital $:"))
        self.capital_spin = QDoubleSpinBox()
        self.capital_spin.setRange(100, 10_000_000)
        self.capital_spin.setValue(10_000)
        self.capital_spin.setSingleStep(1000)
        cap_row.addWidget(self.capital_spin)
        cgl.addLayout(cap_row)

        risk_row = QHBoxLayout()
        risk_row.addWidget(QLabel("SL %:"))
        self.sl_spin = QDoubleSpinBox()
        self.sl_spin.setRange(0.1, 20)
        self.sl_spin.setValue(2.0)
        risk_row.addWidget(self.sl_spin)
        risk_row.addWidget(QLabel("TP %:"))
        self.tp_spin = QDoubleSpinBox()
        self.tp_spin.setRange(0.1, 50)
        self.tp_spin.setValue(4.0)
        risk_row.addWidget(self.tp_spin)
        risk_row.addWidget(QLabel("Confidence:"))
        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.5, 0.99)
        self.conf_spin.setValue(0.60)
        self.conf_spin.setSingleStep(0.05)
        risk_row.addWidget(self.conf_spin)
        cgl.addLayout(risk_row)

        # Model selector
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["Per-Token Model", "Universal LSTM", "Demo (random)"])
        model_row.addWidget(self.model_combo)
        cgl.addLayout(model_row)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("▶ Run Backtest")
        self.run_btn.setObjectName("btn_buy")
        self.run_btn.clicked.connect(self._run_backtest)
        btn_row.addWidget(self.run_btn)
        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setObjectName("btn_cancel")
        self.stop_btn.clicked.connect(self._stop_backtest)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.stop_btn)
        self.export_btn = QPushButton("📄 Export PDF")
        self.export_btn.setObjectName("btn_primary")
        self.export_btn.clicked.connect(self._export_pdf)
        self.export_btn.setEnabled(False)
        btn_row.addWidget(self.export_btn)
        cgl.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        cgl.addWidget(self.progress_bar)
        ll.addWidget(cfg_grp)

        # Metrics
        metrics_grp = QGroupBox("Performance Metrics")
        mgl = QVBoxLayout(metrics_grp)
        self.metrics_tbl = QTableWidget(12, 2)
        self.metrics_tbl.setHorizontalHeaderLabels(["Metric", "Value"])
        self.metrics_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.metrics_tbl.verticalHeader().setVisible(False)
        self.metrics_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.metrics_tbl.setMaximumHeight(290)
        for i, name in enumerate(["Total Return","CAGR","Sharpe Ratio","Sortino Ratio",
                                    "Max Drawdown","Calmar Ratio","Win Rate","Profit Factor",
                                    "Total Trades","Avg Win %","Avg Loss %","Final Capital"]):
            self.metrics_tbl.setItem(i, 0, QTableWidgetItem(name))
            self.metrics_tbl.setItem(i, 1, QTableWidgetItem("—"))
        mgl.addWidget(self.metrics_tbl)
        ll.addWidget(metrics_grp)

        ll.addStretch()
        splitter.addWidget(left)

        # ── Right: charts + trade log ──────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)
        rl.setSpacing(6)

        # Equity chart
        eq_title = QLabel("Equity Curve")
        eq_title.setStyleSheet(f"color:{FG1}; font-size:11px; font-weight:700;")
        rl.addWidget(eq_title)

        self.equity_plot = pg.PlotWidget()
        self.equity_plot.setLabel("left", "Capital $")
        self.equity_plot.setLabel("bottom", "Bar")
        self.equity_plot.showGrid(x=True, y=True, alpha=0.15)
        rl.addWidget(self.equity_plot, 2)

        # Drawdown chart
        dd_title = QLabel("Drawdown")
        dd_title.setStyleSheet(f"color:{RED}; font-size:11px; font-weight:700;")
        rl.addWidget(dd_title)

        self.dd_plot = pg.PlotWidget()
        self.dd_plot.setLabel("left", "DD %")
        self.dd_plot.showGrid(x=True, y=True, alpha=0.15)
        rl.addWidget(self.dd_plot, 1)

        # Trade log
        trade_title = QLabel("Trade Log")
        trade_title.setStyleSheet(f"color:{FG1}; font-size:11px; font-weight:700;")
        rl.addWidget(trade_title)

        self.trade_tbl = QTableWidget(0, 7)
        self.trade_tbl.setHorizontalHeaderLabels(
            ["Symbol","Direction","Entry Price","Exit Price","Qty","P&L","Exit Reason"])
        self.trade_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.trade_tbl.horizontalHeader().setStretchLastSection(True)
        self.trade_tbl.verticalHeader().setVisible(False)
        self.trade_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        rl.addWidget(self.trade_tbl, 2)

        splitter.addWidget(right)
        splitter.setSizes([350, 700])
        layout.addWidget(splitter, 1)

    # ── Backtest control ───────────────────────────────────────────────
    def _run_backtest(self) -> None:
        if not self._backtester:
            QMessageBox.warning(self, "No Backtester", "Backtester service not connected.")
            return

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.export_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_lbl.setText("Status: RUNNING")
        self.status_lbl.setStyleSheet(f"color:{GREEN}; font-size:12px; font-weight:600;")
        self.trade_tbl.setRowCount(0)
        self.equity_plot.clear()
        self.dd_plot.clear()
        self._reset_metrics()

        from ml.backtester import BacktestConfig
        use_per_token = self.model_combo.currentIndex() == 0
        config = BacktestConfig(
            symbol=self.symbol_combo.currentText().upper().strip(),
            interval=self.interval_combo.currentText(),
            start_date=self.start_date.date().toString("yyyy-MM-dd"),
            end_date=self.end_date.date().toString("yyyy-MM-dd"),
            initial_capital=self.capital_spin.value(),
            stop_loss_pct=self.sl_spin.value() / 100,
            take_profit_pct=self.tp_spin.value() / 100,
            confidence_threshold=self.conf_spin.value(),
            use_per_token_model=use_per_token,
        )

        def _run():
            try:
                result = self._backtester.run(config, progress_cb=self._on_progress)
                self._result = result
                self._finish(result)
            except Exception as exc:
                self._finish_error(str(exc))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _stop_backtest(self) -> None:
        if self._backtester:
            self._backtester.stop()
        self._finish_error("Stopped by user")

    # ── Progress + results (called from threads via QTimer trick) ──────
    def _on_progress(self, data: dict) -> None:
        pct = int(data.get("pct", 0))
        # Qt controls must be updated from main thread — use timer
        try:
            self.progress_bar.setValue(pct)
        except Exception:
            pass

    def _finish(self, result) -> None:
        """Called from background thread – updates UI safely."""
        try:
            import numpy as np
            # Must update UI in main thread
            from PyQt6.QtCore import QMetaObject, Qt
            self._pending_result = result
            QMetaObject.invokeMethod(self, "_apply_result", Qt.ConnectionType.QueuedConnection)
        except Exception:
            pass

    def _apply_result(self) -> None:
        result = getattr(self, "_pending_result", None)
        if not result:
            return
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.export_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_lbl.setText("Status: COMPLETE")
        self.status_lbl.setStyleSheet(f"color:{ACCENT}; font-size:12px; font-weight:600;")
        self._populate_metrics(result)
        self._draw_equity_curve(result)
        self._populate_trade_log(result)

    def _finish_error(self, msg: str) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_lbl.setText(f"Status: ERROR – {msg[:40]}")
        self.status_lbl.setStyleSheet(f"color:{RED}; font-size:12px; font-weight:600;")

    def _reset_metrics(self) -> None:
        for i in range(self.metrics_tbl.rowCount()):
            self.metrics_tbl.setItem(i, 1, QTableWidgetItem("—"))

    def _populate_metrics(self, result) -> None:
        import numpy as np
        values = [
            f"{result.total_return_pct:+.2f}%",
            f"{result.cagr_pct:+.2f}%",
            f"{result.sharpe_ratio:.2f}",
            f"{result.sortino_ratio:.2f}",
            f"{result.max_drawdown_pct:.2f}%",
            f"{result.calmar_ratio:.2f}",
            f"{result.win_rate:.1%}",
            f"{result.profit_factor:.2f}",
            str(result.total_trades),
            f"{result.avg_win_pct:+.2f}%",
            f"{result.avg_loss_pct:+.2f}%",
            f"${result.final_capital:,.2f}",
        ]
        colours = [
            GREEN if result.total_return_pct >= 0 else RED,
            GREEN if result.cagr_pct >= 0 else RED,
            GREEN if result.sharpe_ratio >= 1 else YELLOW if result.sharpe_ratio >= 0 else RED,
            GREEN if result.sortino_ratio >= 1 else YELLOW,
            RED, YELLOW, GREEN if result.win_rate >= 0.5 else RED,
            GREEN if result.profit_factor >= 1.5 else YELLOW,
            FG0, GREEN, RED, GREEN if result.final_capital > result.config.initial_capital else RED,
        ]
        for i, (v, c) in enumerate(zip(values, colours)):
            item = QTableWidgetItem(v)
            item.setForeground(QBrush(QColor(c)))
            self.metrics_tbl.setItem(i, 1, item)

    def _draw_equity_curve(self, result) -> None:
        import numpy as np
        eq = result.equity_curve
        if not eq:
            return
        x = list(range(len(eq)))
        self.equity_plot.clear()
        colour = GREEN if eq[-1] >= eq[0] else RED
        self.equity_plot.plot(x, eq, pen=pg.mkPen(colour, width=2))
        # Horizontal line at initial capital
        self.equity_plot.addLine(y=result.config.initial_capital,
                                  pen=pg.mkPen(YELLOW, width=1, style=Qt.PenStyle.DashLine))
        # Drawdown
        eq_arr = np.array(eq)
        peak = np.maximum.accumulate(eq_arr)
        dd = (eq_arr - peak) / (peak + 1e-9) * 100
        self.dd_plot.clear()
        self.dd_plot.plot(x, dd.tolist(), pen=pg.mkPen(RED, width=1))
        self.dd_plot.addLine(y=0, pen=pg.mkPen(BORDER, width=1))

    def _populate_trade_log(self, result) -> None:
        self.trade_tbl.setRowCount(0)
        for trade in result.trades:
            row = self.trade_tbl.rowCount()
            self.trade_tbl.insertRow(row)
            pnl = trade.pnl
            colour = GREEN if pnl >= 0 else RED
            items = [
                (trade.symbol, FG0),
                (trade.direction, GREEN if trade.direction == "BUY" else RED),
                (f"{trade.entry_price:,.4f}", FG1),
                (f"{trade.exit_price:,.4f}", FG1),
                (f"{trade.quantity:.6f}", FG2),
                (f"{pnl:+,.4f}", colour),
                (trade.exit_reason, YELLOW),
            ]
            for col, (text, fg) in enumerate(items):
                item = QTableWidgetItem(text)
                item.setForeground(QBrush(QColor(fg)))
                self.trade_tbl.setItem(row, col, item)

    def _export_pdf(self) -> None:
        if not self._result:
            return
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
            from reportlab.lib.styles import getSampleStyleSheet
            import tempfile, os, subprocess

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                path = f.name

            doc = SimpleDocTemplate(path, pagesize=A4)
            styles = getSampleStyleSheet()
            r = self._result
            content = [
                Paragraph(f"Backtest Report – {r.config.symbol}/{r.config.interval}", styles["Title"]),
                Spacer(1, 12),
                Paragraph(r.summary(), styles["Normal"]),
                Spacer(1, 12),
            ]
            # Metrics table
            data = [["Metric", "Value"]]
            for i in range(self.metrics_tbl.rowCount()):
                name  = self.metrics_tbl.item(i, 0).text()
                value = self.metrics_tbl.item(i, 1).text()
                data.append([name, value])
            content.append(Table(data))
            doc.build(content)

            subprocess.Popen(["open", path])
            QMessageBox.information(self, "PDF Exported", f"Report saved and opened:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", str(exc))
