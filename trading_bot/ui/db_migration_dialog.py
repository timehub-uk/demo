"""
Database Migration Dialog  –  SQLite → PostgreSQL

Simple progress dialog shown while data is being copied.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar

from ui.styles import ACCENT, GREEN, RED, BG2, BG4, BORDER, FG0, FG2
from ui.icons import svg_pixmap


class _MigrationSignals(QObject):
    table_progress = pyqtSignal(str, int, int)   # table, copied, total
    finished       = pyqtSignal(bool, str)        # success, message


class DbMigrationDialog(QDialog):

    def __init__(self, pg_url: str, pg_pool_size: int = 5, pg_max_overflow: int = 10, parent=None) -> None:
        super().__init__(parent)
        self._pg_url          = pg_url
        self._pg_pool_size    = pg_pool_size
        self._pg_max_overflow = pg_max_overflow
        self._signals         = _MigrationSignals()
        self._signals.table_progress.connect(self._on_table_progress)
        self._signals.finished.connect(self._on_finished)
        self._table_counts: dict[str, tuple[int, int]] = {}

        self.setWindowTitle("Database")
        self.setFixedSize(360, 130)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setStyleSheet(
            f"QDialog {{ background:{BG2}; border:1px solid {BORDER}; border-radius:8px; }}"
        )
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Icon + label row
        row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(svg_pixmap("database", ACCENT, 20))
        icon.setFixedSize(24, 24)
        row.addWidget(icon)

        self._msg_lbl = QLabel("Updating databases…")
        self._msg_lbl.setStyleSheet(f"color:{FG0}; font-size:13px; font-weight:600;")
        row.addWidget(self._msg_lbl)
        row.addStretch()
        layout.addLayout(row)

        # Indeterminate progress bar (switches to determinate once we have row counts)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)   # indeterminate spinner
        self._bar.setFixedHeight(8)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(
            f"QProgressBar {{ background:{BG4}; border:none; border-radius:4px; }}"
            f"QProgressBar::chunk {{ background:{ACCENT}; border-radius:4px; }}"
        )
        layout.addWidget(self._bar)

        self._sub_lbl = QLabel("")
        self._sub_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        layout.addWidget(self._sub_lbl)

    # ── Public API ────────────────────────────────────────────────────

    def run(self) -> None:
        from db.sqlite_to_postgres import migrate_sqlite_to_postgres
        migrate_sqlite_to_postgres(
            pg_url=self._pg_url,
            pg_pool_size=self._pg_pool_size,
            pg_max_overflow=self._pg_max_overflow,
            progress_cb=self._signals.table_progress.emit,
            done_cb=self._signals.finished.emit,
        )
        self.exec()

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_table_progress(self, table: str, copied: int, total: int) -> None:
        if total <= 0:
            return
        self._table_counts[table] = (copied, total)
        total_all  = sum(t for _, t in self._table_counts.values())
        copied_all = sum(c for c, _ in self._table_counts.values())
        if total_all > 0:
            self._bar.setRange(0, total_all)
            self._bar.setValue(copied_all)

    def _on_finished(self, success: bool, message: str) -> None:
        if success:
            self._bar.setRange(0, 1)
            self._bar.setValue(1)
            self._bar.setStyleSheet(
                f"QProgressBar {{ background:{BG4}; border:none; border-radius:4px; }}"
                f"QProgressBar::chunk {{ background:{GREEN}; border-radius:4px; }}"
            )
            self._msg_lbl.setText("Databases updated.")
            self._msg_lbl.setStyleSheet(f"color:{GREEN}; font-size:13px; font-weight:600;")
            self._sub_lbl.setText("Switching to PostgreSQL…")
            QTimer.singleShot(1500, self.accept)
        else:
            self._bar.setRange(0, 1)
            self._bar.setValue(0)
            self._bar.setStyleSheet(
                f"QProgressBar {{ background:{BG4}; border:none; border-radius:4px; }}"
                f"QProgressBar::chunk {{ background:{RED}; border-radius:4px; }}"
            )
            self._msg_lbl.setText("Update failed.")
            self._msg_lbl.setStyleSheet(f"color:{RED}; font-size:13px; font-weight:600;")
            self._sub_lbl.setText("SQLite data preserved. See Intel Log for details.")
            self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
            self.show()   # re-show to apply flag change
            QTimer.singleShot(4000, self.accept)
