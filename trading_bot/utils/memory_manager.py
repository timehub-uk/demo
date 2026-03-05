"""
Memory manager for Apple Silicon unified memory architecture.
Monitors usage and triggers garbage collection / cache clearing
to stay within the 20 GB unified budget.
"""

from __future__ import annotations

import gc
import os
import threading
import time
from typing import Callable, Optional

import psutil
from loguru import logger


# 20 GB unified memory budget for Mac Mini M4
TOTAL_BUDGET_GB = 20.0
# Trigger cleanup when > 80% used
CLEANUP_THRESHOLD_PCT = 80.0
# Emergency mode when > 92%
EMERGENCY_THRESHOLD_PCT = 92.0


class MemoryManager:
    """Thread-safe memory monitor and cleanup coordinator."""

    _instance: "MemoryManager | None" = None

    def __new__(cls) -> "MemoryManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialised = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialised:
            return
        self._callbacks: list[Callable] = []
        self._caches: list[dict] = []       # weak refs to clearable caches
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False
        self._last_cleanup = 0.0
        self._initialised = True

    # ── Lifecycle ──────────────────────────────────────────────────────
    def start_monitoring(self, interval_sec: float = 30.0) -> None:
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval_sec,),
            daemon=True,
            name="memory-monitor",
        )
        self._monitor_thread.start()
        logger.info("MemoryManager monitoring started.")

    def stop(self) -> None:
        self._running = False

    # ── Stats ──────────────────────────────────────────────────────────
    @staticmethod
    def stats() -> dict:
        mem = psutil.virtual_memory()
        proc = psutil.Process(os.getpid())
        proc_mem = proc.memory_info()
        return {
            "system_total_gb": mem.total / 1e9,
            "system_used_gb": mem.used / 1e9,
            "system_avail_gb": mem.available / 1e9,
            "system_pct": mem.percent,
            "process_rss_mb": proc_mem.rss / 1e6,
            "process_vms_mb": proc_mem.vms / 1e6,
            "budget_gb": TOTAL_BUDGET_GB,
            "budget_used_pct": mem.percent,
        }

    # ── Cleanup ────────────────────────────────────────────────────────
    def register_cache(self, cache: dict) -> None:
        self._caches.append(cache)

    def on_pressure(self, callback: Callable) -> None:
        """Register callback invoked on memory pressure events."""
        self._callbacks.append(callback)

    def cleanup(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_cleanup < 30:
            return
        self._last_cleanup = now

        # Clear registered caches
        cleared = 0
        for cache in self._caches:
            size = len(cache)
            cache.clear()
            cleared += size

        # Force Python GC
        collected = gc.collect()

        # Try to free PyTorch GPU/MPS cache
        try:
            import torch
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

        logger.debug(f"Memory cleanup: {cleared} cache entries cleared, {collected} GC objects collected")

    def _monitor_loop(self, interval: float) -> None:
        while self._running:
            try:
                s = self.stats()
                pct = s["system_pct"]
                if pct >= EMERGENCY_THRESHOLD_PCT:
                    logger.warning(f"EMERGENCY memory pressure: {pct:.1f}% used!")
                    self.cleanup(force=True)
                    for cb in self._callbacks:
                        try:
                            cb({"level": "emergency", "pct": pct})
                        except Exception:
                            pass
                elif pct >= CLEANUP_THRESHOLD_PCT:
                    logger.info(f"Memory pressure: {pct:.1f}% – cleaning up…")
                    self.cleanup()
                    for cb in self._callbacks:
                        try:
                            cb({"level": "warning", "pct": pct})
                        except Exception:
                            pass
            except Exception as exc:
                logger.error(f"Memory monitor error: {exc}")
            time.sleep(interval)


_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
