"""
ElevenLabs Voice Alert System.

Speaks trading events aloud using ElevenLabs TTS:
  - Trade fills (buy/sell, symbol, price, P&L)
  - Whale events (type, symbol, volume)
  - ML signals (action, confidence)
  - Daily P&L summary
  - System alerts (low win rate, integrity issues)

Uses a queue so alerts never overlap. Falls back to macOS `say`
command if ElevenLabs is unavailable.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from loguru import logger
from utils.logger import get_intel_logger


class VoiceAlerts:
    """
    Thread-safe voice alert queue with ElevenLabs TTS.
    Falls back to system TTS (macOS `say` / `espeak`) if EL unavailable.
    """

    DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"   # ElevenLabs "Bella"

    def __init__(self) -> None:
        self._intel = get_intel_logger()
        self._queue: queue.Queue[str] = queue.Queue(maxsize=20)
        self._running = False
        self._enabled = True
        self._volume = 1.0
        self._voice_id = self.DEFAULT_VOICE_ID
        self._thread: Optional[threading.Thread] = None
        self._el_client = None
        self._system_tts = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._init_client()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="voice-worker")
        self._thread.start()
        self._intel.system("VoiceAlerts", "🔊 Voice alerts started")

    def stop(self) -> None:
        self._running = False

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def set_volume(self, vol: float) -> None:
        self._volume = max(0.0, min(1.0, vol))

    # ── Public alert methods ───────────────────────────────────────────

    def speak_trade(self, action: str, symbol: str, price: float, pnl: float | None = None) -> None:
        coin = symbol.replace("USDT", "").upper()
        if pnl is not None:
            sign = "profit" if pnl >= 0 else "loss"
            text = f"{action} {coin} at {price:,.2f}. {sign} {abs(pnl):,.2f} USDT."
        else:
            text = f"{action} {coin} at {price:,.2f}."
        self._enqueue(text)

    def speak_whale_event(self, event_type: str, symbol: str, volume_usd: float) -> None:
        coin = symbol.replace("USDT", "").upper()
        readable = {
            "FALSE_WALL":   f"False wall detected on {coin}",
            "BUY_WALL":     f"Large buy wall on {coin}, {volume_usd/1000:.0f}k USDT",
            "SELL_WALL":    f"Large sell wall on {coin}, {volume_usd/1000:.0f}k USDT",
            "ATTACK_UP":    f"Whale attack pushing {coin} up, {volume_usd/1000:.0f}k",
            "ATTACK_DOWN":  f"Whale attack pushing {coin} down, {volume_usd/1000:.0f}k",
            "ACCUMULATION": f"Possible whale accumulation on {coin}",
            "SPOOF":        f"Spoofing detected on {coin}",
        }.get(event_type, f"Whale activity on {coin}")
        self._enqueue(readable)

    def speak_signal(self, action: str, symbol: str, confidence: float) -> None:
        if confidence < 0.65:
            return   # Only speak high-confidence signals
        coin = symbol.replace("USDT", "").upper()
        text = f"ML signal: {action} {coin}. Confidence {confidence:.0%}."
        self._enqueue(text)

    def speak_pnl(self, pnl: float, period: str = "today") -> None:
        sign = "up" if pnl >= 0 else "down"
        text = f"Portfolio {sign} {abs(pnl):,.2f} USDT {period}."
        self._enqueue(text)

    def speak_alert(self, message: str) -> None:
        self._enqueue(message)

    # ── Internal ───────────────────────────────────────────────────────

    def _enqueue(self, text: str) -> None:
        if not self._enabled:
            return
        try:
            self._queue.put_nowait(text)
        except queue.Full:
            pass   # Drop if queue is full

    def _worker(self) -> None:
        while self._running:
            try:
                text = self._queue.get(timeout=1.0)
                self._speak(text)
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as exc:
                logger.debug(f"VoiceAlerts worker error: {exc}")

    def _speak(self, text: str) -> None:
        if self._el_client:
            self._speak_elevenlabs(text)
        elif self._system_tts:
            self._speak_system(text)
        else:
            logger.debug(f"[VoiceAlerts] {text}")

    def _speak_elevenlabs(self, text: str) -> None:
        try:
            import tempfile, os, subprocess
            audio = self._el_client.generate(
                text=text,
                voice=self._voice_id,
                model="eleven_turbo_v2",
            )
            # Save to temp file and play
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                for chunk in audio:
                    f.write(chunk)
                tmp_path = f.name
            # Play with afplay (macOS) or ffplay
            for player in ["afplay", "ffplay -nodisp -autoexit"]:
                try:
                    subprocess.run(player.split() + [tmp_path],
                                   capture_output=True, timeout=30)
                    break
                except Exception:
                    continue
            os.unlink(tmp_path)
        except Exception as exc:
            logger.debug(f"ElevenLabs speak error: {exc}")
            self._speak_system(text)

    def _speak_system(self, text: str) -> None:
        import subprocess
        try:
            subprocess.run(["say", text], capture_output=True, timeout=20)
        except Exception:
            try:
                subprocess.run(["espeak", text], capture_output=True, timeout=20)
            except Exception:
                pass

    def _init_client(self) -> None:
        try:
            from config import get_settings
            settings = get_settings()
            api_key = getattr(settings.ai, "elevenlabs_api_key", None)
            if api_key:
                from elevenlabs import ElevenLabs
                self._el_client = ElevenLabs(api_key=api_key)
                self._intel.system("VoiceAlerts", "ElevenLabs TTS ready")
                return
        except Exception as exc:
            logger.debug(f"ElevenLabs init error: {exc}")

        # Fallback to system TTS
        import subprocess
        for cmd in ["say", "espeak"]:
            try:
                subprocess.run([cmd, "--version"], capture_output=True)
                self._system_tts = True
                self._intel.system("VoiceAlerts", f"System TTS ({cmd}) ready")
                break
            except Exception:
                continue
