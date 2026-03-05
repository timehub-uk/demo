"""
Thread pool manager – tuned for Apple Silicon M4 (10-core CPU).
Provides named thread pools for IO, CPU, and ML workloads.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Any, Optional

import psutil
from loguru import logger


class ThreadManager:
    """
    Manages separate thread pools for:
    - IO-bound tasks  (network, disk) – 2× CPU cores
    - CPU-bound tasks (data processing) – CPU cores
    - ML training     – limited to avoid thermal throttling on M4
    """

    _instance: "ThreadManager | None" = None

    def __new__(cls) -> "ThreadManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialised = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialised:
            return
        n_cpu = os.cpu_count() or 4
        n_perf = min(n_cpu, 10)   # P-cores on M4 Mac Mini = 4–6

        self._io_pool = ThreadPoolExecutor(
            max_workers=n_perf * 2, thread_name_prefix="io"
        )
        self._cpu_pool = ThreadPoolExecutor(
            max_workers=n_perf, thread_name_prefix="cpu"
        )
        self._ml_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="ml"   # Limit ML to 2 threads
        )
        self._scheduled: list[threading.Timer] = []
        self._lock = threading.Lock()
        self._initialised = True
        logger.info(f"ThreadManager initialised | CPU cores: {n_cpu} | IO workers: {n_perf*2}")

    # ── Task submission ─────────────────────────────────────────────────
    def submit_io(self, fn: Callable, *args, **kwargs) -> Future:
        return self._io_pool.submit(fn, *args, **kwargs)

    def submit_cpu(self, fn: Callable, *args, **kwargs) -> Future:
        return self._cpu_pool.submit(fn, *args, **kwargs)

    def submit_ml(self, fn: Callable, *args, **kwargs) -> Future:
        return self._ml_pool.submit(fn, *args, **kwargs)

    def schedule(self, delay: float, fn: Callable, *args) -> threading.Timer:
        """Schedule a function to run after `delay` seconds."""
        timer = threading.Timer(delay, fn, args=args)
        timer.daemon = True
        timer.start()
        with self._lock:
            self._scheduled.append(timer)
            self._scheduled = [t for t in self._scheduled if t.is_alive()]
        return timer

    def repeat(self, interval: float, fn: Callable, *args) -> threading.Thread:
        """Run fn every `interval` seconds in a daemon thread."""
        def _loop():
            import time
            while True:
                try:
                    fn(*args)
                except Exception as exc:
                    logger.error(f"repeat() task error: {exc}")
                time.sleep(interval)
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        return t

    # ── System stats ────────────────────────────────────────────────────
    @staticmethod
    def system_stats() -> dict:
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)
        return {
            "cpu_pct": cpu,
            "cpu_cores": os.cpu_count(),
            "mem_total_gb": mem.total / 1e9,
            "mem_used_gb": mem.used / 1e9,
            "mem_avail_gb": mem.available / 1e9,
            "mem_pct": mem.percent,
        }

    def shutdown(self) -> None:
        self._io_pool.shutdown(wait=False)
        self._cpu_pool.shutdown(wait=False)
        self._ml_pool.shutdown(wait=False)
        logger.info("ThreadManager shutdown complete.")


_thread_manager: ThreadManager | None = None


def get_thread_manager() -> ThreadManager:
    global _thread_manager
    if _thread_manager is None:
        _thread_manager = ThreadManager()
    return _thread_manager
