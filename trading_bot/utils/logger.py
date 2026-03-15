"""
Centralised logging setup + IntelLogger – the live dynamic activity log
that powers the Intel Log UI panel.
"""

from __future__ import annotations

import sys
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

LOG_DIR = Path.home() / ".binanceml" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Max entries kept in memory for the Intel Log panel
INTEL_LOG_BUFFER_SIZE = 5000


def setup_logger(level: str = "INFO") -> None:
    """Configure loguru for file + console output."""
    logger.remove()

    # Console (rich)
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> – <level>{message}</level>"
        ),
        colorize=True,
    )

    # Rotating file
    logger.add(
        LOG_DIR / "app_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        compression="gz",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} – {message}",
    )

    # Error file
    logger.add(
        LOG_DIR / "errors.log",
        level="ERROR",
        rotation="10 MB",
        retention="60 days",
        compression="gz",
    )

    logger.info("Logger initialised.")


# ── Intel Logger ────────────────────────────────────────────────────────────

class IntelLogEntry:
    """A single log entry in the Intel Log."""
    __slots__ = ("ts", "level", "category", "source", "message", "data")

    LEVEL_ICONS = {
        "DEBUG":    "🔵",
        "INFO":     "⚪",
        "SUCCESS":  "🟢",
        "WARNING":  "🟡",
        "ERROR":    "🔴",
        "CRITICAL": "🚨",
        "TRADE":    "💰",
        "SIGNAL":   "📡",
        "ML":       "🤖",
        "TAX":      "📋",
        "SYSTEM":   "⚙️",
        "API":      "🔌",
        "WEBHOOK":  "🪝",
    }

    def __init__(
        self,
        level: str,
        category: str,
        source: str,
        message: str,
        data: dict | None = None,
    ) -> None:
        self.ts = datetime.now(timezone.utc)
        self.level = level
        self.category = category
        self.source = source
        self.message = message
        self.data = data or {}

    @property
    def icon(self) -> str:
        return self.LEVEL_ICONS.get(self.level, "⚪")

    @property
    def ts_str(self) -> str:
        return self.ts.strftime("%H:%M:%S.%f")[:-3]

    def to_dict(self) -> dict:
        return {
            "ts": self.ts.isoformat(),
            "level": self.level,
            "category": self.category,
            "source": self.source,
            "message": self.message,
            "data": self.data,
        }


class IntelLogger:
    """
    Real-time activity log aggregator.
    All application events are funnelled here and emitted
    to registered UI callbacks.

    Categories:
        TRADE | SIGNAL | ML | TAX | SYSTEM | API | WEBHOOK | ORDER
    """

    _instance: "IntelLogger | None" = None

    def __new__(cls) -> "IntelLogger":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialised = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialised:
            return
        self._buffer: deque[IntelLogEntry] = deque(maxlen=INTEL_LOG_BUFFER_SIZE)
        self._callbacks: list[Callable[[IntelLogEntry], None]] = []
        self._lock = threading.Lock()
        self._filters: dict[str, bool] = {}   # category → visible
        self._initialised = True

    # ── Logging ─────────────────────────────────────────────────────────
    def log(
        self,
        level: str,
        category: str,
        source: str,
        message: str,
        data: dict | None = None,
    ) -> IntelLogEntry:
        entry = IntelLogEntry(level, category, source, message, data)
        with self._lock:
            self._buffer.append(entry)
        self._dispatch(entry)
        # Mirror to loguru
        log_fn = getattr(logger, level.lower(), logger.info)
        log_fn(f"[{category}] [{source}] {message}")
        return entry

    # ── Convenience methods ──────────────────────────────────────────────
    def trade(self, source: str, message: str, data: dict | None = None) -> None:
        self.log("TRADE", "TRADE", source, message, data)

    def signal(self, source: str, message: str, data: dict | None = None) -> None:
        self.log("SIGNAL", "SIGNAL", source, message, data)

    def ml(self, source: str, message: str, data: dict | None = None) -> None:
        self.log("ML", "ML", source, message, data)

    def tax(self, source: str, message: str, data: dict | None = None) -> None:
        self.log("TAX", "TAX", source, message, data)

    def system(self, source: str, message: str, data: dict | None = None) -> None:
        self.log("SYSTEM", "SYSTEM", source, message, data)

    def api(self, source: str, message: str, data: dict | None = None) -> None:
        self.log("API", "API", source, message, data)

    def webhook(self, source: str, message: str, data: dict | None = None) -> None:
        self.log("WEBHOOK", "WEBHOOK", source, message, data)

    def info(self, source: str, message: str) -> None:
        self.log("INFO", "SYSTEM", source, message)

    def warning(self, source: str, message: str) -> None:
        self.log("WARNING", "SYSTEM", source, message)

    def error(self, source: str, message: str, data: dict | None = None) -> None:
        self.log("ERROR", "SYSTEM", source, message, data)

    def success(self, source: str, message: str, data: dict | None = None) -> None:
        self.log("SUCCESS", "SYSTEM", source, message, data)

    # ── Subscription ─────────────────────────────────────────────────────
    def subscribe(self, callback: Callable[[IntelLogEntry], None]) -> None:
        """Register a callback invoked on every new log entry."""
        with self._lock:
            self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        with self._lock:
            self._callbacks = [c for c in self._callbacks if c != callback]

    # ── Query ──────────────────────────────────────────────────────────
    def recent(self, n: int = 100, category: str | None = None) -> list[IntelLogEntry]:
        with self._lock:
            entries = list(self._buffer)
        if category:
            entries = [e for e in entries if e.category == category]
        return entries[-n:]

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()

    def export_json(self, path: Path) -> None:
        import json
        with self._lock:
            data = [e.to_dict() for e in self._buffer]
        path.write_text(json.dumps(data, indent=2, default=str))

    # ── Internal ─────────────────────────────────────────────────────────
    def _dispatch(self, entry: IntelLogEntry) -> None:
        with self._lock:
            callbacks = list(self._callbacks)
        for cb in callbacks:
            try:
                cb(entry)
            except Exception as _cb_exc:
                # Use the stdlib logger to avoid recursion with IntelLogger itself
                import logging as _stdlib_logging
                _stdlib_logging.getLogger(__name__).warning(
                    "IntelLogger callback raised an exception: %s", _cb_exc
                )


_intel_logger: IntelLogger | None = None


def get_intel_logger() -> IntelLogger:
    global _intel_logger
    if _intel_logger is None:
        _intel_logger = IntelLogger()
    return _intel_logger
