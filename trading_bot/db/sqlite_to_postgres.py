"""
SQLite → PostgreSQL migration utility.

When the app has been running on the SQLite fallback and PostgreSQL later
becomes available, this module copies every row from the local SQLite file
into the live PostgreSQL database, then renames the SQLite file to
``*.migrated`` so the migration is not re-triggered on subsequent starts.

Usage (called automatically by main.py / MainWindow):

    from db.sqlite_to_postgres import migrate_sqlite_to_postgres, sqlite_has_data
    if sqlite_has_data():
        migrate_sqlite_to_postgres(pg_url, progress_cb=..., done_cb=...)

``progress_cb(table: str, copied: int, total: int)`` is called from the
worker thread as each table is processed.
``done_cb(success: bool, message: str)`` is called when complete or on error.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from loguru import logger
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool, QueuePool

from .models import Base

# ── helpers ───────────────────────────────────────────────────────────────────

def _default_sqlite_path() -> Path:
    return Path(__file__).parent.parent / "data" / "binanceml_local.db"


def sqlite_has_data(db_path: str | None = None) -> bool:
    """Return True if the SQLite fallback file exists and has at least one row."""
    path = Path(db_path) if db_path else _default_sqlite_path()
    if not path.exists():
        return False
    try:
        eng = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        inspector = inspect(eng)
        for table in inspector.get_table_names():
            with eng.connect() as conn:
                count = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
                if count:
                    eng.dispose()
                    return True
        eng.dispose()
    except Exception:
        pass
    return False


def migrate_sqlite_to_postgres(
    pg_url: str,
    pg_pool_size: int = 5,
    pg_max_overflow: int = 10,
    sqlite_path: str | None = None,
    progress_cb: Callable[[str, int, int], None] | None = None,
    done_cb: Callable[[bool, str], None] | None = None,
) -> None:
    """
    Run the migration in a background thread.

    Copies all rows from SQLite into PostgreSQL using bulk INSERT with
    ON CONFLICT DO NOTHING so re-runs are safe.  When finished, renames
    the SQLite file to ``<name>.migrated`` to prevent future re-triggers.
    """
    thread = threading.Thread(
        target=_run_migration,
        args=(pg_url, pg_pool_size, pg_max_overflow, sqlite_path, progress_cb, done_cb),
        daemon=True,
        name="sqlite-pg-migration",
    )
    thread.start()


# ── core migration logic ──────────────────────────────────────────────────────

def _run_migration(
    pg_url: str,
    pg_pool_size: int,
    pg_max_overflow: int,
    sqlite_path: str | None,
    progress_cb: Callable[[str, int, int], None] | None,
    done_cb: Callable[[bool, str], None] | None,
) -> None:
    src_path = Path(sqlite_path) if sqlite_path else _default_sqlite_path()

    try:
        logger.info(f"Starting SQLite→PostgreSQL migration from {src_path}")

        # ── Open source (SQLite) ───────────────────────────────────────
        src_engine = create_engine(
            f"sqlite:///{src_path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        # ── Open destination (PostgreSQL) ─────────────────────────────
        from db.postgres import _ensure_database_exists
        _ensure_database_exists(pg_url)

        dst_engine = create_engine(
            pg_url,
            poolclass=QueuePool,
            pool_size=pg_pool_size,
            max_overflow=pg_max_overflow,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 10,
                "options": "-c statement_timeout=60000",
            },
        )
        # Ensure all tables exist on the PG side
        Base.metadata.create_all(dst_engine)

        inspector = inspect(src_engine)
        tables = inspector.get_table_names()

        # Migrate tables in dependency order (parents before children)
        ORDERED = [
            "users",
            "api_credentials",
            "portfolios",
            "ml_models",
            "training_sessions",
            "trades",
            "orders",
            "token_metrics",
            "tax_records",
            "pair_registry",
            "pair_ml_snapshots",
            "alerts",
        ]
        # Put known tables first, append any unexpected tables at the end
        ordered = [t for t in ORDERED if t in tables]
        ordered += [t for t in tables if t not in ordered]

        total_rows_copied = 0

        with src_engine.connect() as src_conn, dst_engine.connect() as dst_conn:
            for table in ordered:
                try:
                    total: int = src_conn.execute(
                        text(f'SELECT COUNT(*) FROM "{table}"')
                    ).scalar() or 0

                    if total == 0:
                        if progress_cb:
                            progress_cb(table, 0, 0)
                        continue

                    # Fetch all rows
                    rows = src_conn.execute(
                        text(f'SELECT * FROM "{table}"')
                    ).mappings().all()

                    if not rows:
                        continue

                    # Get column names from first row
                    columns = list(rows[0].keys())

                    # Build INSERT … ON CONFLICT DO NOTHING
                    col_list  = ", ".join(f'"{c}"' for c in columns)
                    val_list  = ", ".join(f":{c}" for c in columns)
                    stmt = text(
                        f'INSERT INTO "{table}" ({col_list}) '
                        f'VALUES ({val_list}) ON CONFLICT DO NOTHING'
                    )

                    # Batch insert (1000 rows at a time)
                    BATCH = 1000
                    copied = 0
                    for i in range(0, len(rows), BATCH):
                        batch = [dict(r) for r in rows[i : i + BATCH]]
                        dst_conn.execute(stmt, batch)
                        copied += len(batch)
                        if progress_cb:
                            progress_cb(table, copied, total)

                    dst_conn.commit()
                    total_rows_copied += copied
                    logger.info(f"Migrated table '{table}': {copied}/{total} rows")

                except Exception as tbl_exc:
                    logger.warning(f"Migration skipped table '{table}': {tbl_exc}")
                    if progress_cb:
                        progress_cb(table, 0, -1)   # -1 signals a skip/error

        src_engine.dispose()
        dst_engine.dispose()

        # ── Rename SQLite file so migration doesn't re-run ─────────────
        migrated_path = src_path.with_suffix(".db.migrated")
        src_path.rename(migrated_path)
        logger.info(
            f"Migration complete – {total_rows_copied} rows moved. "
            f"SQLite renamed to {migrated_path.name}"
        )

        if done_cb:
            done_cb(True, f"Migration complete – {total_rows_copied} rows copied to PostgreSQL.")

    except Exception as exc:
        logger.error(f"SQLite→PostgreSQL migration failed: {exc}")
        if done_cb:
            done_cb(False, f"Migration failed: {exc}")
