"""
PostgreSQL connection manager using SQLAlchemy 2.x async + sync sessions.
Includes connection pooling tuned for Apple Silicon.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator

from loguru import logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from .models import Base

_lock = threading.Lock()
_engine = None
_SessionLocal = None


def init_db(db_url: str, pool_size: int = 10, max_overflow: int = 20) -> None:
    """Initialise the database engine, create tables if necessary."""
    global _engine, _SessionLocal

    with _lock:
        if _engine is not None:
            return

        _engine = create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
            connect_args={
                "connect_timeout": 10,
                "options": "-c statement_timeout=30000",
            },
        )

        @event.listens_for(_engine, "connect")
        def set_search_path(dbapi_conn, conn_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("SET search_path TO public")
            cursor.close()

        Base.metadata.create_all(_engine)
        _SessionLocal = sessionmaker(
            bind=_engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        logger.info("PostgreSQL connected and tables created.")


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Yield a database session, rolling back on exception."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised – call init_db() first.")
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class Database:
    """Convenience wrapper used by application services."""

    def __init__(self) -> None:
        if _engine is None:
            from config import get_settings
            s = get_settings()
            init_db(s.db_url, s.database.pool_size, s.database.max_overflow)

    # ------------------------------------------------------------------
    def execute_raw(self, sql: str, params: dict | None = None):
        with get_db() as db:
            result = db.execute(text(sql), params or {})
            return result.fetchall()

    def health_check(self) -> bool:
        try:
            with get_db() as db:
                db.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            logger.error(f"DB health check failed: {exc}")
            return False
