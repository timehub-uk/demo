"""
ML Training & Continuous Learning widget.
Displays:
  - Phase 1: Archive download progress (old/historical data)
  - Phase 2: Live gap-fill + live training progress (current data)
  - Phase 3: Per-token individual model training status
  - Universal model training (loss/accuracy charts)
  - Whale watcher activity feed
  - Model performance metrics
  - Live inference signals
  - Training controls (start / pause / stop)
"""

from __future__ import annotations

import time

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject, QMetaObject, Q_ARG
from PyQt6.QtGui import QColor, QBrush, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QGroupBox, QFrame, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QCheckBox, QTabWidget,
    QTextEdit, QScrollArea,
)

from ui.styles import ACCENT, GREEN, RED, YELLOW, BG2, BG3, BG4, BORDER, FG0, FG1, FG2

pg.setConfigOption("background", BG2)
pg.setConfigOption("foreground", FG1)

ORANGE = "#FF9800"
PURPLE = "#CE93D8"


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


# ── Phase progress card ───────────────────────────────────────────────────────

class PhaseCard(QFrame):
    """A compact card showing one training phase with its own progress bar."""

    def __init__(self, phase_num: int, title: str, color: str, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"QFrame {{ background:{BG3}; border:1px solid {color}; border-radius:6px; padding:4px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Header row
        hdr = QHBoxLayout()
        badge = QLabel(f"PHASE {phase_num}")
        badge.setStyleSheet(
            f"background:{color}; color:#000; font-size:9px; font-weight:800; "
            f"padding:1px 5px; border-radius:3px;"
        )
        hdr.addWidget(badge)
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(f"color:{FG0}; font-size:11px; font-weight:700;")
        hdr.addWidget(self.title_lbl)
        hdr.addStretch()
        self.status_lbl = QLabel("WAITING")
        self.status_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        hdr.addWidget(self.status_lbl)
        layout.addLayout(hdr)

        # Progress bar
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(12)
        self.bar.setStyleSheet(
            f"QProgressBar {{ background:{BG4}; border-radius:4px; }}"
            f"QProgressBar::chunk {{ background:{color}; border-radius:4px; }}"
        )
        layout.addWidget(self.bar)

        # Detail row
        self.detail_lbl = QLabel("—")
        self.detail_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        self.detail_lbl.setWordWrap(True)
        layout.addWidget(self.detail_lbl)

    def set_active(self, pct: float, detail: str = "") -> None:
        self.bar.setValue(int(pct))
        self.status_lbl.setText(f"▶ {pct:.0f}%")
        self.status_lbl.setStyleSheet(f"color:{self._color}; font-size:10px; font-weight:700;")
        if detail:
            self.detail_lbl.setText(detail[:100])

    def set_done(self) -> None:
        self.bar.setValue(100)
        self.status_lbl.setText("✅ DONE")
        self.status_lbl.setStyleSheet(f"color:{GREEN}; font-size:10px; font-weight:700;")

    def set_error(self, msg: str = "") -> None:
        self.status_lbl.setText("❌ ERROR")
        self.status_lbl.setStyleSheet(f"color:{RED}; font-size:10px; font-weight:700;")
        if msg:
            self.detail_lbl.setText(msg[:100])

    def reset(self) -> None:
        self.bar.setValue(0)
        self.status_lbl.setText("WAITING")
        self.status_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        self.detail_lbl.setText("—")


# ── Main widget ───────────────────────────────────────────────────────────────

class MLTrainingWidget(QWidget):
    training_started  = pyqtSignal()
    training_finished = pyqtSignal()
    _whale_event_sig  = pyqtSignal(object)
    _add_signal_sig   = pyqtSignal(dict)

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
        self._whale_event_sig.connect(self._do_add_whale_event)
        self._add_signal_sig.connect(self._do_add_signal)

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

        # Main splitter: left controls / right charts+tables
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ────────────────────────────────── LEFT PANEL ────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 4, 0)
        ll.setSpacing(8)

        # Control group
        ctrl_grp = QGroupBox("Training Controls")
        cgl = QVBoxLayout(ctrl_grp)

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

        cl_row = QHBoxLayout()
        self.cl_check = QCheckBox("Continuous learning (retrain every 24h)")
        self.cl_check.setChecked(True)
        cl_row.addWidget(self.cl_check)
        cgl.addLayout(cl_row)

        per_tok_row = QHBoxLayout()
        self.per_token_check = QCheckBox("Per-token individual models")
        self.per_token_check.setChecked(True)
        per_tok_row.addWidget(self.per_token_check)
        cgl.addLayout(per_tok_row)

        ll.addWidget(ctrl_grp)

        # ── Phase cards ───────────────────────────────────────────────
        phases_grp = QGroupBox("Training Pipeline")
        phl = QVBoxLayout(phases_grp)
        phl.setSpacing(6)

        self.phase1_card = PhaseCard(1, "Historical Archive Download", ORANGE)
        self.phase1_card.title_lbl.setText("Historical Archive  (1 year)")
        phl.addWidget(self.phase1_card)

        self.phase2_card = PhaseCard(2, "Live Data Gap-Fill", ACCENT)
        self.phase2_card.title_lbl.setText("Live Gap-Fill  (last 7 days)")
        phl.addWidget(self.phase2_card)

        self.phase3_card = PhaseCard(3, "Universal Model Training", PURPLE)
        self.phase3_card.title_lbl.setText("Universal LSTM+Transformer")
        phl.addWidget(self.phase3_card)

        self.phase4_card = PhaseCard(4, "Per-Token Model Training", GREEN)
        self.phase4_card.title_lbl.setText("Individual Token Networks")
        phl.addWidget(self.phase4_card)

        ll.addWidget(phases_grp)

        # Model Performance metrics
        metrics_grp = QGroupBox("Model Performance")
        mgl = QVBoxLayout(metrics_grp)
        self.metrics_tbl = QTableWidget(6, 2)
        self.metrics_tbl.setHorizontalHeaderLabels(["Metric", "Value"])
        self.metrics_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.metrics_tbl.verticalHeader().setVisible(False)
        self.metrics_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.metrics_tbl.setMaximumHeight(165)
        for row, metric in enumerate(["Accuracy","Win Rate","Sharpe Ratio","Max Drawdown","Total Signals","Model Version"]):
            self.metrics_tbl.setItem(row, 0, QTableWidgetItem(metric))
            self.metrics_tbl.setItem(row, 1, QTableWidgetItem("—"))
        mgl.addWidget(self.metrics_tbl)
        ll.addWidget(metrics_grp)

        ll.addStretch()
        splitter.addWidget(left)

        # ────────────────────────────────── RIGHT PANEL ───────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)
        rl.setSpacing(6)

        # Tab widget for charts / per-token / whale
        self.right_tabs = QTabWidget()
        self.right_tabs.setStyleSheet(
            f"QTabBar::tab {{ color:{FG1}; background:{BG3}; padding:4px 10px; }}"
            f"QTabBar::tab:selected {{ background:{BG4}; color:{ACCENT}; }}"
        )

        # ── Tab 1: Loss / Accuracy charts ─────────────────────────────
        charts_tab = QWidget()
        ctl = QVBoxLayout(charts_tab)
        ctl.setSpacing(6)

        self.loss_plot = pg.PlotWidget(title="Training Loss")
        self.loss_plot.setLabel("left", "Loss")
        self.loss_plot.setLabel("bottom", "Epoch")
        self.loss_plot.showGrid(x=True, y=True, alpha=0.15)
        ctl.addWidget(self.loss_plot)

        self.acc_plot = pg.PlotWidget(title="Validation Accuracy")
        self.acc_plot.setLabel("left", "Accuracy %")
        self.acc_plot.setLabel("bottom", "Epoch")
        self.acc_plot.showGrid(x=True, y=True, alpha=0.15)
        ctl.addWidget(self.acc_plot)

        # Epoch info bar
        epoch_row = QHBoxLayout()
        self.epoch_lbl = QLabel("Epoch: —")
        epoch_row.addWidget(self.epoch_lbl)
        self.loss_lbl = QLabel("Loss: —")
        epoch_row.addWidget(self.loss_lbl)
        self.acc_lbl = QLabel("Accuracy: —")
        epoch_row.addWidget(self.acc_lbl)
        epoch_row.addStretch()
        ctl.addLayout(epoch_row)

        self.right_tabs.addTab(charts_tab, "📈 Charts")

        # ── Tab 2: Per-token training status ──────────────────────────
        token_tab = QWidget()
        ttl = QVBoxLayout(token_tab)

        token_hdr = QHBoxLayout()
        token_title = QLabel("Per-Token Model Status")
        token_title.setStyleSheet(f"color:{GREEN}; font-size:11px; font-weight:700;")
        token_hdr.addWidget(token_title)
        token_hdr.addStretch()
        self.token_count_lbl = QLabel("0 models trained")
        self.token_count_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        token_hdr.addWidget(self.token_count_lbl)
        ttl.addLayout(token_hdr)

        self.token_tbl = QTableWidget(0, 8)
        self.token_tbl.setHorizontalHeaderLabels([
            "Symbol", "Trained", "Val Acc", "Live Win%",
            "Rows", "Peak Hour", "Volatility%", "Last Trained"
        ])
        self.token_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.token_tbl.horizontalHeader().setStretchLastSection(True)
        self.token_tbl.verticalHeader().setVisible(False)
        self.token_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.token_tbl.setAlternatingRowColors(True)
        self.token_tbl.setStyleSheet(
            f"QTableWidget {{ alternate-background-color: {BG3}; }}"
        )
        ttl.addWidget(self.token_tbl)

        self.right_tabs.addTab(token_tab, "🪙 Per-Token")

        # ── Tab 3: Whale watcher ──────────────────────────────────────
        whale_tab = QWidget()
        whl = QVBoxLayout(whale_tab)

        whale_hdr = QHBoxLayout()
        whale_title = QLabel("🐳 WHALE ACTIVITY MONITOR")
        whale_title.setStyleSheet(f"color:{ACCENT}; font-size:11px; font-weight:700; letter-spacing:1px;")
        whale_hdr.addWidget(whale_title)
        whale_hdr.addStretch()
        self.whale_count_lbl = QLabel("0 events detected")
        self.whale_count_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        whale_hdr.addWidget(self.whale_count_lbl)
        whl.addLayout(whale_hdr)

        # Whale events table
        self.whale_tbl = QTableWidget(0, 7)
        self.whale_tbl.setHorizontalHeaderLabels([
            "Symbol", "Event Type", "Side", "Price", "Volume USD", "Confidence", "Time"
        ])
        self.whale_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.whale_tbl.horizontalHeader().setStretchLastSection(True)
        self.whale_tbl.verticalHeader().setVisible(False)
        self.whale_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.whale_tbl.setMaximumHeight(220)
        whl.addWidget(self.whale_tbl)

        # Whale profiles
        prof_lbl = QLabel("Learned Whale Profiles")
        prof_lbl.setStyleSheet(f"color:{FG1}; font-size:11px; font-weight:700; margin-top:6px;")
        whl.addWidget(prof_lbl)

        self.whale_profiles_tbl = QTableWidget(0, 6)
        self.whale_profiles_tbl.setHorizontalHeaderLabels([
            "Whale ID", "Events", "Avg Outcome%", "Predictability", "Typical Size USD", "Dominant Pattern"
        ])
        self.whale_profiles_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.whale_profiles_tbl.horizontalHeader().setStretchLastSection(True)
        self.whale_profiles_tbl.verticalHeader().setVisible(False)
        self.whale_profiles_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        whl.addWidget(self.whale_profiles_tbl)

        self.right_tabs.addTab(whale_tab, "🐳 Whale Watch")

        # ── Tab 4: ML signals ─────────────────────────────────────────
        signals_tab = QWidget()
        sgl = QVBoxLayout(signals_tab)

        self.signals_tbl = QTableWidget(0, 6)
        self.signals_tbl.setHorizontalHeaderLabels(["Symbol","Source","Action","Confidence","Price","Time"])
        self.signals_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.signals_tbl.verticalHeader().setVisible(False)
        self.signals_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        sgl.addWidget(self.signals_tbl)

        self.right_tabs.addTab(signals_tab, "📡 Signals")

        rl.addWidget(self.right_tabs, 1)

        splitter.addWidget(right)
        splitter.setSizes([360, 650])
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
        self.phase1_card.reset()
        self.phase2_card.reset()
        self.phase3_card.reset()
        self.phase4_card.reset()
        self._loss_history.clear()
        self._acc_history.clear()

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
        self.phase1_card.set_active(0, "Demo mode – no trainer connected")

    # ── Progress updates ────────────────────────────────────────────────
    def _on_progress(self, data: dict) -> None:
        event = data.get("event", "")
        message = data.get("message", "")
        pct = float(data.get("pct", 0))

        # Route to appropriate phase card
        if event in ("archive", "archive_progress"):
            self.phase1_card.set_active(min(pct / 38 * 100, 99), message)
        elif event == "archive_done":
            self.phase1_card.set_done()
        elif event == "data":
            self.phase2_card.set_active(min((pct - 38) / 4 * 100, 99), message)
        elif event in ("train_start", "epoch", "validate", "save"):
            if pct < 95:
                self.phase3_card.set_active(min((pct - 42) / 53 * 100, 99), message)
            else:
                self.phase3_card.set_done()
        elif event == "token_train":
            self.phase4_card.set_active(pct, message)
            self.right_tabs.setCurrentIndex(1)  # Switch to Per-Token tab
        elif event == "token_train_done":
            self.phase4_card.set_done()

        if event == "epoch":
            parts = message.split("|")
            if len(parts) >= 3:
                try:
                    loss_val = float(parts[1].strip().split(":")[1].strip())
                    acc_val  = float(parts[2].strip().split(":")[1].strip().replace("%","")) / 100
                    self._loss_history.append(loss_val)
                    self._acc_history.append(acc_val * 100)
                    self._update_charts()
                    self.loss_lbl.setText(f"Loss: {loss_val:.4f}")
                    self.acc_lbl.setText(f"Accuracy: {acc_val:.2%}")
                    self.epoch_lbl.setText(f"Epoch: {len(self._loss_history)}")
                except Exception:
                    pass

    def _on_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.mode_lbl.setText("Status: COMPLETE")
        self.mode_lbl.setStyleSheet(f"color:{ACCENT}; font-size:12px; font-weight:600;")
        self.phase1_card.set_done()
        self.phase3_card.set_done()
        if self._thread:
            self._thread.quit()
        self.training_finished.emit()
        self._load_metrics()

    def _on_error(self, msg: str) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.mode_lbl.setText(f"Status: ERROR – {msg[:40]}")
        self.mode_lbl.setStyleSheet(f"color:{RED}; font-size:12px; font-weight:600;")
        self.phase3_card.set_error(msg)

    # ── Chart updates ───────────────────────────────────────────────────
    def _update_charts(self) -> None:
        epochs = list(range(1, len(self._loss_history) + 1))
        self.loss_plot.clear()
        self.loss_plot.plot(epochs, self._loss_history, pen=pg.mkPen(RED, width=2))
        self.acc_plot.clear()
        self.acc_plot.plot(epochs, self._acc_history, pen=pg.mkPen(GREEN, width=2))

    def _load_metrics(self) -> None:
        try:
            from db.postgres import get_db
            from db.models import MLModel
            with get_db() as db:
                from sqlalchemy import select
                m = db.execute(
                    select(MLModel).filter_by(is_active=True).order_by(MLModel.created_at.desc())
                ).scalar_one_or_none()
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

    # ── Public: add signal ──────────────────────────────────────────────
    def add_signal(self, signal: dict) -> None:
        """Thread-safe entry point – marshal to main thread via signal."""
        self._add_signal_sig.emit(signal)

    def _do_add_signal(self, signal: dict) -> None:
        """Add a new ML signal to the signals table (from universal or per-token model)."""
        action = signal.get("action", signal.get("signal", ""))
        colour = GREEN if action == "BUY" else RED if action == "SELL" else YELLOW
        source = signal.get("source", "Universal")
        row = self.signals_tbl.rowCount()
        self.signals_tbl.insertRow(row)
        items = [
            (signal.get("symbol", ""), FG0),
            (source, ACCENT),
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
        self.right_tabs.setTabText(3, f"📡 Signals ({self.signals_tbl.rowCount()})")

    # ── Public: add whale event ─────────────────────────────────────────
    def add_whale_event(self, event) -> None:
        """Thread-safe entry point – marshal to main thread via signal."""
        self._whale_event_sig.emit(event)

    def _do_add_whale_event(self, event) -> None:
        """Add a whale event to the whale activity table."""
        evt_type = getattr(event, "event_type", str(event))
        color_map = {
            "FALSE_WALL": YELLOW,
            "BUY_WALL":   GREEN,
            "SELL_WALL":  RED,
            "ATTACK_UP":  GREEN,
            "ATTACK_DOWN": RED,
            "ACCUMULATION": ACCENT,
            "SPOOF":      ORANGE,
        }
        colour = color_map.get(evt_type, FG1)
        row = self.whale_tbl.rowCount()
        self.whale_tbl.insertRow(row)
        items = [
            (getattr(event, "symbol", ""), FG0),
            (evt_type, colour),
            (getattr(event, "side", ""), FG1),
            (f"{getattr(event, 'price', 0):,.4f}", FG0),
            (f"${getattr(event, 'volume_usd', 0):,.0f}", colour),
            (f"{getattr(event, 'confidence', 0):.0%}", colour),
            (time.strftime("%H:%M:%S"), FG2),
        ]
        for col, (text, fg) in enumerate(items):
            item = QTableWidgetItem(text)
            item.setForeground(QBrush(QColor(fg)))
            self.whale_tbl.setItem(row, col, item)
        if self.whale_tbl.rowCount() > 100:
            self.whale_tbl.removeRow(0)
        self.whale_tbl.scrollToBottom()
        count = self.whale_tbl.rowCount()
        self.whale_count_lbl.setText(f"{count} events detected")
        self.right_tabs.setTabText(2, f"🐳 Whale ({count})")

    def update_whale_profiles(self, profiles: list) -> None:
        """Refresh the whale profiles table from learned profiles."""
        self.whale_profiles_tbl.setRowCount(0)
        for p in profiles:
            if not hasattr(p, "event_count") or p.event_count == 0:
                continue
            row = self.whale_profiles_tbl.rowCount()
            self.whale_profiles_tbl.insertRow(row)
            dominant = max(getattr(p, "favourite_events", {}).items(),
                           key=lambda x: x[1], default=("—", 0))[0]
            avg_out = getattr(p, "avg_outcome", 0)
            pred    = getattr(p, "predictability", 0)
            colour  = GREEN if avg_out > 0 else RED if avg_out < 0 else FG1
            items = [
                (getattr(p, "whale_id", "?"), ACCENT),
                (str(getattr(p, "event_count", 0)), FG1),
                (f"{avg_out:+.2f}%", colour),
                (f"{pred:.0%}", YELLOW),
                (f"${getattr(p, 'typical_size_usd', 0):,.0f}", FG0),
                (dominant, colour),
            ]
            for col, (text, fg) in enumerate(items):
                item = QTableWidgetItem(text)
                item.setForeground(QBrush(QColor(fg)))
                self.whale_profiles_tbl.setItem(row, col, item)

    def update_token_table(self, rows: list[dict]) -> None:
        """Refresh the per-token model status table."""
        self.token_tbl.setRowCount(0)
        trained_count = 0
        for r in rows:
            row = self.token_tbl.rowCount()
            self.token_tbl.insertRow(row)
            trained = r.get("trained", False)
            if trained:
                trained_count += 1
            val_acc   = r.get("val_accuracy", 0)
            win_rate  = r.get("live_win_rate", 0)
            acc_col   = GREEN if val_acc >= 0.6 else YELLOW if val_acc >= 0.5 else RED
            wr_col    = GREEN if win_rate >= 0.55 else YELLOW if win_rate >= 0.45 else RED

            items = [
                (r.get("symbol", ""), FG0),
                ("✅" if trained else "⏳", GREEN if trained else YELLOW),
                (f"{val_acc:.1%}", acc_col),
                (f"{win_rate:.1%}", wr_col),
                (str(r.get("training_rows", 0)), FG2),
                (f"{r.get('peak_volume_hour', 0):02d}:00 UTC", FG1),
                (f"{r.get('avg_volatility_pct', 0):.2f}%", FG1),
                (r.get("last_trained", "")[:16] or "—", FG2),
            ]
            for col, (text, fg) in enumerate(items):
                item = QTableWidgetItem(text)
                item.setForeground(QBrush(QColor(fg)))
                self.token_tbl.setItem(row, col, item)

        total = len(rows)
        self.token_count_lbl.setText(f"{trained_count}/{total} models trained")
        self.right_tabs.setTabText(1, f"🪙 Per-Token ({trained_count}/{total})")

    # ── Status polling ─────────────────────────────────────────────────
    def _start_status_timer(self) -> None:
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._poll_status)
        self._status_timer.start(5000)

    def _poll_status(self) -> None:
        try:
            from db.redis_client import RedisClient
            rc = RedisClient()

            # Universal training progress
            prog = rc.get_training_progress()
            if prog and not (self._worker and self._thread and self._thread.isRunning()):
                pct = prog.get("pct", 0)
                msg = prog.get("message", "")
                event = prog.get("event", "")
                self._on_progress({"event": event, "message": msg, "pct": pct})

            # Archive bootstrap progress
            arch = rc.get("archive:bootstrap_progress")
            if arch and isinstance(arch, dict):
                arch_pct = arch.get("pct", 0)
                sym = arch.get("symbol", "")
                self.phase1_card.set_active(arch_pct, f"Downloading {sym}…")

            # Archive main progress
            arch2 = rc.get("archive:progress")
            if arch2 and isinstance(arch2, dict):
                arch2_pct = arch2.get("global_pct", 0)
                sym2 = arch2.get("symbol", "")
                self.phase1_card.set_active(arch2_pct, f"Archive: {sym2}")

        except Exception:
            pass
