"""
New Token Launch Watcher & Scalp Learner.

Monitors Binance for newly listed tokens and automatically:
  1. Detects launch moment (first candle appears)
  2. Watches the first 10 minutes tick-by-tick
  3. Learns the price discovery pattern:
       - Pump spike height and duration
       - First retracement depth
       - Volume exhaustion signals
       - Optimal entry window (usually 2-5 min after launch)
       - Exit signal (volume/momentum fade)
  4. Builds a LaunchProfile per token from historical launches
  5. When a new token launches, applies learned patterns to
     generate scalp entry/exit signals in real time

Architecture:
  NewTokenWatcher   – monitors exchange for new listings
  LaunchAnalyser    – analyses the first 10 minutes of a token
  ScalpLearner      – learns patterns from past launches
  LaunchScalper     – real-time signal generator for live launches
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from loguru import logger
from utils.logger import get_intel_logger

LAUNCH_DATA_DIR = Path(__file__).parent.parent / "data" / "launches"
LAUNCH_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── Launch profile ────────────────────────────────────────────────────────────

@dataclass
class LaunchCandle:
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_num: int       # 0 = first minute candle


@dataclass
class LaunchProfile:
    """Learned statistics from past token launches."""
    symbol: str
    launch_time: str = ""

    # Price action statistics (all vs open price)
    peak_pct_from_open: float = 0.0          # Max pump from open price
    peak_bar: int = 0                         # Which minute the peak occurred
    first_retrace_pct: float = 0.0           # Retrace from peak
    stable_level_pct: float = 0.0            # Where price settled after initial frenzy

    # Volume stats
    peak_volume_bar: int = 0
    volume_decay_rate: float = 0.0           # How fast volume falls post-launch

    # Scalp stats (from backtested entries)
    best_entry_bar: int = 2                  # Bar that gave best entry historically
    best_entry_pct_from_open: float = 5.0    # What % above open to wait for pullback entry
    best_exit_bar: int = 6
    avg_scalp_pct: float = 0.0               # Average profit from optimal entry
    win_rate: float = 0.0
    sample_count: int = 0                    # How many launches this is based on

    # Raw candles (first 10 minutes)
    candles: list[dict] = field(default_factory=list)


@dataclass
class ScalpSignal:
    symbol: str
    action: str          # ENTER_LONG | EXIT_LONG | WAIT | ABORT
    confidence: float
    reason: str
    price: float
    bar_num: int
    timestamp: str = ""


# ── Launch analyser ───────────────────────────────────────────────────────────

class LaunchAnalyser:
    """
    Analyses the first 10 minutes of a newly launched token.
    Extracts key statistics into a LaunchProfile.
    """

    def __init__(self) -> None:
        self._intel = get_intel_logger()

    def analyse(self, symbol: str, candles: list[LaunchCandle]) -> LaunchProfile:
        if not candles:
            return LaunchProfile(symbol=symbol)

        profile = LaunchProfile(
            symbol=symbol,
            launch_time=datetime.now(timezone.utc).isoformat(),
            candles=[asdict(c) for c in candles],
        )
        open_price = candles[0].open
        if open_price <= 0:
            return profile

        closes = [c.close for c in candles]
        highs  = [c.high for c in candles]
        vols   = [c.volume for c in candles]

        # Peak
        peak_idx = int(np.argmax(highs))
        peak_price = highs[peak_idx]
        profile.peak_pct_from_open = (peak_price - open_price) / open_price * 100
        profile.peak_bar = peak_idx

        # Retrace from peak
        if peak_idx < len(closes) - 1:
            post_peak_low = min(c.low for c in candles[peak_idx:])
            profile.first_retrace_pct = (peak_price - post_peak_low) / peak_price * 100

        # Stable level (last 3 candles average)
        if len(closes) >= 3:
            stable = np.mean(closes[-3:])
            profile.stable_level_pct = (stable - open_price) / open_price * 100

        # Volume stats
        profile.peak_volume_bar = int(np.argmax(vols))
        if vols[0] > 0 and len(vols) > 1:
            # Fit exponential decay
            normed = np.array(vols) / vols[0]
            profile.volume_decay_rate = float(1 - normed[-1]) if len(normed) > 1 else 0.0

        # Best scalp entry (simulate: wait for pullback after peak, enter at min, exit later)
        best_pnl = -np.inf
        best_entry = 1
        best_exit  = len(closes) - 1
        for entry_bar in range(1, min(6, len(closes))):
            entry_price = closes[entry_bar]
            if entry_price <= 0:
                continue
            for exit_bar in range(entry_bar + 1, min(11, len(closes))):
                pnl_pct = (closes[exit_bar] - entry_price) / entry_price * 100
                if pnl_pct > best_pnl:
                    best_pnl = pnl_pct
                    best_entry = entry_bar
                    best_exit  = exit_bar

        profile.best_entry_bar = best_entry
        profile.best_exit_bar  = best_exit
        profile.avg_scalp_pct  = float(best_pnl)
        profile.best_entry_pct_from_open = (closes[best_entry] - open_price) / open_price * 100 if best_entry < len(closes) else 0

        self._intel.ml("LaunchAnalyser",
            f"📊 [{symbol}] Launch analysed | peak={profile.peak_pct_from_open:+.1f}% @ bar {profile.peak_bar} | "
            f"best scalp entry=bar {profile.best_entry_bar} exit=bar {profile.best_exit_bar} | "
            f"avg_scalp={profile.avg_scalp_pct:+.1f}%")
        return profile


# ── Scalp learner ─────────────────────────────────────────────────────────────

class ScalpLearner:
    """
    Aggregates LaunchProfiles from past launches into learned entry/exit rules.
    Saved to data/launches/learned_rules.json.
    """

    RULES_FILE = LAUNCH_DATA_DIR / "learned_rules.json"

    def __init__(self) -> None:
        self._profiles: list[LaunchProfile] = []
        self._rules: dict = {}
        self._intel = get_intel_logger()
        self._load()

    def add_profile(self, profile: LaunchProfile) -> None:
        """Add a new launch profile and update learned rules."""
        if profile.sample_count == 0 and profile.avg_scalp_pct == 0:
            return  # Skip empty profiles
        self._profiles.append(profile)
        self._update_rules()
        self._save()
        self._intel.ml("ScalpLearner",
            f"📚 Learned from {profile.symbol} launch | total launches: {len(self._profiles)}")

    def get_entry_signal(self, bar_num: int, price: float, open_price: float,
                         volume: float, avg_volume: float) -> ScalpSignal:
        """
        Given the current bar of a live launch, return a scalp entry/exit signal.
        """
        rules = self._rules
        if not rules or open_price <= 0:
            return ScalpSignal(
                symbol="", action="WAIT", confidence=0.3,
                reason="no learned rules yet", price=price, bar_num=bar_num,
                timestamp=datetime.now(timezone.utc).isoformat()
            )

        pct_from_open = (price - open_price) / open_price * 100
        vol_ratio = volume / (avg_volume + 1e-9)

        optimal_entry_bar = rules.get("avg_best_entry_bar", 2)
        optimal_entry_pct = rules.get("avg_best_entry_pct", 5.0)
        optimal_exit_bar  = rules.get("avg_best_exit_bar", 6)
        avg_peak_pct      = rules.get("avg_peak_pct", 20.0)
        avg_scalp         = rules.get("avg_scalp_pct", 5.0)
        win_rate          = rules.get("overall_win_rate", 0.5)

        action     = "WAIT"
        confidence = 0.3
        reason     = ""

        # Abort: price already 2× avg peak → overbought
        if pct_from_open > avg_peak_pct * 2:
            action     = "ABORT"
            confidence = 0.80
            reason     = f"price {pct_from_open:.0f}% above open – past typical peak"

        # Entry window: target bar reached + price in acceptable range
        elif bar_num >= optimal_entry_bar and abs(pct_from_open - optimal_entry_pct) < avg_peak_pct * 0.3:
            if vol_ratio > 1.5:
                action     = "ENTER_LONG"
                confidence = min(0.88, 0.5 + win_rate * 0.4)
                reason     = (f"entry window: bar {bar_num} | price {pct_from_open:+.1f}% from open | "
                              f"vol ratio {vol_ratio:.1f}× | expected scalp {avg_scalp:+.1f}%")

        # Exit window: reached target bar or volume collapsing
        elif bar_num >= optimal_exit_bar or (bar_num > 2 and vol_ratio < 0.3):
            action     = "EXIT_LONG"
            confidence = 0.75
            reason     = f"exit window: bar {bar_num} | vol_ratio {vol_ratio:.2f}"

        return ScalpSignal(
            symbol="", action=action, confidence=confidence,
            reason=reason, price=price, bar_num=bar_num,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    @property
    def rules(self) -> dict:
        return dict(self._rules)

    @property
    def profile_count(self) -> int:
        return len(self._profiles)

    # ── Internal ───────────────────────────────────────────────────────

    def _update_rules(self) -> None:
        if not self._profiles:
            return
        self._rules = {
            "avg_peak_pct":       float(np.mean([p.peak_pct_from_open for p in self._profiles])),
            "avg_peak_bar":       float(np.mean([p.peak_bar for p in self._profiles])),
            "avg_retrace_pct":    float(np.mean([p.first_retrace_pct for p in self._profiles])),
            "avg_stable_pct":     float(np.mean([p.stable_level_pct for p in self._profiles])),
            "avg_best_entry_bar": float(np.mean([p.best_entry_bar for p in self._profiles])),
            "avg_best_entry_pct": float(np.mean([p.best_entry_pct_from_open for p in self._profiles])),
            "avg_best_exit_bar":  float(np.mean([p.best_exit_bar for p in self._profiles])),
            "avg_scalp_pct":      float(np.mean([p.avg_scalp_pct for p in self._profiles])),
            "overall_win_rate":   float(np.mean([1 if p.avg_scalp_pct > 0 else 0 for p in self._profiles])),
            "sample_count":       len(self._profiles),
        }

    def _save(self) -> None:
        try:
            data = {
                "rules": self._rules,
                "profiles": [asdict(p) for p in self._profiles[-100:]],  # Keep last 100
            }
            self.RULES_FILE.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.debug(f"ScalpLearner save error: {exc}")

    def _load(self) -> None:
        try:
            if self.RULES_FILE.exists():
                data = json.loads(self.RULES_FILE.read_text())
                self._rules = data.get("rules", {})
                self._profiles = [LaunchProfile(**p) for p in data.get("profiles", [])]
                logger.debug(f"ScalpLearner: loaded {len(self._profiles)} launch profiles")
        except Exception as exc:
            logger.debug(f"ScalpLearner load error: {exc}")


# ── New token watcher ─────────────────────────────────────────────────────────

class NewTokenWatcher:
    """
    Monitors Binance for newly listed tokens.
    When a new token appears, starts collecting 1-minute candles for the first 10 minutes,
    feeds data to LaunchAnalyser and ScalpLearner,
    and broadcasts real-time scalp signals via callbacks.
    """

    MONITOR_INTERVAL_SEC = 60          # Check for new listings every minute
    LAUNCH_TRACK_MINUTES = 10          # Track first N minutes of each launch
    MIN_VOLUME_USD_LAUNCH = 50_000     # Min USD volume to be considered a real launch

    def __init__(self, binance_client=None) -> None:
        self._client = binance_client
        self._intel = get_intel_logger()
        self._analyser = LaunchAnalyser()
        self._learner  = ScalpLearner()
        self._known_symbols: set[str] = set()
        self._active_launches: dict[str, list[LaunchCandle]] = {}  # symbol → candles so far
        self._launch_open_prices: dict[str, float] = {}
        self._launch_avg_volumes: dict[str, float] = {}
        self._signal_callbacks: list[Callable[[ScalpSignal], None]] = []
        self._event_callbacks: list[Callable[[str, LaunchProfile], None]] = []
        self._running = False
        self._lock = threading.Lock()

    def on_signal(self, cb: Callable[[ScalpSignal], None]) -> None:
        """Register callback for real-time scalp signals during a launch."""
        self._signal_callbacks.append(cb)

    def on_launch(self, cb: Callable[[str, LaunchProfile], None]) -> None:
        """Register callback called when a launch finishes (symbol, profile)."""
        self._event_callbacks.append(cb)

    def start(self) -> None:
        self._running = True
        # Load currently known symbols
        self._known_symbols = self._fetch_all_symbols()
        self._intel.ml("NewTokenWatcher",
            f"🔭 New token watcher started | monitoring {len(self._known_symbols)} symbols | "
            f"learned from {self._learner.profile_count} past launches")
        t = threading.Thread(target=self._monitor_loop, daemon=True, name="new-token-watcher")
        t.start()

    def stop(self) -> None:
        self._running = False

    @property
    def learner(self) -> ScalpLearner:
        return self._learner

    # ── Internal loops ─────────────────────────────────────────────────

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                current_symbols = self._fetch_all_symbols()
                new_symbols = current_symbols - self._known_symbols
                if new_symbols:
                    for sym in new_symbols:
                        self._intel.ml("NewTokenWatcher",
                            f"🚀 NEW LISTING DETECTED: {sym} – starting launch tracking!")
                        t = threading.Thread(
                            target=self._track_launch, args=(sym,),
                            daemon=True, name=f"launch-{sym}"
                        )
                        t.start()
                    self._known_symbols = current_symbols
                time.sleep(self.MONITOR_INTERVAL_SEC)
            except Exception as exc:
                logger.debug(f"NewTokenWatcher monitor loop error: {exc}")
                time.sleep(10)

    def _track_launch(self, symbol: str) -> None:
        """Track a single new token for the first LAUNCH_TRACK_MINUTES minutes."""
        candles: list[LaunchCandle] = []
        bar_num = 0
        open_price = 0.0
        avg_vol_baseline = 0.0

        self._intel.ml("NewTokenWatcher",
            f"⏱ [{symbol}] Tracking launch – collecting first {self.LAUNCH_TRACK_MINUTES} minutes…")

        for bar_num in range(self.LAUNCH_TRACK_MINUTES):
            if not self._running:
                break
            try:
                if self._client:
                    raw = self._client.get_klines(symbol, "1m", limit=1)
                    if raw:
                        k = raw[-1]
                        candle = LaunchCandle(
                            timestamp=float(k[0]),
                            open=float(k[1]),
                            high=float(k[2]),
                            low=float(k[3]),
                            close=float(k[4]),
                            volume=float(k[5]),
                            bar_num=bar_num,
                        )
                        candles.append(candle)
                        if bar_num == 0:
                            open_price = candle.open
                        if bar_num == 1:
                            avg_vol_baseline = candle.volume

                        # Generate real-time scalp signal
                        if open_price > 0:
                            avg_vol = avg_vol_baseline or candle.volume
                            signal = self._learner.get_entry_signal(
                                bar_num=bar_num,
                                price=candle.close,
                                open_price=open_price,
                                volume=candle.volume,
                                avg_volume=avg_vol,
                            )
                            signal.symbol = symbol
                            self._fire_signal(signal)

                            pct = (candle.close - open_price) / open_price * 100
                            self._intel.ml("NewTokenWatcher",
                                f"[{symbol}] Bar {bar_num}: close={candle.close:.4f} "
                                f"({pct:+.1f}%) vol={candle.volume:.0f} | signal={signal.action}")
            except Exception as exc:
                logger.debug(f"NewTokenWatcher track error [{symbol}] bar {bar_num}: {exc}")

            time.sleep(60)   # Wait for next 1-minute bar

        # Analyse launch and learn from it
        if len(candles) >= 3:
            profile = self._analyser.analyse(symbol, candles)
            self._learner.add_profile(profile)
            for cb in self._event_callbacks:
                try:
                    cb(symbol, profile)
                except Exception:
                    pass

        self._intel.ml("NewTokenWatcher",
            f"✅ [{symbol}] Launch tracking complete | {len(candles)} bars collected")

    def _fire_signal(self, signal: ScalpSignal) -> None:
        for cb in self._signal_callbacks:
            try:
                cb(signal)
            except Exception:
                pass

    def _fetch_all_symbols(self) -> set[str]:
        """Get the full set of currently traded USDT pairs."""
        if self._client:
            try:
                info = self._client.get_exchange_info()
                return {
                    s["symbol"] for s in info.get("symbols", [])
                    if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
                }
            except Exception:
                pass
        return set()
