"""
Master Orchestrator
===================
Coordinates all services, scheduling, dependencies, and failover.
Provides a central registry of all running service threads and their health.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class ServiceState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPING = "stopping"


@dataclass
class ServiceDescriptor:
    name: str
    start_fn: Callable
    stop_fn: Optional[Callable] = None
    health_fn: Optional[Callable[[], bool]] = None
    dependencies: List[str] = field(default_factory=list)
    restart_on_failure: bool = True
    max_restarts: int = 5
    restart_delay: float = 5.0
    state: ServiceState = ServiceState.STOPPED
    thread: Optional[threading.Thread] = None
    restart_count: int = 0
    last_error: Optional[str] = None


class MasterOrchestrator:
    """
    Central coordinator for all trading system services.

    Responsibilities:
    - Start/stop services in dependency order
    - Monitor service health
    - Auto-restart failed services
    - Provide system-wide state snapshot
    """

    def __init__(self):
        self._services: Dict[str, ServiceDescriptor] = {}
        self._lock = threading.RLock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False
        self._callbacks: List[Callable] = []

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        start_fn: Callable,
        stop_fn: Optional[Callable] = None,
        health_fn: Optional[Callable[[], bool]] = None,
        dependencies: Optional[List[str]] = None,
        restart_on_failure: bool = True,
        max_restarts: int = 5,
    ) -> None:
        with self._lock:
            self._services[name] = ServiceDescriptor(
                name=name,
                start_fn=start_fn,
                stop_fn=stop_fn,
                health_fn=health_fn,
                dependencies=dependencies or [],
                restart_on_failure=restart_on_failure,
                max_restarts=max_restarts,
            )
            logger.debug(f"[Orchestrator] Registered service: {name}")

    def on_state_change(self, callback: Callable) -> None:
        """Subscribe to service state change events."""
        self._callbacks.append(callback)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start_all(self) -> None:
        """Start all services in dependency order."""
        self._running = True
        order = self._resolve_start_order()
        for name in order:
            self._start_service(name)
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="orchestrator-monitor"
        )
        self._monitor_thread.start()
        logger.info(f"[Orchestrator] All services started ({len(order)} total)")

    def stop_all(self) -> None:
        """Stop all services in reverse dependency order."""
        self._running = False
        order = list(reversed(self._resolve_start_order()))
        for name in order:
            self._stop_service(name)
        logger.info("[Orchestrator] All services stopped")

    def start_service(self, name: str) -> bool:
        """Start a specific service."""
        return self._start_service(name)

    def stop_service(self, name: str) -> bool:
        """Stop a specific service."""
        return self._stop_service(name)

    def restart_service(self, name: str) -> bool:
        """Restart a specific service."""
        self._stop_service(name)
        time.sleep(1)
        return self._start_service(name)

    # ── State ─────────────────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, dict]:
        with self._lock:
            return {
                name: {
                    "state": svc.state.value,
                    "restart_count": svc.restart_count,
                    "last_error": svc.last_error,
                    "alive": svc.thread.is_alive() if svc.thread else False,
                }
                for name, svc in self._services.items()
            }

    def is_healthy(self) -> bool:
        with self._lock:
            return all(
                svc.state in (ServiceState.RUNNING, ServiceState.DEGRADED)
                for svc in self._services.values()
            )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _resolve_start_order(self) -> List[str]:
        """Topological sort based on dependencies."""
        visited: set = set()
        order: List[str] = []

        def visit(name: str):
            if name in visited:
                return
            visited.add(name)
            svc = self._services.get(name)
            if svc:
                for dep in svc.dependencies:
                    visit(dep)
            order.append(name)

        for name in self._services:
            visit(name)
        return order

    def _start_service(self, name: str) -> bool:
        with self._lock:
            svc = self._services.get(name)
            if not svc:
                logger.error(f"[Orchestrator] Unknown service: {name}")
                return False
            if svc.state == ServiceState.RUNNING:
                return True
            # Check dependencies
            for dep in svc.dependencies:
                dep_svc = self._services.get(dep)
                if dep_svc and dep_svc.state != ServiceState.RUNNING:
                    logger.warning(
                        f"[Orchestrator] Dependency {dep} not ready for {name}"
                    )
                    self._start_service(dep)

            svc.state = ServiceState.STARTING

        try:
            t = threading.Thread(
                target=self._run_service,
                args=(name,),
                daemon=True,
                name=f"svc-{name}",
            )
            t.start()
            with self._lock:
                svc.thread = t
                svc.state = ServiceState.RUNNING
            self._notify(name, ServiceState.RUNNING)
            logger.info(f"[Orchestrator] Started: {name}")
            return True
        except Exception as exc:
            with self._lock:
                svc.state = ServiceState.FAILED
                svc.last_error = str(exc)
            self._notify(name, ServiceState.FAILED)
            logger.error(f"[Orchestrator] Failed to start {name}: {exc}")
            return False

    def _run_service(self, name: str) -> None:
        svc = self._services[name]
        try:
            svc.start_fn()
        except Exception as exc:
            with self._lock:
                svc.state = ServiceState.FAILED
                svc.last_error = str(exc)
            self._notify(name, ServiceState.FAILED)
            logger.error(f"[Orchestrator] Service {name} crashed: {exc}")

    def _stop_service(self, name: str) -> bool:
        with self._lock:
            svc = self._services.get(name)
            if not svc:
                return False
            svc.state = ServiceState.STOPPING

        try:
            if svc.stop_fn:
                svc.stop_fn()
            with self._lock:
                svc.state = ServiceState.STOPPED
            logger.info(f"[Orchestrator] Stopped: {name}")
            return True
        except Exception as exc:
            logger.error(f"[Orchestrator] Error stopping {name}: {exc}")
            return False

    def _monitor_loop(self) -> None:
        while self._running:
            time.sleep(10)
            with self._lock:
                services = list(self._services.values())
            for svc in services:
                # Check thread alive
                if svc.state == ServiceState.RUNNING and svc.thread:
                    if not svc.thread.is_alive():
                        with self._lock:
                            svc.state = ServiceState.FAILED
                        self._notify(svc.name, ServiceState.FAILED)
                        if svc.restart_on_failure and svc.restart_count < svc.max_restarts:
                            logger.warning(
                                f"[Orchestrator] Auto-restarting {svc.name} "
                                f"(attempt {svc.restart_count + 1})"
                            )
                            time.sleep(svc.restart_delay)
                            with self._lock:
                                svc.restart_count += 1
                            self._start_service(svc.name)
                # Custom health check
                if svc.state == ServiceState.RUNNING and svc.health_fn:
                    try:
                        ok = svc.health_fn()
                        if not ok:
                            with self._lock:
                                svc.state = ServiceState.DEGRADED
                            self._notify(svc.name, ServiceState.DEGRADED)
                    except Exception:
                        pass

    def _notify(self, name: str, state: ServiceState) -> None:
        for cb in self._callbacks:
            try:
                cb(name, state)
            except Exception:
                pass


# Singleton
_orchestrator: Optional[MasterOrchestrator] = None


def get_orchestrator() -> MasterOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MasterOrchestrator()
    return _orchestrator
