"""
Service Health Monitor
======================
Tracks process uptime, queue health, memory, CPU, API availability,
and degraded modes across all running services.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False


@dataclass
class HealthMetric:
    name: str
    value: Any
    unit: str = ""
    ok: bool = True
    threshold: Optional[float] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ServiceHealth:
    name: str
    alive: bool = True
    degraded: bool = False
    metrics: Dict[str, HealthMetric] = field(default_factory=dict)
    last_check: float = field(default_factory=time.time)
    error: Optional[str] = None


class ServiceHealthMonitor:
    """
    Continuously polls all registered services and system resources.

    Reports:
    - CPU / memory / disk usage
    - Thread / queue depths
    - Exchange API ping latency
    - DB connection pool status
    - Custom health probes
    """

    def __init__(self, poll_interval: float = 30.0):
        self._services: Dict[str, ServiceHealth] = {}
        self._probes: Dict[str, Callable[[], HealthMetric]] = {}
        self._lock = threading.RLock()
        self._poll_interval = poll_interval
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._alert_callbacks: List[Callable] = []

    # ── Registration ──────────────────────────────────────────────────────────

    def register_service(self, name: str) -> None:
        with self._lock:
            self._services[name] = ServiceHealth(name=name)

    def add_probe(self, name: str, probe_fn: Callable[[], HealthMetric]) -> None:
        """Add a custom health probe function."""
        with self._lock:
            self._probes[name] = probe_fn

    def on_alert(self, callback: Callable[[str, ServiceHealth], None]) -> None:
        self._alert_callbacks.append(callback)

    # ── Control ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="health-monitor"
        )
        self._thread.start()
        logger.info("[HealthMonitor] Started")

    def stop(self) -> None:
        self._running = False

    # ── Snapshots ────────────────────────────────────────────────────────────

    def get_system_metrics(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}
        if _PSUTIL:
            try:
                metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
                mem = psutil.virtual_memory()
                metrics["mem_used_gb"] = round(mem.used / 1e9, 2)
                metrics["mem_percent"] = mem.percent
                disk = psutil.disk_usage("/")
                metrics["disk_percent"] = disk.percent
                metrics["thread_count"] = threading.active_count()
            except Exception as exc:
                metrics["error"] = str(exc)
        else:
            metrics["thread_count"] = threading.active_count()
            metrics["pid"] = os.getpid()
        return metrics

    def get_service_health(self, name: str) -> Optional[ServiceHealth]:
        with self._lock:
            return self._services.get(name)

    def get_all_health(self) -> Dict[str, ServiceHealth]:
        with self._lock:
            return dict(self._services)

    def is_system_healthy(self) -> bool:
        with self._lock:
            return all(
                sh.alive and not sh.degraded
                for sh in self._services.values()
            )

    def update_service(self, name: str, alive: bool, degraded: bool = False,
                       error: Optional[str] = None) -> None:
        with self._lock:
            if name not in self._services:
                self._services[name] = ServiceHealth(name=name)
            sh = self._services[name]
            sh.alive = alive
            sh.degraded = degraded
            sh.error = error
            sh.last_check = time.time()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while self._running:
            self._run_probes()
            self._check_system()
            time.sleep(self._poll_interval)

    def _run_probes(self) -> None:
        with self._lock:
            probes = dict(self._probes)
        for name, probe_fn in probes.items():
            try:
                metric = probe_fn()
                with self._lock:
                    if name not in self._services:
                        self._services[name] = ServiceHealth(name=name)
                    self._services[name].metrics[metric.name] = metric
                    self._services[name].last_check = time.time()
                    if not metric.ok:
                        self._services[name].degraded = True
                        self._fire_alert(name, self._services[name])
            except Exception as exc:
                logger.debug(f"[HealthMonitor] Probe {name} error: {exc}")

    def _check_system(self) -> None:
        if not _PSUTIL:
            return
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory().percent
            if cpu > 90 or mem > 90:
                logger.warning(
                    f"[HealthMonitor] High resource usage – CPU {cpu:.0f}% MEM {mem:.0f}%"
                )
        except Exception:
            pass

    def _fire_alert(self, name: str, health: ServiceHealth) -> None:
        for cb in self._alert_callbacks:
            try:
                cb(name, health)
            except Exception:
                pass


# Singleton
_monitor: Optional[ServiceHealthMonitor] = None


def get_health_monitor() -> ServiceHealthMonitor:
    global _monitor
    if _monitor is None:
        _monitor = ServiceHealthMonitor()
    return _monitor
