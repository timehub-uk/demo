"""
StreamDeckController – Elgato Stream Deck integration for BinanceML Pro.

Maps physical Stream Deck buttons to trading actions, mode switches,
and live price/P&L display.  Uses the `streamdeck` PyPI package
(pip install streamdeck).  Falls back gracefully if no device is found
or the package is not installed.

Button layout (default 15-key / 5×3):
  Row 0:  [BUY BTC] [BUY ETH] [BUY SOL] [BUY BNB] [BUY XRP]
  Row 1:  [SELL BTC][SELL ETH][SELL SOL] [SELL BNB][SELL XRP]
  Row 2:  [AUTO ON] [AUTO OFF][PAPER MODE][CANCEL ALL][KILL ⛔]

Each button shows a live label (rendered as a PIL image) with the
current price or status underneath its icon text.

To use without a physical device, set STREAM_DECK_SIMULATE=1 in env
and button presses can be sent via the REST API:
  POST /api/streamdeck/press  {"button": 0}
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Optional

from loguru import logger
from utils.logger import get_intel_logger

# ── Optional imports ─────────────────────────────────────────────────────────
try:
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.ImageHelpers import PILHelper
    _HAS_STREAMDECK = True
except ImportError:
    _HAS_STREAMDECK = False

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

SIMULATE = os.getenv("STREAM_DECK_SIMULATE", "0") == "1"

# Default symbols on the grid (5 per row)
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

# Button indices
ROW0_START = 0   # BUY row (buttons 0-4)
ROW1_START = 5   # SELL row (buttons 5-9)
ROW2_CONTROLS = {
    10: ("AUTO ON",    "auto_on"),
    11: ("AUTO OFF",   "auto_off"),
    12: ("PAPER",      "paper_mode"),
    13: ("CANCEL ALL", "cancel_all"),
    14: ("KILL ⛔",    "emergency_stop"),
}

# Colours (RGB tuples for PIL)
_COL = {
    "bg":      (10,  10,  18),
    "green":   (0,   212, 100),
    "red":     (212, 50,  50),
    "yellow":  (255, 215, 64),
    "blue":    (0,   212, 255),
    "purple":  (170, 50,  255),
    "white":   (240, 240, 240),
    "grey":    (100, 100, 130),
    "orange":  (255, 140, 0),
}


def _make_image(deck, label: str, sub: str, icon_col: tuple,
                bg_col: tuple = _COL["bg"]) -> Any:
    """Render a button face as a PIL Image sized to the deck."""
    if not _HAS_PIL or not deck:
        return None
    try:
        img = PILHelper.create_scaled_image(deck, Image.new("RGB", (1, 1), bg_col))
        draw = ImageDraw.Draw(img)
        w, h = img.size
        # Main label
        draw.text((w // 2, h // 2 - 10), label, fill=icon_col, anchor="mm")
        # Sub-label (price/status)
        if sub:
            draw.text((w // 2, h // 2 + 14), sub, fill=_COL["white"], anchor="mm")
        return PILHelper.to_native_format(deck, img)
    except Exception as exc:
        logger.debug(f"StreamDeck image render error: {exc}")
        return None


class StreamDeckController:
    """
    Manages Elgato Stream Deck connection + button mappings.

    Services are injected after creation via set_services().
    """

    def __init__(self) -> None:
        self._deck        = None
        self._lock        = threading.Lock()
        self._stop_evt    = threading.Event()
        self._thread:     Optional[threading.Thread] = None
        self._intel       = get_intel_logger()
        self._prices:     dict[str, float] = {}
        self._pnl:        float = 0.0
        self._mode:       str = "MANUAL"
        self._callbacks:  dict[str, list[Callable]] = {}
        # Services (injected)
        self._engine      = None
        self._auto_trader = None
        self._order_mgr   = None

    # ── Service injection ────────────────────────────────────────────────────

    def set_services(
        self,
        engine=None,
        auto_trader=None,
        order_manager=None,
    ) -> None:
        self._engine      = engine
        self._auto_trader = auto_trader
        self._order_mgr   = order_manager

    def on_action(self, action: str, cb: Callable) -> None:
        """Register a callback for a named action (e.g. 'buy_BTCUSDT')."""
        self._callbacks.setdefault(action, []).append(cb)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Open the Stream Deck and start the update loop. Returns True if connected."""
        if SIMULATE:
            self._intel.system("StreamDeck", "Simulated mode (no physical device)")
            self._start_update_thread()
            return True

        if not _HAS_STREAMDECK:
            self._intel.warning(
                "StreamDeck",
                "streamdeck package not installed.  "
                "Run: pip install streamdeck  to enable Stream Deck support.",
            )
            return False

        try:
            devices = DeviceManager().enumerate()
            if not devices:
                self._intel.warning("StreamDeck", "No Stream Deck device found.")
                return False

            self._deck = devices[0]
            self._deck.open()
            self._deck.reset()
            self._deck.set_brightness(70)
            self._deck.set_key_callback(self._on_button)
            self._intel.system(
                "StreamDeck",
                f"Connected: {self._deck.deck_type()}  "
                f"({self._deck.key_count()} keys)",
            )
            self._render_all()
            self._start_update_thread()
            return True

        except Exception as exc:
            self._intel.warning("StreamDeck", f"Failed to open device: {exc}")
            return False

    def stop(self) -> None:
        self._stop_evt.set()
        try:
            if self._deck:
                self._deck.reset()
                self._deck.close()
        except Exception:
            pass

    # ── Live data feeds ──────────────────────────────────────────────────────

    def update_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price
        # Refresh just the buttons for this symbol
        try:
            for row, start in ((0, ROW0_START), (1, ROW1_START)):
                for idx, sym in enumerate(DEFAULT_SYMBOLS):
                    if sym == symbol:
                        self._render_btn(start + idx, row)
        except Exception:
            pass

    def update_pnl(self, pnl: float) -> None:
        self._pnl = pnl

    def update_mode(self, mode: str) -> None:
        self._mode = mode.upper()
        self._render_control_row()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _start_update_thread(self) -> None:
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._update_loop, name="StreamDeckUpdate", daemon=True
        )
        self._thread.start()

    def _update_loop(self) -> None:
        """Refresh price labels every 5 s."""
        while not self._stop_evt.is_set():
            try:
                if self._deck or SIMULATE:
                    self._render_all()
            except Exception as exc:
                logger.debug(f"StreamDeck update loop error: {exc}")
            self._stop_evt.wait(5)

    def _on_button(self, deck, key: int, pressed: bool) -> None:
        if not pressed:
            return
        self._intel.system("StreamDeck", f"Button {key} pressed")

        if key < 5:
            sym    = DEFAULT_SYMBOLS[key]
            action = f"buy_{sym}"
            self._dispatch(action)
            self._execute_buy(sym)

        elif key < 10:
            sym    = DEFAULT_SYMBOLS[key - 5]
            action = f"sell_{sym}"
            self._dispatch(action)
            self._execute_sell(sym)

        elif key in ROW2_CONTROLS:
            _, action = ROW2_CONTROLS[key]
            self._dispatch(action)
            self._execute_control(action)

    def _dispatch(self, action: str) -> None:
        for cb in self._callbacks.get(action, []):
            try:
                cb()
            except Exception:
                pass

    # ── Trading actions ──────────────────────────────────────────────────────

    def _execute_buy(self, symbol: str) -> None:
        self._intel.trade("StreamDeck", f"BUY signal → {symbol}")
        try:
            if self._engine:
                self._engine.emit("streamdeck_buy", {"symbol": symbol})
        except Exception as exc:
            logger.debug(f"StreamDeck buy {symbol}: {exc}")

    def _execute_sell(self, symbol: str) -> None:
        self._intel.trade("StreamDeck", f"SELL signal → {symbol}")
        try:
            if self._engine:
                self._engine.emit("streamdeck_sell", {"symbol": symbol})
        except Exception as exc:
            logger.debug(f"StreamDeck sell {symbol}: {exc}")

    def _execute_control(self, action: str) -> None:
        try:
            if action == "auto_on":
                if self._auto_trader:
                    self._auto_trader.start()
                    self._intel.system("StreamDeck", "AutoTrader started")
            elif action == "auto_off":
                if self._auto_trader:
                    if hasattr(self._auto_trader, "pause"):
                        self._auto_trader.pause()
                    self._intel.system("StreamDeck", "AutoTrader paused")
            elif action == "paper_mode":
                if self._engine:
                    self._engine.set_mode("paper")
                    self._intel.system("StreamDeck", "Engine → PAPER mode")
            elif action == "cancel_all":
                if self._order_mgr:
                    self._order_mgr.cancel_all_orders()
                    self._intel.system("StreamDeck", "All orders cancelled")
            elif action == "emergency_stop":
                self._emergency()
        except Exception as exc:
            logger.debug(f"StreamDeck control {action}: {exc}")

    def _emergency(self) -> None:
        msgs = []
        try:
            if self._order_mgr:
                self._order_mgr.cancel_all_orders()
                msgs.append("orders cancelled")
        except Exception:
            pass
        try:
            if self._auto_trader:
                if hasattr(self._auto_trader, "pause"):
                    self._auto_trader.pause()
                msgs.append("AT paused")
        except Exception:
            pass
        try:
            if self._engine:
                self._engine.set_mode("paper")
                msgs.append("PAPER mode")
        except Exception:
            pass
        self._intel.warning("StreamDeck", "EMERGENCY STOP: " + " | ".join(msgs))

    # ── Rendering ────────────────────────────────────────────────────────────

    def _render_all(self) -> None:
        for i, sym in enumerate(DEFAULT_SYMBOLS):
            self._render_btn(ROW0_START + i, 0, sym)
            self._render_btn(ROW1_START + i, 1, sym)
        self._render_control_row()

    def _render_btn(self, key: int, row: int, sym: str | None = None) -> None:
        if not self._deck and not SIMULATE:
            return
        if sym is None:
            idx = key % 5
            if idx < len(DEFAULT_SYMBOLS):
                sym = DEFAULT_SYMBOLS[idx]
            else:
                return

        short  = sym.replace("USDT", "")
        price  = self._prices.get(sym, 0)
        sub    = f"{price:,.2f}" if price else "—"
        label  = f"BUY {short}" if row == 0 else f"SELL {short}"
        col    = _COL["green"] if row == 0 else _COL["red"]

        img = _make_image(self._deck, label, sub, col)
        if img and self._deck:
            with self._lock:
                try:
                    self._deck.set_key_image(key, img)
                except Exception:
                    pass

    def _render_control_row(self) -> None:
        if not self._deck and not SIMULATE:
            return
        for key, (label, action) in ROW2_CONTROLS.items():
            col = _COL["red"] if action == "emergency_stop" else \
                  _COL["orange"] if action == "cancel_all" else \
                  _COL["green"] if action == "auto_on" else \
                  _COL["yellow"]
            sub = self._mode if action in ("auto_on", "auto_off") else ""
            img = _make_image(self._deck, label, sub, col)
            if img and self._deck:
                with self._lock:
                    try:
                        self._deck.set_key_image(key, img)
                    except Exception:
                        pass


# ── Singleton ─────────────────────────────────────────────────────────────────

_controller: Optional[StreamDeckController] = None


def get_stream_deck() -> StreamDeckController:
    global _controller
    if _controller is None:
        _controller = StreamDeckController()
    return _controller
