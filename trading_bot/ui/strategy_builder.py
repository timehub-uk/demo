"""
Strategy Builder UI.

A visual rule-based strategy editor where the user defines
entry/exit conditions and the system backtests them.

Layout:
  ┌──────────────────────────────────────────────────────────┐
  │  Strategy name  [Load] [Save] [New]                      │
  ├───────────────────────┬──────────────────────────────────┤
  │  Entry Conditions     │  Strategy Library                │
  │  + Add Condition      │  (saved strategies)              │
  ├───────────────────────┤                                  │
  │  Exit Conditions      │                                  │
  │  + Add Condition      │                                  │
  ├───────────────────────┴──────────────────────────────────┤
  │  Position sizing  |  SL/TP  |  [▶ Run Backtest]          │
  └──────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QSplitter, QListWidget, QListWidgetItem,
    QMessageBox, QFileDialog, QProgressBar, QFrame,
)

from ui.styles import ACCENT, GREEN, RED, YELLOW, BG2, BG3, BG4, BORDER, FG0, FG1, FG2

STRATEGIES_DIR = Path(__file__).parent.parent / "data" / "strategies"
STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)

ORANGE = "#FF9800"

# ── Condition row ─────────────────────────────────────────────────────────────

INDICATORS = [
    "RSI", "MACD", "EMA_20", "EMA_50", "EMA_200", "BB_UPPER", "BB_LOWER",
    "ATR", "ADX", "VWAP", "OBV", "CLOSE", "VOLUME", "CANDLE_BODY",
    "ML_SIGNAL", "WHALE_EVENT", "SENTIMENT_SCORE",
]
OPERATORS = [">", "<", ">=", "<=", "==", "crosses_above", "crosses_below"]


class ConditionRow(QFrame):
    removed = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"QFrame {{ background:{BG3}; border:1px solid {BORDER}; border-radius:4px; }}")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(6)

        self.indicator_combo = QComboBox()
        self.indicator_combo.addItems(INDICATORS)
        self.indicator_combo.setFixedWidth(130)
        lay.addWidget(self.indicator_combo)

        self.operator_combo = QComboBox()
        self.operator_combo.addItems(OPERATORS)
        self.operator_combo.setFixedWidth(110)
        lay.addWidget(self.operator_combo)

        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(-999999, 999999)
        self.value_spin.setValue(30)
        self.value_spin.setDecimals(2)
        self.value_spin.setFixedWidth(90)
        lay.addWidget(self.value_spin)

        self.logic_combo = QComboBox()
        self.logic_combo.addItems(["AND", "OR"])
        self.logic_combo.setFixedWidth(55)
        lay.addWidget(self.logic_combo)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(24, 24)
        del_btn.setStyleSheet(f"color:{RED}; background:transparent; border:none; font-size:12px;")
        del_btn.clicked.connect(lambda: self.removed.emit(self))
        lay.addWidget(del_btn)

    def to_dict(self) -> dict:
        return {
            "indicator": self.indicator_combo.currentText(),
            "operator":  self.operator_combo.currentText(),
            "value":     self.value_spin.value(),
            "logic":     self.logic_combo.currentText(),
        }

    def from_dict(self, d: dict) -> None:
        self.indicator_combo.setCurrentText(d.get("indicator", "RSI"))
        self.operator_combo.setCurrentText(d.get("operator", ">"))
        self.value_spin.setValue(float(d.get("value", 30)))
        self.logic_combo.setCurrentText(d.get("logic", "AND"))


# ── Strategy builder widget ───────────────────────────────────────────────────

class StrategyBuilderWidget(QWidget):
    backtest_requested = pyqtSignal(dict)   # Emit strategy dict for backtester

    def __init__(self, backtester=None, parent=None) -> None:
        super().__init__(parent)
        self._backtester = backtester
        self._entry_rows: list[ConditionRow] = []
        self._exit_rows:  list[ConditionRow] = []
        self._setup_ui()
        self._load_library()

    # ── UI setup ───────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("⚙️ STRATEGY BUILDER")
        title.setStyleSheet(f"color:{ACCENT}; font-size:13px; font-weight:700; letter-spacing:1px;")
        hdr.addWidget(title)
        hdr.addStretch()
        layout.addLayout(hdr)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: editor ──────────────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 4, 0)
        ll.setSpacing(8)

        # Name row
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Strategy name:"))
        self.name_edit = QLineEdit("My Strategy")
        self.name_edit.setFixedWidth(200)
        name_row.addWidget(self.name_edit)
        name_row.addStretch()
        new_btn = QPushButton("New")
        new_btn.setObjectName("btn_primary")
        new_btn.clicked.connect(self._new_strategy)
        name_row.addWidget(new_btn)
        save_btn = QPushButton("💾 Save")
        save_btn.setObjectName("btn_primary")
        save_btn.clicked.connect(self._save_strategy)
        name_row.addWidget(save_btn)
        import_btn = QPushButton("📥 Import JSON")
        import_btn.setObjectName("btn_primary")
        import_btn.clicked.connect(self._import_strategy)
        name_row.addWidget(import_btn)
        export_btn_hdr = QPushButton("📤 Export JSON")
        export_btn_hdr.setObjectName("btn_primary")
        export_btn_hdr.clicked.connect(self._export_strategy)
        name_row.addWidget(export_btn_hdr)
        ll.addLayout(name_row)

        # Symbol + interval
        sym_row = QHBoxLayout()
        sym_row.addWidget(QLabel("Symbol:"))
        self.symbol_edit = QLineEdit("BTCUSDT")
        self.symbol_edit.setFixedWidth(100)
        sym_row.addWidget(self.symbol_edit)
        sym_row.addWidget(QLabel("Interval:"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["1m","5m","15m","1h","4h","1d"])
        self.interval_combo.setCurrentText("1h")
        sym_row.addWidget(self.interval_combo)
        sym_row.addStretch()
        ll.addLayout(sym_row)

        # ── Entry conditions ─────────────────────────────────────────
        entry_grp = QGroupBox("Entry Conditions (BUY)")
        egl = QVBoxLayout(entry_grp)
        self.entry_conditions_layout = QVBoxLayout()
        self.entry_conditions_layout.setSpacing(4)
        egl.addLayout(self.entry_conditions_layout)
        add_entry_btn = QPushButton("+ Add Entry Condition")
        add_entry_btn.setObjectName("btn_primary")
        add_entry_btn.clicked.connect(self._add_entry_condition)
        egl.addWidget(add_entry_btn)
        ll.addWidget(entry_grp)

        # ── Exit conditions ──────────────────────────────────────────
        exit_grp = QGroupBox("Exit Conditions (SELL)")
        exgl = QVBoxLayout(exit_grp)
        self.exit_conditions_layout = QVBoxLayout()
        self.exit_conditions_layout.setSpacing(4)
        exgl.addLayout(self.exit_conditions_layout)
        add_exit_btn = QPushButton("+ Add Exit Condition")
        add_exit_btn.setObjectName("btn_primary")
        add_exit_btn.clicked.connect(self._add_exit_condition)
        exgl.addWidget(add_exit_btn)
        ll.addWidget(exit_grp)

        # ── Position sizing ──────────────────────────────────────────
        pos_grp = QGroupBox("Position Sizing & Risk")
        pgl = QHBoxLayout(pos_grp)
        pgl.addWidget(QLabel("Capital %:"))
        self.capital_spin = QDoubleSpinBox()
        self.capital_spin.setRange(1, 100)
        self.capital_spin.setValue(95)
        self.capital_spin.setSuffix("%")
        pgl.addWidget(self.capital_spin)
        pgl.addWidget(QLabel("Stop Loss:"))
        self.sl_spin = QDoubleSpinBox()
        self.sl_spin.setRange(0.1, 20)
        self.sl_spin.setValue(2.0)
        self.sl_spin.setSuffix("%")
        pgl.addWidget(self.sl_spin)
        pgl.addWidget(QLabel("Take Profit:"))
        self.tp_spin = QDoubleSpinBox()
        self.tp_spin.setRange(0.1, 50)
        self.tp_spin.setValue(4.0)
        self.tp_spin.setSuffix("%")
        pgl.addWidget(self.tp_spin)
        pgl.addStretch()
        ll.addWidget(pos_grp)

        # ── Backtest button ──────────────────────────────────────────
        bt_row = QHBoxLayout()
        self.bt_btn = QPushButton("▶ Run Backtest")
        self.bt_btn.setObjectName("btn_buy")
        self.bt_btn.setFixedHeight(36)
        self.bt_btn.clicked.connect(self._run_backtest)
        bt_row.addStretch()
        bt_row.addWidget(self.bt_btn)
        ll.addLayout(bt_row)

        self.bt_progress = QProgressBar()
        self.bt_progress.setRange(0, 100)
        self.bt_progress.setValue(0)
        self.bt_progress.setVisible(False)
        ll.addWidget(self.bt_progress)

        self.bt_result_lbl = QLabel("")
        self.bt_result_lbl.setStyleSheet(f"color:{GREEN}; font-size:11px; font-weight:600;")
        self.bt_result_lbl.setWordWrap(True)
        ll.addWidget(self.bt_result_lbl)

        ll.addStretch()
        splitter.addWidget(left)

        # ── Right: strategy library ────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)
        rl.setSpacing(6)

        lib_title = QLabel("📚 Strategy Library")
        lib_title.setStyleSheet(f"color:{ACCENT}; font-size:11px; font-weight:700;")
        rl.addWidget(lib_title)

        self.lib_list = QListWidget()
        self.lib_list.setStyleSheet(f"QListWidget {{ background:{BG3}; border:1px solid {BORDER}; }}")
        self.lib_list.itemDoubleClicked.connect(self._load_from_library)
        rl.addWidget(self.lib_list)

        del_btn2 = QPushButton("🗑 Delete Selected")
        del_btn2.setObjectName("btn_cancel")
        del_btn2.clicked.connect(self._delete_from_library)
        rl.addWidget(del_btn2)

        splitter.addWidget(right)
        splitter.setSizes([700, 250])
        layout.addWidget(splitter, 1)

        # Add default conditions
        self._add_entry_condition()
        self._add_exit_condition()

    # ── Condition management ───────────────────────────────────────────
    def _add_entry_condition(self) -> None:
        row = ConditionRow()
        row.removed.connect(self._remove_entry_condition)
        self._entry_rows.append(row)
        self.entry_conditions_layout.addWidget(row)

    def _add_exit_condition(self) -> None:
        row = ConditionRow()
        row.removed.connect(self._remove_exit_condition)
        self._exit_rows.append(row)
        self.exit_conditions_layout.addWidget(row)

    def _remove_entry_condition(self, row: ConditionRow) -> None:
        if row in self._entry_rows:
            self._entry_rows.remove(row)
            row.setParent(None)
            row.deleteLater()

    def _remove_exit_condition(self, row: ConditionRow) -> None:
        if row in self._exit_rows:
            self._exit_rows.remove(row)
            row.setParent(None)
            row.deleteLater()

    # ── Serialisation ──────────────────────────────────────────────────
    def _get_strategy_dict(self) -> dict:
        return {
            "name": self.name_edit.text().strip() or "Unnamed",
            "symbol": self.symbol_edit.text().strip().upper() or "BTCUSDT",
            "interval": self.interval_combo.currentText(),
            "entry_conditions": [r.to_dict() for r in self._entry_rows],
            "exit_conditions":  [r.to_dict() for r in self._exit_rows],
            "capital_pct":   self.capital_spin.value(),
            "stop_loss_pct": self.sl_spin.value(),
            "take_profit_pct": self.tp_spin.value(),
        }

    def _load_strategy_dict(self, d: dict) -> None:
        self.name_edit.setText(d.get("name", ""))
        self.symbol_edit.setText(d.get("symbol", "BTCUSDT"))
        self.interval_combo.setCurrentText(d.get("interval", "1h"))
        self.capital_spin.setValue(float(d.get("capital_pct", 95)))
        self.sl_spin.setValue(float(d.get("stop_loss_pct", 2.0)))
        self.tp_spin.setValue(float(d.get("take_profit_pct", 4.0)))

        for r in list(self._entry_rows):
            r.setParent(None)
            r.deleteLater()
        self._entry_rows.clear()
        for c in d.get("entry_conditions", []):
            self._add_entry_condition()
            self._entry_rows[-1].from_dict(c)

        for r in list(self._exit_rows):
            r.setParent(None)
            r.deleteLater()
        self._exit_rows.clear()
        for c in d.get("exit_conditions", []):
            self._add_exit_condition()
            self._exit_rows[-1].from_dict(c)

    # ── Library ────────────────────────────────────────────────────────
    def _save_strategy(self) -> None:
        d = self._get_strategy_dict()
        name = d["name"].replace(" ", "_")
        path = STRATEGIES_DIR / f"{name}.json"
        path.write_text(json.dumps(d, indent=2))
        self._load_library()
        QMessageBox.information(self, "Saved", f"Strategy '{d['name']}' saved.")

    def _load_library(self) -> None:
        self.lib_list.clear()
        for f in sorted(STRATEGIES_DIR.glob("*.json")):
            item = QListWidgetItem(f.stem.replace("_", " "))
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            self.lib_list.addItem(item)

    def _load_from_library(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        try:
            d = json.loads(Path(path).read_text())
            self._load_strategy_dict(d)
        except Exception as exc:
            QMessageBox.warning(self, "Load Error", str(exc))

    def _delete_from_library(self) -> None:
        item = self.lib_list.currentItem()
        if not item:
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        if QMessageBox.question(self, "Delete", f"Delete '{item.text()}'?") == QMessageBox.StandardButton.Yes:
            path.unlink(missing_ok=True)
            self._load_library()

    def _import_strategy(self) -> None:
        """Import a strategy from any JSON file chosen by the user."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Strategy", str(Path.home()),
            "Strategy JSON (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            d = json.loads(Path(path).read_text())
            # Validate minimal required keys
            required = {"name", "entry_conditions", "exit_conditions"}
            if not required.issubset(d.keys()):
                raise ValueError(f"Missing required keys: {required - d.keys()}")
            self._load_strategy_dict(d)
            # Copy into library
            dest = STRATEGIES_DIR / Path(path).name
            dest.write_text(json.dumps(d, indent=2))
            self._load_library()
            QMessageBox.information(self, "Imported", f"Strategy '{d['name']}' imported successfully.")
        except Exception as exc:
            QMessageBox.warning(self, "Import Error", f"Failed to import strategy:\n{exc}")

    def _export_strategy(self) -> None:
        """Export the current strategy to a user-chosen JSON file location."""
        d = self._get_strategy_dict()
        default_name = d["name"].replace(" ", "_") + ".json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Strategy", str(Path.home() / default_name),
            "Strategy JSON (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(d, indent=2))
            QMessageBox.information(self, "Exported", f"Strategy exported to:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", f"Failed to export strategy:\n{exc}")

    def _new_strategy(self) -> None:
        for r in list(self._entry_rows + self._exit_rows):
            r.setParent(None)
            r.deleteLater()
        self._entry_rows.clear()
        self._exit_rows.clear()
        self.name_edit.setText("New Strategy")
        self._add_entry_condition()
        self._add_exit_condition()

    # ── Backtest ───────────────────────────────────────────────────────
    def _run_backtest(self) -> None:
        d = self._get_strategy_dict()
        self.backtest_requested.emit(d)
        if not self._backtester:
            QMessageBox.information(self, "Backtest", "Connect backtester service to run backtest.")
            return
        self.bt_btn.setEnabled(False)
        self.bt_progress.setVisible(True)
        self.bt_progress.setValue(0)
        self.bt_result_lbl.setText("Running backtest…")

        from ml.backtester import BacktestConfig
        config = BacktestConfig(
            symbol=d["symbol"],
            interval=d["interval"],
            position_size_pct=d["capital_pct"] / 100,
            stop_loss_pct=d["stop_loss_pct"] / 100,
            take_profit_pct=d["take_profit_pct"] / 100,
        )

        import threading
        def _run():
            try:
                result = self._backtester.run(config, progress_cb=self._on_bt_progress)
                from PyQt6.QtCore import QMetaObject, Qt
                # Use queued signal dispatch to update UI from thread
                self._bt_result = result
                QMetaObject.invokeMethod(self, "_finish_backtest", Qt.ConnectionType.QueuedConnection)
            except Exception as exc:
                self._bt_error = str(exc)
                QMetaObject.invokeMethod(self, "_backtest_error", Qt.ConnectionType.QueuedConnection)

        self._bt_thread = threading.Thread(target=_run, daemon=True)
        self._bt_thread.start()

    def _on_bt_progress(self, data: dict) -> None:
        try:
            from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
            pct = int(data.get("pct", 0))
            self.bt_progress.setValue(pct)
        except Exception:
            pass

    def _finish_backtest(self) -> None:
        result = getattr(self, "_bt_result", None)
        if result:
            self.bt_result_lbl.setStyleSheet(f"color:{GREEN}; font-size:11px; font-weight:600;")
            self.bt_result_lbl.setText(result.summary())
        self.bt_btn.setEnabled(True)
        self.bt_progress.setVisible(False)

    def _backtest_error(self) -> None:
        err = getattr(self, "_bt_error", "Unknown error")
        self.bt_result_lbl.setStyleSheet(f"color:{RED}; font-size:11px; font-weight:600;")
        self.bt_result_lbl.setText(f"Backtest error: {err}")
        self.bt_btn.setEnabled(True)
        self.bt_progress.setVisible(False)
