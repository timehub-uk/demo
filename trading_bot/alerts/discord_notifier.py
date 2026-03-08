"""
Discord Webhook Notifier.

Sends rich embed messages to a Discord channel via an incoming webhook URL.
Configure the webhook URL in Settings → Notifications → Discord.

No external library required – uses urllib directly.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.request
from typing import Optional

from loguru import logger
from utils.logger import get_intel_logger


class DiscordNotifier:
    """
    Queued Discord webhook sender.

    All public methods are non-blocking – they enqueue a message that is
    sent by a background daemon thread.
    """

    RATE_LIMIT_SEC = 1.5      # Discord allows ~5 req/s; we stay conservative
    MAX_QUEUE = 100

    def __init__(self) -> None:
        self._intel = get_intel_logger()
        self._webhook_url: Optional[str] = None
        self._cfg = None
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=self.MAX_QUEUE)
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        try:
            from config import get_settings
            settings = get_settings()
            self._cfg = settings.notifications
            self._webhook_url = self._cfg.discord_webhook_url or None
        except Exception:
            pass

        if not self._webhook_url:
            self._intel.system("Discord", "Discord not configured – skipping")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="discord-notifier"
        )
        self._thread.start()
        self._intel.system("Discord", "Discord notifier started")

    def stop(self) -> None:
        self._running = False

    @property
    def enabled(self) -> bool:
        return bool(self._webhook_url and self._running)

    # ── Alert helpers ──────────────────────────────────────────────────

    def send_trade_alert(self, action: str, symbol: str, price: float,
                         qty: float, pnl: Optional[float] = None) -> None:
        if not self.enabled or not (self._cfg and self._cfg.discord_trade_alerts):
            return
        color = 0x00C853 if action == "BUY" else 0xD50000
        pnl_field = [{"name": "P&L", "value": f"`{pnl:+,.2f} USDT`", "inline": True}] if pnl is not None else []
        self._enqueue({
            "embeds": [{
                "title": f"{'🟢' if action == 'BUY' else '🔴'} {action} {symbol}",
                "color": color,
                "fields": [
                    {"name": "Price",    "value": f"`{price:,.4f} USDT`", "inline": True},
                    {"name": "Quantity", "value": f"`{qty:.6f}`",          "inline": True},
                ] + pnl_field,
                "footer": {"text": "BinanceML Pro"},
                "timestamp": _utcnow(),
            }]
        })

    def send_signal_alert(self, signal: str, symbol: str, confidence: float) -> None:
        if not self.enabled or not (self._cfg and self._cfg.discord_signal_alerts):
            return
        if confidence < 0.70:
            return
        color = 0x00C853 if signal == "BUY" else 0xD50000 if signal == "SELL" else 0x757575
        self._enqueue({
            "embeds": [{
                "title": f"ML Signal: {signal} {symbol}",
                "color": color,
                "fields": [{"name": "Confidence", "value": f"`{confidence:.0%}`", "inline": True}],
                "footer": {"text": "BinanceML Pro"},
                "timestamp": _utcnow(),
            }]
        })

    def send_whale_alert(self, event_type: str, symbol: str,
                         volume_usd: float, confidence: float) -> None:
        if not self.enabled or not (self._cfg and self._cfg.discord_whale_alerts):
            return
        self._enqueue({
            "embeds": [{
                "title": f"🐳 WHALE: {event_type} {symbol}",
                "color": 0x1565C0,
                "fields": [
                    {"name": "Volume",     "value": f"`${volume_usd:,.0f}`",     "inline": True},
                    {"name": "Confidence", "value": f"`{confidence:.0%}`",        "inline": True},
                ],
                "footer": {"text": "BinanceML Pro"},
                "timestamp": _utcnow(),
            }]
        })

    def send_daily_report(self, daily_pnl: float, trades: int, win_rate: float) -> None:
        if not self.enabled or not (self._cfg and self._cfg.discord_daily_report):
            return
        color = 0x00C853 if daily_pnl >= 0 else 0xD50000
        self._enqueue({
            "embeds": [{
                "title": "📊 Daily P&L Report",
                "color": color,
                "fields": [
                    {"name": "P&L",      "value": f"`{daily_pnl:+,.2f} USDT`", "inline": True},
                    {"name": "Trades",   "value": f"`{trades}`",                "inline": True},
                    {"name": "Win Rate", "value": f"`{win_rate:.0%}`",           "inline": True},
                ],
                "footer": {"text": "BinanceML Pro"},
                "timestamp": _utcnow(),
            }]
        })

    def send_layer_results(self, layer: int, results: dict) -> None:
        """Send ML layer results as a Discord embed."""
        if not self.enabled:
            return
        tools = results.get("tools", {})
        fields = []
        for name, data in list(tools.items())[:10]:
            if isinstance(data, dict):
                val = "\n".join(f"`{k}`: {v}" for k, v in list(data.items())[:3] if not isinstance(v, (dict, list)))
            else:
                val = str(data)
            fields.append({"name": name.replace("_", " ").title(), "value": val or "—", "inline": False})
        self._enqueue({
            "embeds": [{
                "title": f"Layer {layer} – {results.get('name', '')}",
                "color": int(results.get("color", "#00D4FF").lstrip("#"), 16),
                "fields": fields or [{"name": "Status", "value": "No data available", "inline": False}],
                "footer": {"text": "BinanceML Pro"},
                "timestamp": _utcnow(),
            }]
        })

    def send_text(self, message: str) -> None:
        if not self.enabled:
            return
        self._enqueue({"content": message[:2000]})

    # ── Internal ───────────────────────────────────────────────────────

    def _enqueue(self, payload: dict) -> None:
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            pass

    def _worker(self) -> None:
        while self._running:
            try:
                payload = self._queue.get(timeout=1.0)
                self._send(payload)
                self._queue.task_done()
                time.sleep(self.RATE_LIMIT_SEC)
            except queue.Empty:
                continue
            except Exception as exc:
                logger.debug(f"Discord send error: {exc}")

    def _send(self, payload: dict) -> None:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self._webhook_url, data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


_discord_singleton: DiscordNotifier | None = None


def get_discord_notifier() -> DiscordNotifier:
    global _discord_singleton
    if _discord_singleton is None:
        _discord_singleton = DiscordNotifier()
    return _discord_singleton
