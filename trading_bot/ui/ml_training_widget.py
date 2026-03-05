"""
ML Training & Continuous Learning widget.
Displays:
  - Training progress (stage, epoch, loss, accuracy)
  - Token training coverage map
  - Model performance metrics
  - Live inference signals
  - Training controls (start / pause / stop)
"""

from __future__ import annotations

import time

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QColor, QBrush, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QGroupBox, QFrame, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QCheckBox, QTextEdit,
)

from ui.styles import ACCENT, GREEN, RED, YELLOW, BG2, BG3, BG4, BORDER, FG0, FG1, FG2

pg.setConfigOption("background", BG2)
pg.setConfigOption("foreground", FG1)


# ── Background training worker ────────────────────────────────────────────────

class TrainingWorker(QObject):
    progress = pyqtSignal(dict)
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, trainer, symbols) -> None:
        super().__init__()
        self._trainer = trainer
        self._symbols = symbols

    def run(self) -> None:
        try:
            self._trainer.on_progress(lambda d: self.progress.emit(d))
            self._trainer.run_training_session(self._symbols)
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


# ── Main widget ───────────────────────────────────────────────────────────────

class MLTrainingWidget(QWidget):
    training_started  = pyqtSignal()
    training_finished = pyqtSignal()

    def __init__(self, trainer=None, parent=None) -> None:
        super().__init__(parent)
        self._trainer = trainer
        self._worker: TrainingWorker | None = None
        self._thread: QThread | None = None
        self._loss_history: list[float] = []
        self._acc_history:  list[float] = []
        self._epoch_history: list[int] = []
        self._signal_history: list[dict] = []
        self._setup_ui()
        self._start_status_timer()

    # ── UI setup ───────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("🤖 ML TRAINING & CONTINUOUS LEARNING")
        title.setStyleSheet(f"color:{ACCENT}; font-size:13px; font-weight:700; letter-spacing:1px;")
        hdr.addWidget(title)
        hdr.addStretch()
        self.mode_lbl = QLabel("Status: IDLE")
        self.mode_lbl.setStyleSheet(f"color:{YELLOW}; font-size:12px; font-weight:600;")
        hdr.addWidget(self.mode_lbl)
        layout.addLayout(hdr)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left panel: controls + metrics ────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 4, 0)
        ll.setSpacing(8)

        # Control group
        ctrl_grp = QGroupBox("Training Controls")
        cgl = QVBoxLayout(ctrl_grp)

        # Token count + hours selector
        cfg_row = QHBoxLayout()
        cfg_row.addWidget(QLabel("Top tokens:"))
        self.tokens_combo = QComboBox()
        for n in [10, 25, 50, 100]:
            self.tokens_combo.addItem(str(n))
        self.tokens_combo.setCurrentText("100")
        cfg_row.addWidget(self.tokens_combo)
        cfg_row.addWidget(QLabel("Hours:"))
        self.hours_combo = QComboBox()
        for h in [1, 6, 12, 24, 48]:
            self.hours_combo.addItem(str(h))
        self.hours_combo.setCurrentText("48")
        cfg_row.addWidget(self.hours_combo)
        cgl.addLayout(cfg_row)

        # Buttons
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start Training")
        self.start_btn.setObjectName("btn_primary")
        self.start_btn.clicked.connect(self._start_training)
        btn_row.addWidget(self.start_btn)
        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setObjectName("btn_cancel")
        self.stop_btn.clicked.connect(self._stop_training)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.stop_btn)
        cgl.addLayout(btn_row)

        # Continuous learning toggle
        cl_row = QHBoxLayout()
        self.cl_check = QCheckBox("Continuous learning (retrain every 24h)")
        self.cl_check.setChecked(True)
        cl_row.addWidget(self.cl_check)
        cgl.addLayout(cl_row)

        ll.addWidget(ctrl_grp)

        # Progress group
        prog_grp = QGroupBox("Training Progress")
        pgl = QVBoxLayout(prog_grp)

        self.stage_lbl = QLabel("Stage: —")
        self.stage_lbl.setStyleSheet(f"color:{FG1}; font-size:11px;")
        pgl.addWidget(self.stage_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p% – %v/100")
        pgl.addWidget(self.progress_bar)

        # Epoch info
        epoch_row = QHBoxLayout()
        self.epoch_lbl = QLabel("Epoch: —")
        epoch_row.addWidget(self.epoch_lbl)
        self.loss_lbl = QLabel("Loss: —")
        epoch_row.addWidget(self.loss_lbl)
        self.acc_lbl = QLabel("Accuracy: —")
        epoch_row.addWidget(self.acc_lbl)
        epoch_row.addStretch()
        pgl.addLayout(epoch_row)

        ll.addWidget(prog_grp)

        # Metrics group
        metrics_grp = QGroupBox("Model Performance")
        mgl = QVBoxLayout(metrics_grp)
        self.metrics_tbl = QTableWidget(6, 2)
        self.metrics_tbl.setHorizontalHeaderLabels(["Metric", "Value"])
        self.metrics_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.metrics_tbl.verticalHeader().setVisible(False)
        self.metrics_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.metrics_tbl.setMaximumHeight(180)
        for row, metric in enumerate(["Accuracy","Win Rate","Sharpe Ratio","Max Drawdown","Total Signals","Model Version"]):
            self.metrics_tbl.setItem(row, 0, QTableWidgetItem(metric))
            self.metrics_tbl.setItem(row, 1, QTableWidgetItem("—"))
        mgl.addWidget(self.metrics_tbl)
        ll.addWidget(metrics_grp)

        ll.addStretch()
        splitter.addWidget(left)

        # ── Right panel: charts ────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)
        rl.setSpacing(6)

        # Loss chart
        self.loss_plot = pg.PlotWidget(title="Training Loss")
        self.loss_plot.setLabel("left", "Loss")
        self.loss_plot.setLabel("bottom", "Epoch")
        self.loss_plot.showGrid(x=True, y=True, alpha=0.15)
        self.loss_plot.setMaximumHeight(200)
        rl.addWidget(self.loss_plot)

        # Accuracy chart
        self.acc_plot = pg.PlotWidget(title="Validation Accuracy")
        self.acc_plot.setLabel("left", "Accuracy %")
        self.acc_plot.setLabel("bottom", "Epoch")
        self.acc_plot.showGrid(x=True, y=True, alpha=0.15)
        self.acc_plot.setMaximumHeight(200)
        rl.addWidget(self.acc_plot)

        # Signals table
        sig_grp = QGroupBox("Latest ML Signals")
        sgl = QVBoxLayout(sig_grp)
        self.signals_tbl = QTableWidget(0, 5)
        self.signals_tbl.setHorizontalHeaderLabels(["Symbol","Action","Confidence","Price","Time"])
        self.signals_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.signals_tbl.verticalHeader().setVisible(False)
        self.signals_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.signals_tbl.setMaximumHeight(200)
        sgl.addWidget(self.signals_tbl)
        rl.addWidget(sig_grp)

        splitter.addWidget(right)
        splitter.setSizes([350, 600])
        layout.addWidget(splitter, 1)

    # ── Training control ────────────────────────────────────────────────
    def _start_training(self) -> None:
        if not self._trainer:
            self._show_no_trainer()
            return
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.mode_lbl.setText("Status: TRAINING")
        self.mode_lbl.setStyleSheet(f"color:{GREEN}; font-size:12px; font-weight:600;")

        n_tokens = int(self.tokens_combo.currentText())
        self._thread = QThread()
        self._worker = TrainingWorker(self._trainer, None)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._thread.start()
        self.training_started.emit()

    def _stop_training(self) -> None:
        if self._trainer:
            self._trainer.stop()
        self._on_finished()

    def _show_no_trainer(self) -> None:
        self.stage_lbl.setText("Stage: Demo mode – no trainer connected")

    # ── Progress updates ────────────────────────────────────────────────
    def _on_progress(self, data: dict) -> None:
        event = data.get("event", "")
        message = data.get("message", "")
        pct = data.get("pct", 0)

        self.progress_bar.setValue(int(pct))
        self.stage_lbl.setText(f"Stage: {message[:80]}")

        if event == "epoch":
            # Parse epoch info from message
            parts = message.split("|")
            if len(parts) >= 3:
                try:
                    loss_part = parts[1].strip()
                    acc_part  = parts[2].strip()
                    loss_val = float(loss_part.split(":")[1].strip())
                    acc_val  = float(acc_part.split(":")[1].strip().replace("%", "")) / 100

                    epoch_num = len(self._loss_history) + 1
                    self._loss_history.append(loss_val)
                    self._acc_history.append(acc_val * 100)
                    self._epoch_history.append(epoch_num)
                    self._update_charts()

                    self.loss_lbl.setText(f"Loss: {loss_val:.4f}")
                    self.acc_lbl.setText(f"Accuracy: {acc_val:.2%}")
                except Exception:
                    pass

    def _on_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.mode_lbl.setText("Status: COMPLETE")
        self.mode_lbl.setStyleSheet(f"color:{ACCENT}; font-size:12px; font-weight:600;")
        self.progress_bar.setValue(100)
        if self._thread:
            self._thread.quit()
        self.training_finished.emit()
        self._load_metrics()

    def _on_error(self, msg: str) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.mode_lbl.setText(f"Status: ERROR – {msg[:40]}")
        self.mode_lbl.setStyleSheet(f"color:{RED}; font-size:12px; font-weight:600;")

    # ── Chart updates ───────────────────────────────────────────────────
    def _update_charts(self) -> None:
        epochs = list(range(1, len(self._loss_history) + 1))
        self.loss_plot.clear()
        self.loss_plot.plot(epochs, self._loss_history, pen=pg.mkPen(RED, width=2), name="Train Loss")

        self.acc_plot.clear()
        self.acc_plot.plot(epochs, self._acc_history, pen=pg.mkPen(GREEN, width=2), name="Val Accuracy")

    def _load_metrics(self) -> None:
        try:
            from db.postgres import get_db
            from db.models import MLModel
            with get_db() as db:
                m = db.query(MLModel).filter_by(is_active=True).order_by(MLModel.created_at.desc()).first()
                if m:
                    vals = [
                        f"{(m.accuracy or 0):.2%}",
                        f"{(m.win_rate or 0):.2%}",
                        f"{(m.sharpe_ratio or 0):.2f}",
                        f"{(m.max_drawdown or 0):.2%}",
                        str(m.total_trades_tested or 0),
                        m.version or "—",
                    ]
                    for row, v in enumerate(vals):
                        self.metrics_tbl.setItem(row, 1, QTableWidgetItem(v))
        except Exception:
            pass

    def add_signal(self, signal: dict) -> None:
        """Add a new ML signal to the signals table."""
        action = signal.get("action", "")
        colour = GREEN if action == "BUY" else RED if action == "SELL" else YELLOW
        row = self.signals_tbl.rowCount()
        self.signals_tbl.insertRow(row)
        items = [
            (signal.get("symbol", ""), FG0),
            (action, colour),
            (f"{signal.get('confidence', 0):.2%}", colour),
            (f"{signal.get('price', 0):,.4f}", FG0),
            (time.strftime("%H:%M:%S"), FG2),
        ]
        for col, (text, fg) in enumerate(items):
            item = QTableWidgetItem(text)
            item.setForeground(QBrush(QColor(fg)))
            self.signals_tbl.setItem(row, col, item)
        if self.signals_tbl.rowCount() > 50:
            self.signals_tbl.removeRow(0)
        self.signals_tbl.scrollToBottom()

    # ── Status polling ─────────────────────────────────────────────────
    def _start_status_timer(self) -> None:
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._poll_status)
        self._status_timer.start(5000)

    def _poll_status(self) -> None:
        try:
            from db.redis_client import RedisClient
            rc = RedisClient()
            prog = rc.get_training_progress()
            if prog and not self._trainer:
                pct = prog.get("pct", 0)
                msg = prog.get("message", "")
                self.progress_bar.setValue(int(pct))
                self.stage_lbl.setText(f"Stage: {msg[:80]}")
        except Exception:
            pass
