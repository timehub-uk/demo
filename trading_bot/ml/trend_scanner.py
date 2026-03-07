"""
Trend Scanner ML — Multi-timeframe trend classification for all monitored pairs.

For each symbol the scanner fetches Binance kline data across three base
intervals (5m, 1h, 1d) and derives trend direction and strength across seven
timeframes:

    15m  30m  1h  12h  24h  7d  30d

Classification algorithm (per timeframe window of N bars):

  1. Linear regression slope  → primary direction signal
  2. R² goodness-of-fit      → rewards clean trends, punishes choppy noise
  3. Volatility-adjusted threshold → calibrated per symbol from its own history
  4. EMA fast/slow crossover → secondary confirmation ±15% score adjustment
  5. Price momentum          → first vs last close over the window

The three signals are blended into a single composite score.  Calibration
(per-symbol threshold) is updated from the rolling 5-minute return volatility
so that high-volatility coins require a proportionally larger slope before
being labelled "UP" or "DOWN".

Output (TrendSnapshot):
    {
        "BTCUSDT": TrendSnapshot(
            symbol="BTCUSDT",
            last_price=65000.0,
            trends={
                "15m": TrendResult(direction="UP", strength=0.78, change_pct=0.31, ...),
                "30m": TrendResult(direction="SIDEWAYS", ...),
                ...
            }
        ),
        ...
    }

Thread model:
  - Background scanner wakes every SCAN_INTERVAL_SEC
  - Results stored in a thread-safe dict, emitted to registered callbacks
  - Klines are cached with per-interval TTL to minimise API calls
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

import numpy as np
from loguru import logger
from utils.logger import get_intel_logger


# ── Timeframe configuration ────────────────────────────────────────────────────

# Maps each user-facing timeframe label to the kline group and bar count needed
TIMEFRAME_CFG: dict[str, dict] = {
    "15m": {"group": "5m", "bars": 3},
    "30m": {"group": "5m", "bars": 6},
    "1h":  {"group": "5m", "bars": 12},
    "12h": {"group": "1h", "bars": 12},
    "24h": {"group": "1h", "bars": 24},
    "7d":  {"group": "1d", "bars": 7},
    "30d": {"group": "1d", "bars": 30},
}

# Kline groups: how many bars to fetch per interval + how long to cache result
GROUP_CFG: dict[str, dict] = {
    "5m": {"fetch": 15,  "cache_ttl_sec": 60},
    "1h": {"fetch": 26,  "cache_ttl_sec": 300},
    "1d": {"fetch": 32,  "cache_ttl_sec": 3600},
}

TIMEFRAMES: list[str] = ["15m", "30m", "1h", "12h", "24h", "7d", "30d"]

SCAN_INTERVAL_SEC = 120    # Full cycle period

# Default symbols to monitor
DEFAULT_SYMBOLS: list[str] = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "MATICUSDT",
    "LINKUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "NEARUSDT",
    "SHIBUSDT", "TRXUSDT", "ETCUSDT", "FILUSDT", "SANDUSDT",
]

TrendLabel = Literal["UP", "SIDEWAYS", "DOWN"]


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class TrendResult:
    """Trend classification for one symbol × one timeframe."""
    symbol:     str
    timeframe:  str
    direction:  TrendLabel    # "UP" | "SIDEWAYS" | "DOWN"
    strength:   float         # 0.0 (barely detectable) → 1.0 (very strong)
    change_pct: float         # % price change over the window (first→last close)
    r_squared:  float         # Linear regression fit quality (0→1)
    slope_norm: float         # Slope normalised by mean price
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def arrow(self) -> str:
        return {"UP": "↑", "DOWN": "↓", "SIDEWAYS": "→"}[self.direction]

    @property
    def strength_label(self) -> str:
        if self.strength >= 0.7:
            return "Strong"
        if self.strength >= 0.4:
            return "Moderate"
        return "Weak"


@dataclass
class TrendSnapshot:
    """All timeframe trends for one symbol at a point in time."""
    symbol:     str
    last_price: float
    trends:     dict[str, TrendResult]   # timeframe → TrendResult
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def get(self, timeframe: str) -> Optional[TrendResult]:
        return self.trends.get(timeframe)


# ── Pure maths helpers ─────────────────────────────────────────────────────────

def _ema(data: np.ndarray, period: int) -> float:
    """Exponential moving average — returns final value."""
    if len(data) == 0:
        return 0.0
    period = max(1, period)
    k   = 2.0 / (period + 1)
    val = float(data[0])
    for price in data[1:]:
        val = float(price) * k + val * (1.0 - k)
    return val


def _linear_regression(y: np.ndarray) -> tuple[float, float, float]:
    """
    Fit y ~ a + b·x for x in [0, n-1].

    Returns (slope_per_bar, intercept, r_squared).
    R² = 1 means a perfect line; 0 means no linear relationship.
    """
    n = len(y)
    if n < 3:
        return 0.0, float(y[0]) if len(y) else 0.0, 0.0

    x  = np.arange(n, dtype=float)
    xm = x.mean()
    ym = y.mean()

    ssxy  = float(np.sum((x - xm) * (y - ym)))
    ssxx  = float(np.sum((x - xm) ** 2))
    slope = ssxy / ssxx if ssxx > 1e-12 else 0.0

    y_pred = slope * (x - xm) + ym
    ssres  = float(np.sum((y - y_pred) ** 2))
    sstot  = float(np.sum((y - ym) ** 2))
    r2     = max(0.0, 1.0 - ssres / sstot) if sstot > 1e-12 else 0.0

    return slope, float(ym), r2


def _classify(closes: np.ndarray, vol_calibration: float = 0.0) -> tuple[TrendLabel, float, float, float, float]:
    """
    Classify trend direction and strength from a close-price array.

    Parameters
    ----------
    closes           : NumPy array of close prices (oldest first)
    vol_calibration  : Rolling 5-minute return std from this symbol's history.
                       0.0 → use a conservative default.

    Returns
    -------
    (direction, strength, change_pct, r_squared, slope_norm)
    """
    n = len(closes)
    if n < 3:
        return "SIDEWAYS", 0.0, 0.0, 0.0, 0.0

    closes = closes.astype(float)
    slope, mean_price, r2 = _linear_regression(closes)

    if mean_price < 1e-12:
        return "SIDEWAYS", 0.0, 0.0, 0.0, 0.0

    # Normalised slope: fraction of mean price per bar
    slope_norm = slope / mean_price

    # Volatility-adjusted threshold
    # We estimate per-bar volatility from close-to-close returns
    returns = np.diff(closes) / closes[:-1]
    per_bar_vol = float(returns.std()) if len(returns) > 1 else (vol_calibration or 0.005)
    if vol_calibration > 0:
        # Blend: 70% live, 30% calibration
        per_bar_vol = 0.7 * per_bar_vol + 0.3 * vol_calibration
    threshold = max(0.0002, per_bar_vol * 0.3)

    # Price change over the whole window
    change_pct = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 1e-12 else 0.0

    # EMA fast / slow crossover (fast = n//3, slow = all bars)
    fast_period = max(2, n // 3)
    fast_ema    = _ema(closes, fast_period)
    slow_ema    = _ema(closes, n)
    ema_aligns  = (slope_norm > 0 and fast_ema >= slow_ema) or \
                  (slope_norm < 0 and fast_ema <= slow_ema)

    # Composite score: direction × R²-weighted magnitude, ±EMA adjustment
    weighted = (slope_norm / threshold) * max(0.1, r2)
    weighted *= 1.15 if ema_aligns else 0.85

    if weighted > 0.5:
        direction = "UP"
        strength  = min(1.0, weighted / 3.0)
    elif weighted < -0.5:
        direction = "DOWN"
        strength  = min(1.0, abs(weighted) / 3.0)
    else:
        direction = "SIDEWAYS"
        strength  = max(0.0, 1.0 - min(1.0, abs(weighted) * 2))

    return direction, round(strength, 3), round(change_pct, 3), round(r2, 3), round(slope_norm, 8)


# ── Main scanner ───────────────────────────────────────────────────────────────

class TrendScanner:
    """
    Background scanner that classifies trend across 7 timeframes for each
    monitored symbol.

    Usage::

        scanner = TrendScanner(binance_client=client)
        scanner.on_update(my_callback)   # cb(dict[str, TrendSnapshot])
        scanner.start()
        snap = scanner.get_snapshot("BTCUSDT")
    """

    def __init__(
        self,
        binance_client=None,
        symbols: Optional[list[str]] = None,
    ) -> None:
        self._client   = binance_client
        self._intel    = get_intel_logger()
        self._lock     = threading.Lock()
        self._running  = False
        self._thread: Optional[threading.Thread] = None

        self._symbols: list[str] = list(symbols or DEFAULT_SYMBOLS)

        # Result store: symbol → TrendSnapshot
        self._snapshots: dict[str, TrendSnapshot] = {}

        # Kline cache: (symbol, interval) → {"data": list, "ts": float}
        self._kline_cache: dict[tuple[str, str], dict] = {}

        # Per-symbol rolling volatility calibration (from 5m return std)
        self._vol_cal: dict[str, float] = {}

        self._callbacks: list[Callable[[dict[str, TrendSnapshot]], None]] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_update(self, cb: Callable[[dict[str, TrendSnapshot]], None]) -> None:
        """Register callback invoked after every full scan with updated snapshots."""
        self._callbacks.append(cb)

    def get_snapshot(self, symbol: str) -> Optional[TrendSnapshot]:
        with self._lock:
            return self._snapshots.get(symbol)

    def get_all_snapshots(self) -> dict[str, TrendSnapshot]:
        with self._lock:
            return dict(self._snapshots)

    def add_symbol(self, symbol: str) -> None:
        with self._lock:
            if symbol not in self._symbols:
                self._symbols.append(symbol)

    def remove_symbol(self, symbol: str) -> None:
        with self._lock:
            self._symbols = [s for s in self._symbols if s != symbol]
            self._snapshots.pop(symbol, None)

    @property
    def symbols(self) -> list[str]:
        with self._lock:
            return list(self._symbols)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="trend-scanner"
        )
        self._thread.start()
        self._intel.ml("TrendScanner",
                       f"Started — monitoring {len(self._symbols)} symbols "
                       f"across {len(TIMEFRAMES)} timeframes")

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(2)   # brief warm-up
        while self._running:
            t0 = time.monotonic()
            try:
                self._full_scan()
            except Exception as exc:
                logger.warning(f"TrendScanner scan error: {exc!r}")
            elapsed = time.monotonic() - t0
            sleep_for = max(1.0, SCAN_INTERVAL_SEC - elapsed)
            time.sleep(sleep_for)

    def _full_scan(self) -> None:
        with self._lock:
            syms = list(self._symbols)

        updated: dict[str, TrendSnapshot] = {}
        for sym in syms:
            if not self._running:
                break
            try:
                snap = self._scan_symbol(sym)
                if snap:
                    updated[sym] = snap
            except Exception as exc:
                logger.debug(f"TrendScanner: {sym} scan failed: {exc!r}")

        if updated:
            with self._lock:
                self._snapshots.update(updated)
            for cb in self._callbacks:
                try:
                    cb(dict(self._snapshots))
                except Exception as exc:
                    logger.warning(f"TrendScanner callback error: {exc!r}")

        self._intel.ml("TrendScanner",
                       f"Scan complete — {len(updated)}/{len(syms)} symbols updated")

    # ── Per-symbol scan ────────────────────────────────────────────────────────

    def _scan_symbol(self, symbol: str) -> Optional[TrendSnapshot]:
        """Fetch klines for all groups and classify all 7 timeframes."""
        # Fetch klines for each group (5m, 1h, 1d)
        group_closes: dict[str, np.ndarray] = {}
        last_price = 0.0

        for interval, gcfg in GROUP_CFG.items():
            raw = self._fetch_klines(symbol, interval, gcfg["fetch"], gcfg["cache_ttl_sec"])
            if not raw:
                continue
            closes = np.array([float(k[4]) for k in raw], dtype=float)
            if len(closes) == 0:
                continue
            group_closes[interval] = closes
            if interval == "5m":
                last_price = float(closes[-1])

        if not group_closes:
            return None

        if last_price == 0.0:
            # Fallback to any available price
            for closes in group_closes.values():
                if len(closes):
                    last_price = float(closes[-1])
                    break

        # Update volatility calibration from 5-min data
        if "5m" in group_closes and len(group_closes["5m"]) >= 3:
            c5 = group_closes["5m"]
            rets = np.diff(c5) / c5[:-1]
            if len(rets):
                new_vol = float(rets.std())
                with self._lock:
                    old_vol = self._vol_cal.get(symbol, new_vol)
                    # Exponentially-smoothed volatility estimate
                    self._vol_cal[symbol] = 0.8 * old_vol + 0.2 * new_vol

        with self._lock:
            vol_cal = self._vol_cal.get(symbol, 0.0)

        # Classify each timeframe
        trends: dict[str, TrendResult] = {}
        for tf in TIMEFRAMES:
            cfg     = TIMEFRAME_CFG[tf]
            group   = cfg["group"]
            n_bars  = cfg["bars"]
            closes  = group_closes.get(group)
            if closes is None or len(closes) < 3:
                continue

            # Take last n_bars bars (or all if fewer available)
            window = closes[-n_bars:] if len(closes) >= n_bars else closes
            if len(window) < 2:
                continue

            direction, strength, change_pct, r2, slope_norm = _classify(window, vol_cal)
            trends[tf] = TrendResult(
                symbol=symbol,
                timeframe=tf,
                direction=direction,
                strength=strength,
                change_pct=change_pct,
                r_squared=r2,
                slope_norm=slope_norm,
            )

        if not trends:
            return None

        return TrendSnapshot(
            symbol=symbol,
            last_price=last_price,
            trends=trends,
        )

    # ── Kline fetching with cache ──────────────────────────────────────────────

    def _fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        cache_ttl_sec: float,
    ) -> list:
        """Fetch klines from Binance REST, with per-(symbol, interval) cache."""
        cache_key = (symbol, interval)
        now = time.monotonic()

        # Check cache
        cached = self._kline_cache.get(cache_key)
        if cached and (now - cached["ts"]) < cache_ttl_sec:
            return cached["data"]

        # Fetch from Binance
        data = self._fetch_klines_api(symbol, interval, limit)
        if data is not None:
            self._kline_cache[cache_key] = {"data": data, "ts": now}
            return data

        # Return stale cache if available
        return (cached or {}).get("data", [])

    def _fetch_klines_api(self, symbol: str, interval: str, limit: int) -> Optional[list]:
        """Call the Binance REST API for klines. Returns None on failure."""
        if not self._client:
            return self._synthetic_klines(symbol, interval, limit)
        try:
            return self._client.get_klines(
                symbol=symbol, interval=interval, limit=limit
            )
        except Exception as exc:
            logger.debug(
                f"TrendScanner: kline fetch failed {symbol}/{interval}: {exc!r}"
            )
            # Fall back to synthetic data for demo / offline mode
            return self._synthetic_klines(symbol, interval, limit)

    def _synthetic_klines(self, symbol: str, interval: str, limit: int) -> list:
        """
        Generate a realistic-looking synthetic kline series for demo/offline use.
        Uses a seeded random walk anchored to known approximate prices.
        """
        seed_prices = {
            "BTCUSDT": 65000.0, "ETHUSDT": 3500.0,  "BNBUSDT": 580.0,
            "SOLUSDT": 180.0,   "XRPUSDT": 0.65,    "ADAUSDT": 0.48,
            "AVAXUSDT": 40.0,   "DOGEUSDT": 0.12,   "SHIBUSDT": 0.000025,
            "DOTUSDT": 8.0,     "MATICUSDT": 0.9,   "LINKUSDT": 15.0,
            "LTCUSDT": 85.0,    "UNIUSDT": 7.5,     "ATOMUSDT": 9.0,
            "NEARUSDT": 5.0,    "TRXUSDT": 0.13,    "ETCUSDT": 25.0,
            "FILUSDT": 5.5,     "SANDUSDT": 0.35,
        }
        volatility_map = {
            "5m": 0.001, "1h": 0.005, "1d": 0.02,
        }
        base  = seed_prices.get(symbol, 1.0)
        vol   = volatility_map.get(interval, 0.002)
        now_ms = int(time.time() * 1000)
        interval_ms = {
            "1m": 60_000, "3m": 180_000, "5m": 300_000,
            "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000,
            "4h": 14_400_000, "1d": 86_400_000,
        }.get(interval, 300_000)

        rng   = np.random.default_rng(hash(symbol + interval) % (2**31))
        price = base
        klines = []
        for i in range(limit):
            ts = now_ms - (limit - i) * interval_ms
            o  = price
            price = max(price * (1 + rng.normal(0, vol)), 1e-10)
            h  = max(o, price) * (1 + abs(rng.normal(0, vol * 0.3)))
            l  = min(o, price) * (1 - abs(rng.normal(0, vol * 0.3)))
            c  = price
            klines.append([ts, str(o), str(h), str(l), str(c),
                           "0", ts + interval_ms - 1, "0", 0, "0", "0", "0"])
        return klines
