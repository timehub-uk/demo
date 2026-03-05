"""
Webhook manager – dispatches event notifications to registered external URLs.
Supports retry logic with exponential backoff.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests
from loguru import logger

from utils.logger import get_intel_logger


@dataclass
class WebhookEndpoint:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    url: str = ""
    events: list[str] = field(default_factory=list)
    secret: str = ""
    active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    success_count: int = 0
    failure_count: int = 0
    last_triggered: Optional[str] = None


@dataclass
class WebhookEvent:
    event: str
    data: dict
    timestamp: float = field(default_factory=time.time)


class WebhookManager:
    """
    Thread-safe webhook dispatcher with:
    - Multiple endpoint registration
    - Event filtering
    - Exponential-backoff retries (up to 5 attempts)
    - HMAC-SHA256 request signing
    """

    def __init__(self) -> None:
        self._endpoints: dict[str, WebhookEndpoint] = {}
        self._queue: list[WebhookEvent] = []
        self._lock = threading.Lock()
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop, daemon=True, name="webhook-dispatcher"
        )
        self._dispatch_thread.start()
        self._intel = get_intel_logger()

    # ── Registration ────────────────────────────────────────────────────
    def register(self, url: str, events: list[str], secret: str = "") -> WebhookEndpoint:
        ep = WebhookEndpoint(url=url, events=events, secret=secret)
        with self._lock:
            self._endpoints[ep.id] = ep
        logger.info(f"Webhook registered: {url} events={events}")
        return ep

    def unregister(self, endpoint_id: str) -> bool:
        with self._lock:
            if endpoint_id in self._endpoints:
                del self._endpoints[endpoint_id]
                return True
        return False

    def list_webhooks(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "id": ep.id, "url": ep.url,
                    "events": ep.events, "active": ep.active,
                    "success": ep.success_count, "failures": ep.failure_count,
                    "created_at": ep.created_at,
                }
                for ep in self._endpoints.values()
            ]

    # ── Event dispatch ──────────────────────────────────────────────────
    def emit(self, event: str, data: dict) -> None:
        """Queue an event for delivery to all matching endpoints."""
        ev = WebhookEvent(event=event, data=data)
        with self._lock:
            self._queue.append(ev)

    # ── Pre-built emitters ───────────────────────────────────────────────
    def emit_trade(self, trade: dict) -> None:
        self.emit("TRADE", trade)

    def emit_signal(self, signal: dict) -> None:
        self.emit("SIGNAL", signal)

    def emit_ml_update(self, update: dict) -> None:
        self.emit("ML_UPDATE", update)

    def emit_alert(self, alert: dict) -> None:
        self.emit("ALERT", alert)

    # ── Background dispatcher ────────────────────────────────────────────
    def _dispatch_loop(self) -> None:
        while True:
            with self._lock:
                if self._queue:
                    ev = self._queue.pop(0)
                else:
                    ev = None
            if ev:
                self._deliver(ev)
            else:
                time.sleep(0.1)

    def _deliver(self, ev: WebhookEvent) -> None:
        with self._lock:
            endpoints = [
                ep for ep in self._endpoints.values()
                if ep.active and (not ep.events or ev.event in ep.events)
            ]

        for ep in endpoints:
            threading.Thread(
                target=self._send_with_retry,
                args=(ep, ev),
                daemon=True,
            ).start()

    def _send_with_retry(self, ep: WebhookEndpoint, ev: WebhookEvent) -> None:
        payload = {
            "event": ev.event,
            "timestamp": ev.timestamp,
            "data": ev.data,
        }
        body = json.dumps(payload, default=str)
        headers = {"Content-Type": "application/json"}

        if ep.secret:
            import hmac, hashlib
            sig = hmac.new(ep.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            headers["X-BinanceML-Signature"] = f"sha256={sig}"

        max_attempts = 5
        delay = 1.0
        for attempt in range(max_attempts):
            try:
                resp = requests.post(ep.url, data=body, headers=headers, timeout=10)
                resp.raise_for_status()
                with self._lock:
                    ep.success_count += 1
                    ep.last_triggered = datetime.now(timezone.utc).isoformat()
                self._intel.webhook(
                    "WebhookManager",
                    f"Delivered {ev.event} to {ep.url} (attempt {attempt+1})"
                )
                return
            except Exception as exc:
                logger.warning(f"Webhook delivery failed [{ep.url}] attempt {attempt+1}: {exc}")
                if attempt < max_attempts - 1:
                    time.sleep(delay)
                    delay = min(delay * 2, 30)

        with self._lock:
            ep.failure_count += 1
        self._intel.error("WebhookManager", f"Webhook failed after {max_attempts} attempts: {ep.url}")


_webhook_manager: WebhookManager | None = None


def get_webhook_manager() -> WebhookManager:
    global _webhook_manager
    if _webhook_manager is None:
        _webhook_manager = WebhookManager()
    return _webhook_manager
