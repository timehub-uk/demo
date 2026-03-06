"""
Market Pulse – 5-Minute Broad Market Monitor.

Watches ALL USDT trading pairs every 5 minutes for:
  • Volume spikes   – sudden surge vs 20-bar rolling average (>2×)
  • Early pumps     – price up ≥1% in 5 min with rising volume
  • New interest    – RSI crossing 50 from below while volume expands
  • Exhaustion      – RSI >75 + volume declining → do NOT enter (greed trap)
  • Momentum decay  – momentum reversing → emit EXIT signal for open trades

Signals are emitted via callbacks and cached in Redis so the chart widget
and AutoTrader can consume them without polling.

Usage:
    pulse = MarketPulse(redis_client=rc)
    pulse.on_alert(lambda alert: print(alert))
    pulse.start()
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from loguru import logger
from utils.logger import get_intel_logger


# ── Alert types ───────────────────────────────────────────────────────────────

ALERT_VOLUME_SPIKE  = "VOLUME_SPIKE"    # Sudden volume surge
ALERT_EARLY_PUMP    = "EARLY_PUMP"      # Price + volume surge together
ALERT_NEW_INTEREST  = "NEW_INTEREST"    # RSI crossing 50, expanding volume
ALERT_EXHAUSTION    = "EXHAUSTION"      # RSI >75, volume fading – avoid
ALERT_MOMENTUM_FADE = "MOMENTUM_FADE"  # Momentum reversing – potential exit


@dataclass
class PulseAlert:
    symbol: str
    alert_type: str
    price: float
    volume_ratio: float      # current vol / 20-bar avg vol
    price_change_pct: float  # % move in last scan window
    rsi: float
    confidence: float        # 0-1
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_entry_signal(self) -> bool:
        return self.alert_type in (ALERT_VOLUME_SPIKE, ALERT_EARLY_PUMP, ALERT_NEW_INTEREST)

    @property
    def is_exit_signal(self) -> bool:
        return self.alert_type in (ALERT_EXHAUSTION, ALERT_MOMENTUM_FADE)

    @property
    def emoji(self) -> str:
        return {
            ALERT_VOLUME_SPIKE:  "🔊",
            ALERT_EARLY_PUMP:    "🚀",
            ALERT_NEW_INTEREST:  "👀",
            ALERT_EXHAUSTION:    "⚠️",
            ALERT_MOMENTUM_FADE: "📉",
        }.get(self.alert_type, "❓")


# ── MarketPulse ───────────────────────────────────────────────────────────────

class MarketPulse:
    """
    Continuously scans all USDT pairs every SCAN_INTERVAL_SEC seconds.
    Emits PulseAlert objects to registered callbacks.
    Thread-safe.
    """

    SCAN_INTERVAL_SEC     = 300    # 5-minute windows
    MIN_VOLUME_RATIO      = 2.0    # Volume spike threshold (2× avg)
    PUMP_PRICE_PCT        = 1.0    # Min price move for early pump
    RSI_INTEREST_CROSS    = 50.0   # RSI cross threshold for new interest
    RSI_EXHAUSTION        = 75.0   # RSI above this = greed trap
    MOMENTUM_FADE_DROP    = 0.30   # RSI drops by 30% of range in one bar
    MAX_ALERTS_CACHED     = 100    # Redis cache depth
    TOP_PAIRS_LIMIT       = 200    # Max pairs to watch

    def __init__(self, redis_client=None, binance_client=None) -> None:
        self._redis   = redis_client
        self._client  = binance_client
        self._intel   = get_intel_logger()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._alert_callbacks: list[Callable[[PulseAlert], None]] = []
        self._lock    = threading.Lock()

        # Rolling history: {symbol: deque of dicts {price, volume, rsi}}
        self._history: dict[str, list] = {}

    def on_alert(self, cb: Callable[[PulseAlert], None]) -> None:
        """Register a callback for every new alert."""
        with self._lock:
            self._alert_callbacks.append(cb)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="market-pulse"
        )
        self._thread.start()
        self._intel.ml("MarketPulse", "📡 Market Pulse started – watching all USDT pairs every 5 min")

    def stop(self) -> None:
        self._running = False

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        while self._running:
            try:
                self._scan_all()
            except Exception as exc:
                logger.debug(f"MarketPulse scan error: {exc}")
            time.sleep(self.SCAN_INTERVAL_SEC)

    def _scan_all(self) -> None:
        tickers = self._fetch_all_tickers()
        if not tickers:
            return

        alerts_this_round: list[PulseAlert] = []

        for sym, data in tickers.items():
            try:
                alert = self._analyse_pair(sym, data)
                if alert:
                    alerts_this_round.append(alert)
            except Exception:
                pass

        # Sort by confidence descending, emit top findings
        alerts_this_round.sort(key=lambda a: a.confidence, reverse=True)
        for alert in alerts_this_round[:20]:   # Top 20 per scan round
            self._emit_alert(alert)

        if alerts_this_round:
            self._intel.ml("MarketPulse",
                f"📡 Pulse scan: {len(tickers)} pairs | {len(alerts_this_round)} alerts | "
                f"top: {alerts_this_round[0].emoji}{alerts_this_round[0].symbol} "
                f"({alerts_this_round[0].alert_type})")

    def _analyse_pair(self, symbol: str, data: dict) -> Optional[PulseAlert]:
        """
        Compare latest tick to rolling history.
        Returns a PulseAlert or None.
        """
        price      = float(data.get("price") or data.get("lastPrice") or 0)
        volume     = float(data.get("volume") or data.get("quoteVolume") or 0)
        price_chg  = float(data.get("priceChangePercent") or 0)
        rsi        = float(data.get("rsi") or 50)   # May not always be present

        if price <= 0:
            return None

        # Update rolling history (keep last 21 data points = 20-bar avg)
        hist = self._history.setdefault(symbol, [])
        hist.append({"price": price, "volume": volume, "rsi": rsi})
        if len(hist) > 21:
            hist.pop(0)

        if len(hist) < 3:
            return None   # Not enough history yet

        # 20-bar average volume (or what we have)
        avg_vol = sum(h["volume"] for h in hist[:-1]) / max(1, len(hist) - 1)
        vol_ratio = volume / max(avg_vol, 1e-9)

        # Previous RSI for cross detection
        prev_rsi = hist[-2]["rsi"] if len(hist) >= 2 else 50

        # ── Checks ──────────────────────────────────────────────────────
        # Exhaustion first – do not emit entry signals when greedy
        if rsi >= self.RSI_EXHAUSTION and vol_ratio < 1.2:
            return PulseAlert(
                symbol=symbol,
                alert_type=ALERT_EXHAUSTION,
                price=price,
                volume_ratio=vol_ratio,
                price_change_pct=price_chg,
                rsi=rsi,
                confidence=min(0.95, (rsi - self.RSI_EXHAUSTION) / 25 + 0.5),
                message=(
                    f"{symbol} RSI={rsi:.0f} (overbought), volume fading "
                    f"– avoid entry, consider exit"
                ),
            )

        # Momentum fade
        if rsi < prev_rsi - self.MOMENTUM_FADE_DROP * 100 and price_chg < 0:
            return PulseAlert(
                symbol=symbol,
                alert_type=ALERT_MOMENTUM_FADE,
                price=price,
                volume_ratio=vol_ratio,
                price_change_pct=price_chg,
                rsi=rsi,
                confidence=min(0.85, abs(rsi - prev_rsi) / 40 + 0.4),
                message=(
                    f"{symbol} momentum fading: RSI {prev_rsi:.0f}→{rsi:.0f}, "
                    f"price {price_chg:+.2f}%"
                ),
            )

        # Early pump: price up AND volume spike together
        if price_chg >= self.PUMP_PRICE_PCT and vol_ratio >= self.MIN_VOLUME_RATIO:
            conf = min(0.92, (vol_ratio / 5) * 0.5 + (price_chg / 5) * 0.5)
            return PulseAlert(
                symbol=symbol,
                alert_type=ALERT_EARLY_PUMP,
                price=price,
                volume_ratio=vol_ratio,
                price_change_pct=price_chg,
                rsi=rsi,
                confidence=conf,
                message=(
                    f"🚀 {symbol} early pump: +{price_chg:.2f}% "
                    f"with {vol_ratio:.1f}× volume surge | RSI={rsi:.0f}"
                ),
            )

        # Pure volume spike (even without price move – precursor to pump)
        if vol_ratio >= self.MIN_VOLUME_RATIO * 1.5:
            conf = min(0.80, (vol_ratio / 8) * 0.6 + 0.3)
            return PulseAlert(
                symbol=symbol,
                alert_type=ALERT_VOLUME_SPIKE,
                price=price,
                volume_ratio=vol_ratio,
                price_change_pct=price_chg,
                rsi=rsi,
                confidence=conf,
                message=(
                    f"🔊 {symbol} volume spike: {vol_ratio:.1f}× avg | "
                    f"price {price_chg:+.2f}%"
                ),
            )

        # New interest: RSI crossing 50 from below + expanding volume
        if prev_rsi < self.RSI_INTEREST_CROSS <= rsi and vol_ratio >= 1.3:
            conf = min(0.75, (vol_ratio / 3) * 0.4 + (rsi - 50) / 50 * 0.4 + 0.2)
            return PulseAlert(
                symbol=symbol,
                alert_type=ALERT_NEW_INTEREST,
                price=price,
                volume_ratio=vol_ratio,
                price_change_pct=price_chg,
                rsi=rsi,
                confidence=conf,
                message=(
                    f"👀 {symbol} new interest: RSI crossed 50 ({prev_rsi:.0f}→{rsi:.0f}) "
                    f"with {vol_ratio:.1f}× volume"
                ),
            )

        return None

    # ── Data fetching ─────────────────────────────────────────────────────────

    def _fetch_all_tickers(self) -> dict[str, dict]:
        """Return {symbol: ticker_dict} for all USDT pairs."""
        # Try Redis 24hr ticker cache first
        if self._redis:
            try:
                tickers = self._redis.get("market:all_tickers")
                if tickers and isinstance(tickers, dict):
                    return {k: v for k, v in tickers.items()
                            if k.endswith("USDT")}
            except Exception:
                pass

        # Fall back to Binance REST
        if self._client:
            try:
                raw = self._client.get_all_tickers()
                if isinstance(raw, list):
                    result = {}
                    for t in raw:
                        sym = t.get("symbol", "")
                        if sym.endswith("USDT"):
                            result[sym] = t
                    return dict(list(result.items())[:self.TOP_PAIRS_LIMIT])
            except Exception as exc:
                logger.debug(f"MarketPulse fetch failed: {exc}")

        # Fall back to individual Redis tickers for known symbols
        if self._redis:
            try:
                symbols_raw = self._redis.get("scanner:symbols")
                if symbols_raw:
                    symbols = symbols_raw if isinstance(symbols_raw, list) else []
                    out = {}
                    for sym in symbols[:self.TOP_PAIRS_LIMIT]:
                        t = self._redis.get_ticker(sym)
                        if t:
                            out[sym] = t
                    return out
            except Exception:
                pass

        return {}

    # ── Emit ──────────────────────────────────────────────────────────────────

    def _emit_alert(self, alert: PulseAlert) -> None:
        # Log to intel
        self._intel.signal("MarketPulse", f"{alert.emoji} {alert.message}")

        # Push to Redis for UI polling
        if self._redis:
            try:
                key = f"pulse:alert:{alert.symbol}"
                self._redis.set(key, {
                    "symbol": alert.symbol,
                    "alert_type": alert.alert_type,
                    "price": alert.price,
                    "volume_ratio": alert.volume_ratio,
                    "price_change_pct": alert.price_change_pct,
                    "rsi": alert.rsi,
                    "confidence": alert.confidence,
                    "message": alert.message,
                    "timestamp": alert.timestamp,
                }, ttl=600)
                # Also append to a rolling list
                try:
                    existing = self._redis.get("pulse:recent_alerts") or []
                    if not isinstance(existing, list):
                        existing = []
                    existing.insert(0, {
                        "symbol": alert.symbol,
                        "alert_type": alert.alert_type,
                        "price": alert.price,
                        "confidence": alert.confidence,
                        "message": alert.message,
                        "timestamp": alert.timestamp,
                    })
                    self._redis.set("pulse:recent_alerts", existing[:self.MAX_ALERTS_CACHED], ttl=3600)
                except Exception:
                    pass
            except Exception:
                pass

        # Fire registered callbacks
        with self._lock:
            cbs = list(self._alert_callbacks)
        for cb in cbs:
            try:
                cb(alert)
            except Exception:
                pass

    @property
    def recent_alerts(self) -> list[dict]:
        """Return cached alerts from Redis (for UI polling)."""
        if self._redis:
            try:
                return self._redis.get("pulse:recent_alerts") or []
            except Exception:
                pass
        return []
