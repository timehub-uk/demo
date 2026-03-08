"""
Slack Incoming Webhook Notifier.

Posts messages to a Slack channel via an incoming webhook URL.
Configure in Settings → Notifications → Slack.

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


class SlackNotifier:
    """Queued Slack webhook sender."""

    RATE_LIMIT_SEC = 1.0
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
            self._webhook_url = self._cfg.slack_webhook_url or None
        except Exception:
            pass

        if not self._webhook_url:
            self._intel.system("Slack", "Slack not configured – skipping")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="slack-notifier"
        )
        self._thread.start()
        self._intel.system("Slack", "Slack notifier started")

    def stop(self) -> None:
        self._running = False

    @property
    def enabled(self) -> bool:
        return bool(self._webhook_url and self._running)

    # ── Alert helpers ──────────────────────────────────────────────────

    def send_trade_alert(self, action: str, symbol: str, price: float,
                         qty: float, pnl: Optional[float] = None) -> None:
        if not self.enabled or not (self._cfg and self._cfg.slack_trade_alerts):
            return
        emoji = ":large_green_circle:" if action == "BUY" else ":red_circle:"
        pnl_text = f"   P&L: *{pnl:+,.2f} USDT*" if pnl is not None else ""
        self._enqueue({
            "blocks": [{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji} *{action} {symbol}*\n"
                        f"Price: `{price:,.4f} USDT`   Qty: `{qty:.6f}`{pnl_text}"
                    ),
                },
            }]
        })

    def send_signal_alert(self, signal: str, symbol: str, confidence: float) -> None:
        if not self.enabled or not (self._cfg and self._cfg.slack_signal_alerts):
            return
        if confidence < 0.70:
            return
        emoji = ":chart_with_upwards_trend:" if signal == "BUY" else ":chart_with_downwards_trend:"
        self._enqueue({
            "text": f"{emoji} ML Signal: *{signal} {symbol}* ({confidence:.0%})"
        })

    def send_whale_alert(self, event_type: str, symbol: str,
                         volume_usd: float, confidence: float) -> None:
        if not self.enabled:
            return
        self._enqueue({
            "text": (
                f":whale: *WHALE: {event_type}* – {symbol}\n"
                f"Volume: `${volume_usd:,.0f}`   Confidence: `{confidence:.0%}`"
            )
        })

    def send_daily_report(self, daily_pnl: float, trades: int, win_rate: float) -> None:
        if not self.enabled or not (self._cfg and self._cfg.slack_daily_report):
            return
        emoji = ":chart_with_upwards_trend:" if daily_pnl >= 0 else ":chart_with_downwards_trend:"
        self._enqueue({
            "blocks": [{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji} *Daily P&L Report*\n"
                        f"P&L: `{daily_pnl:+,.2f} USDT`   "
                        f"Trades: `{trades}`   Win Rate: `{win_rate:.0%}`"
                    ),
                },
            }]
        })

    def send_layer_results(self, layer: int, results: dict) -> None:
        """Send ML layer results to Slack."""
        if not self.enabled:
            return
        tools = results.get("tools", {})
        lines = [f"*Layer {layer} – {results.get('name', '')}*"]
        for name, data in list(tools.items())[:8]:
            lines.append(f"• *{name.replace('_', ' ').title()}*")
            if isinstance(data, dict):
                for k, v in list(data.items())[:2]:
                    if not isinstance(v, (dict, list)):
                        lines.append(f"   `{k}`: {v}")
        self._enqueue({"text": "\n".join(lines)[:3000]})

    def send_text(self, message: str) -> None:
        if not self.enabled:
            return
        self._enqueue({"text": message[:3000]})

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
                logger.debug(f"Slack send error: {exc}")

    def _send(self, payload: dict) -> None:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self._webhook_url, data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()


_slack_singleton: SlackNotifier | None = None


def get_slack_notifier() -> SlackNotifier:
    global _slack_singleton
    if _slack_singleton is None:
        _slack_singleton = SlackNotifier()
    return _slack_singleton
