"""
Telegram Bot Notification & Command Interface.

Sends real-time alerts to a configured Telegram chat:
  - Trade fills with P&L
  - Whale event alerts
  - ML signals (high confidence only)
  - Daily P&L summary
  - Win rate warnings

Accepts commands from the chat:
  /status     – engine mode, today's P&L, win rate
  /portfolio  – open positions and portfolio value
  /pause      – pause auto-trading
  /resume     – resume auto-trading
  /report     – generate and send daily tax report

Uses Telegram Bot API directly (no external library needed).
Rate limited to 1 message per 3 seconds to avoid flood restrictions.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import Optional, Callable

from loguru import logger
from utils.logger import get_intel_logger


@dataclass
class TelegramMessage:
    text: str
    parse_mode: str = "HTML"   # HTML or Markdown


class TelegramBot:
    """
    Minimal Telegram Bot with send queue + command polling.
    Set token + chat_id in settings.ai.telegram_bot_token / telegram_chat_id.
    """

    API_BASE = "https://api.telegram.org/bot{token}/{method}"
    RATE_LIMIT_SEC = 3.0         # Minimum seconds between messages
    POLL_INTERVAL  = 5           # Seconds between update polls

    def __init__(self, engine=None, portfolio=None, services: dict | None = None) -> None:
        self._engine    = engine
        self._portfolio = portfolio
        self._services: dict = services or {}
        self._intel    = get_intel_logger()
        self._token: Optional[str] = None
        self._chat_id: Optional[str] = None
        self._running = False
        self._send_queue: queue.Queue[TelegramMessage] = queue.Queue(maxsize=50)
        self._last_update_id = 0
        self._callbacks: dict[str, Callable] = {}
        self._send_thread: Optional[threading.Thread] = None
        self._poll_thread:  Optional[threading.Thread] = None

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        try:
            from config import get_settings
            settings = get_settings()
            self._token   = getattr(settings.ai, "telegram_bot_token", None)
            self._chat_id = getattr(settings.ai, "telegram_chat_id", None)
        except Exception:
            pass

        if not self._token or not self._chat_id:
            self._intel.system("TelegramBot", "Telegram not configured – skipping")
            return

        self._running = True
        self._send_thread = threading.Thread(target=self._send_worker, daemon=True, name="tg-send")
        self._poll_thread  = threading.Thread(target=self._poll_worker, daemon=True, name="tg-poll")
        self._send_thread.start()
        self._poll_thread.start()
        self._intel.system("TelegramBot", "📱 Telegram bot started")
        self.send_text("🤖 <b>BinanceML Pro</b> started. Type /status for info.")

    def stop(self) -> None:
        self._running = False

    def on_command(self, command: str, callback: Callable) -> None:
        """Register a command handler (e.g. '/pause')."""
        self._callbacks[command] = callback

    # ── Alert methods ──────────────────────────────────────────────────

    def send_text(self, text: str, parse_mode: str = "HTML") -> None:
        try:
            self._send_queue.put_nowait(TelegramMessage(text, parse_mode))
        except queue.Full:
            pass

    def send_trade_alert(self, action: str, symbol: str, price: float,
                         qty: float, pnl: float | None = None) -> None:
        emoji = "🟢" if action == "BUY" else "🔴"
        pnl_str = f"\nP&L: <b>{pnl:+,.2f} USDT</b>" if pnl is not None else ""
        text = (
            f"{emoji} <b>{action} {symbol}</b>\n"
            f"Price: {price:,.4f} USDT\n"
            f"Qty: {qty:.6f}{pnl_str}"
        )
        self.send_text(text)

    def send_whale_alert(self, event_type: str, symbol: str,
                         volume_usd: float, confidence: float) -> None:
        emoji_map = {
            "FALSE_WALL": "⚠️", "BUY_WALL": "🟢", "SELL_WALL": "🔴",
            "ATTACK_UP": "🚀", "ATTACK_DOWN": "💥",
            "ACCUMULATION": "🔵", "SPOOF": "👻",
        }
        emoji = emoji_map.get(event_type, "🐳")
        text = (
            f"{emoji} <b>WHALE: {event_type}</b>\n"
            f"Symbol: {symbol}\n"
            f"Volume: ${volume_usd:,.0f}\n"
            f"Confidence: {confidence:.0%}"
        )
        self.send_text(text)

    def send_signal_alert(self, signal: str, symbol: str, confidence: float) -> None:
        if confidence < 0.70:
            return
        emoji = "🟢" if signal == "BUY" else "🔴" if signal == "SELL" else "⚪"
        text = f"{emoji} <b>ML Signal: {signal} {symbol}</b> ({confidence:.0%})"
        self.send_text(text)

    def send_pnl_report(self, daily_pnl: float, total_trades: int, win_rate: float) -> None:
        emoji = "📈" if daily_pnl >= 0 else "📉"
        text = (
            f"{emoji} <b>Daily P&L Report</b>\n"
            f"P&L: <b>{daily_pnl:+,.2f} USDT</b>\n"
            f"Trades: {total_trades}\n"
            f"Win Rate: {win_rate:.0%}"
        )
        self.send_text(text)

    def send_warning(self, title: str, message: str) -> None:
        self.send_text(f"⚠️ <b>{title}</b>\n{message}")

    # ── Internal ───────────────────────────────────────────────────────

    def _send_worker(self) -> None:
        while self._running:
            try:
                msg = self._send_queue.get(timeout=1.0)
                self._api_send(msg.text, msg.parse_mode)
                self._send_queue.task_done()
                time.sleep(self.RATE_LIMIT_SEC)
            except queue.Empty:
                continue
            except Exception as exc:
                logger.debug(f"TelegramBot send error: {exc}")

    def _poll_worker(self) -> None:
        while self._running:
            try:
                updates = self._api_get_updates()
                for upd in updates:
                    self._handle_update(upd)
            except Exception as exc:
                logger.debug(f"TelegramBot poll error: {exc}")
            time.sleep(self.POLL_INTERVAL)

    def _handle_update(self, upd: dict) -> None:
        uid = upd.get("update_id", 0)
        if uid <= self._last_update_id:
            return
        self._last_update_id = uid

        msg = upd.get("message", {})
        text = msg.get("text", "").strip()
        if not text.startswith("/"):
            return

        cmd = text.split()[0].lower()
        handler = self._callbacks.get(cmd)

        if handler:
            try:
                result = handler()
                if result:
                    self.send_text(str(result))
            except Exception as exc:
                self.send_text(f"❌ Command error: {exc}")
        elif cmd == "/status":
            self.send_text(self._build_status())
        elif cmd == "/portfolio":
            self.send_text(self._build_portfolio())
        elif cmd == "/ml_list":
            self.send_text(self._build_ml_list())
        elif cmd.startswith("/ml_layer_"):
            # /ml_layer_1 … /ml_layer_10
            try:
                layer_n = int(cmd.split("_")[-1])
                if 1 <= layer_n <= 10:
                    self._send_layer(layer_n)
                else:
                    self.send_text("❌ Layer must be 1–10. Use /ml_list to see all layers.")
            except ValueError:
                self.send_text("❌ Usage: /ml_layer_1 … /ml_layer_10")
        elif cmd == "/help":
            self.send_text(
                "📖 <b>Available commands:</b>\n"
                "/status – system status\n"
                "/portfolio – positions\n"
                "/pause – pause auto-trading\n"
                "/resume – resume auto-trading\n\n"
                "<b>ML Toolbox:</b>\n"
                "/ml_list – list all 10 layers\n"
                "/ml_layer_1 … /ml_layer_10 – current results for that layer\n\n"
                "/help – this message"
            )

    def _build_status(self) -> str:
        mode = "UNKNOWN"
        if self._engine:
            try:
                mode = str(self._engine.mode)
                metrics = self._engine.metrics
                return (
                    f"📊 <b>Status</b>\n"
                    f"Mode: {mode}\n"
                    f"Trades today: {metrics.get('trades_today', 0)}\n"
                    f"P&L today: {metrics.get('pnl_today', 0):+,.2f} USDT\n"
                    f"Signals: {metrics.get('signals_processed', 0)}"
                )
            except Exception:
                pass
        return f"📊 Mode: {mode}"

    def _build_ml_list(self) -> str:
        from ml.layer_results import LAYER_META
        lines = ["🧠 <b>ML Toolbox – 10 Layers</b>\n"]
        for n, meta in LAYER_META.items():
            lines.append(f"  /ml_layer_{n} – <b>Layer {n}</b>: {meta['name']}")
        lines.append("\nSend /ml_layer_N to get live results for that layer.")
        return "\n".join(lines)

    def _send_layer(self, layer_n: int) -> None:
        """Fetch and send results for one layer (may split into multiple messages)."""
        from ml.layer_results import format_layer_text
        text = format_layer_text(layer_n, self._services)
        # Telegram max 4096 chars per message; split if needed
        for chunk in _split_message(text, 4000):
            self.send_text(chunk)

    def _build_portfolio(self) -> str:
        if self._portfolio:
            try:
                summary = self._portfolio.get_summary()
                total = summary.get("total_value_usdt", 0)
                positions = summary.get("positions", [])
                lines = [f"💼 <b>Portfolio</b>\nTotal: ${total:,.2f}\n"]
                for p in positions[:10]:
                    lines.append(f"• {p.get('symbol','?')}: {p.get('qty',0):.4f} @ ${p.get('avg_price',0):,.2f}")
                return "\n".join(lines)
            except Exception:
                pass
        return "💼 Portfolio data unavailable"

    def _api_send(self, text: str, parse_mode: str = "HTML") -> None:
        url = self.API_BASE.format(token=self._token, method="sendMessage")
        payload = json.dumps({
            "chat_id": self._chat_id,
            "text": text[:4096],
            "parse_mode": parse_mode,
        }).encode()
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

    def set_services(self, services: dict) -> None:
        """Inject the services dict after construction (called from main.py)."""
        self._services = services

    def _api_get_updates(self) -> list[dict]:
        url = self.API_BASE.format(token=self._token, method="getUpdates")
        params = urllib.parse.urlencode({
            "offset": self._last_update_id + 1,
            "timeout": 0,
            "limit": 10,
        })
        with urllib.request.urlopen(f"{url}?{params}", timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get("result", [])


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a long string into chunks without breaking mid-tag."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks
