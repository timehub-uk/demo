"""
Database Migration Dialog  –  SQLite → PostgreSQL

Shows a progress dialog while the background migration thread copies rows.
Displays per-table progress with a scrollable log and an overall progress bar.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QFrame,
)

from ui.styles import (
    ACCENT, ACCENT2, GREEN, RED, YELLOW, ORANGE,
    BG2, BG3, BG4, BORDER, BORDER2, FG0, FG1, FG2,
)
from ui.icons import svg_pixmap


class _MigrationSignals(QObject):
    """Cross-thread signals for updating the dialog from the worker thread."""
    table_progress = pyqtSignal(str, int, int)   # table, copied, total
    finished       = pyqtSignal(bool, str)        # success, message


class DbMigrationDialog(QDialog):
    """
    Modal progress dialog for the SQLite → PostgreSQL migration.

    After construction call ``run(pg_url)`` to kick off the migration.
    The dialog closes automatically on success; on failure it stays open
    and shows an error summary.
    """

    def __init__(self, pg_url: str, pg_pool_size: int = 5, pg_max_overflow: int = 10, parent=None) -> None:
        super().__init__(parent)
        self._pg_url         = pg_url
        self._pg_pool_size   = pg_pool_size
        self._pg_max_overflow = pg_max_overflow
        self._signals        = _MigrationSignals()
        self._signals.table_progress.connect(self._on_table_progress)
        self._signals.finished.connect(self._on_finished)
        self._table_counts: dict[str, tuple[int, int]] = {}   # table → (copied, total)
        self._done = False

        self.setWindowTitle("Database Migration")
        self.setMinimumSize(520, 400)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setStyleSheet(
            f"QDialog {{ background:{BG2}; color:{FG0}; border:1px solid {BORDER}; border-radius:8px; }}"
        )

        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Header
        hdr = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(svg_pixmap("database", ACCENT, 26))
        icon.setFixedSize(32, 32)
        hdr.addWidget(icon)

        title = QLabel("Migrating SQLite → PostgreSQL")
        title.setStyleSheet(f"color:{FG0}; font-size:14px; font-weight:700;")
        hdr.addWidget(title)
        hdr.addStretch()
        layout.addLayout(hdr)

        subtitle = QLabel(
            "PostgreSQL is now available. Copying your local data to the "
            "PostgreSQL database – this may take a moment."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color:{FG2}; font-size:11px;")
        layout.addWidget(subtitle)

        # Overall progress bar
        prog_row = QHBoxLayout()
        prog_lbl = QLabel("Overall:")
        prog_lbl.setStyleSheet(f"color:{FG2}; font-size:11px; min-width:55px;")
        prog_row.addWidget(prog_lbl)

        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, 100)
        self._overall_bar.setValue(0)
        self._overall_bar.setFixedHeight(10)
        self._overall_bar.setTextVisible(False)
        self._overall_bar.setStyleSheet(
            f"QProgressBar {{ background:{BG4}; border:none; border-radius:5px; }}"
            f"QProgressBar::chunk {{ background:{ACCENT}; border-radius:5px; }}"
        )
        prog_row.addWidget(self._overall_bar, 1)

        self._pct_lbl = QLabel("0%")
        self._pct_lbl.setStyleSheet(f"color:{FG2}; font-size:10px; font-family:monospace; min-width:32px;")
        prog_row.addWidget(self._pct_lbl)
        layout.addLayout(prog_row)

        # Current table label
        self._current_lbl = QLabel("Preparing…")
        self._current_lbl.setStyleSheet(f"color:{YELLOW}; font-size:11px; font-weight:600;")
        layout.addWidget(self._current_lbl)

        # Scrollable log
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            f"QTextEdit {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; font-family:monospace; font-size:10px; }}"
        )
        self._log.setMinimumHeight(140)
        layout.addWidget(self._log, 1)

        # Status / close button row
        btn_row = QHBoxLayout()
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        btn_row.addWidget(self._status_lbl, 1)

        self._close_btn = QPushButton("Running…")
        self._close_btn.setEnabled(False)
        self._close_btn.setFixedSize(110, 30)
        self._close_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{FG2}; border:1px solid {BORDER}; "
            f"border-radius:4px; font-size:11px; }}"
            f"QPushButton:enabled {{ background:{ACCENT}; color:#000; border:none; font-weight:700; }}"
            f"QPushButton:enabled:hover {{ background:{ACCENT2}; }}"
        )
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

    # ── Public API ────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the migration worker thread and show the dialog."""
        from db.sqlite_to_postgres import migrate_sqlite_to_postgres
        migrate_sqlite_to_postgres(
            pg_url=self._pg_url,
            pg_pool_size=self._pg_pool_size,
            pg_max_overflow=self._pg_max_overflow,
            progress_cb=self._signals.table_progress.emit,
            done_cb=self._signals.finished.emit,
        )
        self.exec()

    # ── Slots (GUI thread) ────────────────────────────────────────────

    def _on_table_progress(self, table: str, copied: int, total: int) -> None:
        if total < 0:
            # -1 signals a skipped/errored table
            self._log.append(
                f'<span style="color:{YELLOW};">⚠  {table}: skipped (error or unsupported)</span>'
            )
            return

        if total == 0:
            self._log.append(f'<span style="color:{FG2};">·  {table}: empty — skipped</span>')
            return

        self._current_lbl.setText(f"Migrating: {table}  ({copied}/{total})")
        self._table_counts[table] = (copied, total)

        if copied >= total:
            self._log.append(
                f'<span style="color:{GREEN};">✓  {table}: {copied} rows</span>'
            )

        # Recompute overall percentage across all tracked tables
        total_all  = sum(t for _, t in self._table_counts.values() if t > 0)
        copied_all = sum(c for c, t in self._table_counts.values() if t > 0)
        if total_all > 0:
            pct = int(copied_all / total_all * 100)
            self._overall_bar.setValue(pct)
            self._pct_lbl.setText(f"{pct}%")

    def _on_finished(self, success: bool, message: str) -> None:
        self._done = True
        if success:
            self._overall_bar.setValue(100)
            self._pct_lbl.setText("100%")
            self._current_lbl.setText("Migration complete.")
            self._current_lbl.setStyleSheet(f"color:{GREEN}; font-size:11px; font-weight:600;")
            self._log.append(f'<br><span style="color:{GREEN}; font-weight:bold;">✓ {message}</span>')
            self._status_lbl.setText("PostgreSQL is now the active database.")
            self._close_btn.setText("Continue")
            self._close_btn.setEnabled(True)
            # Auto-close after 3 seconds
            QTimer.singleShot(3000, self.accept)
        else:
            self._current_lbl.setText("Migration failed.")
            self._current_lbl.setStyleSheet(f"color:{RED}; font-size:11px; font-weight:600;")
            self._log.append(f'<br><span style="color:{RED}; font-weight:bold;">✗ {message}</span>')
            self._status_lbl.setText("SQLite data preserved. Check logs for details.")
            self._close_btn.setText("Close")
            self._close_btn.setEnabled(True)
