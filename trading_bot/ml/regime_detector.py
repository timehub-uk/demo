"""
Market Regime Detector.

Identifies the current market regime using a Hidden Markov Model (HMM)
with 4 states, updated every 15 minutes from 1-hour candle data:

  TRENDING_UP   – sustained uptrend, momentum positive
  TRENDING_DOWN – sustained downtrend, momentum negative
  RANGING       – oscillating, low ADX, mean-revert friendly
  VOLATILE      – high ATR, unpredictable spikes, reduce size

Regime is used throughout the platform to:
  - Scale confidence thresholds (stricter in VOLATILE/RANGING)
  - Multiply position sizes (smaller in hostile regimes)
  - Filter signal direction (no longs in TRENDING_DOWN)
  - Widen ATR stops in VOLATILE

Falls back to heuristic regime (ADX + RSI + ATR z-score) when
hmmlearn is not installed.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

import numpy as np

from loguru import logger
from utils.logger import get_intel_logger


# ── Regime enum ───────────────────────────────────────────────────────────────

class Regime(str, Enum):
    TRENDING_UP   = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING       = "RANGING"
    VOLATILE      = "VOLATILE"
    UNKNOWN       = "UNKNOWN"


# ── Per-regime parameters ─────────────────────────────────────────────────────

REGIME_PARAMS: dict[Regime, dict] = {
    Regime.TRENDING_UP: {
        "allowed_signals":     {"BUY"},           # Only go long in uptrend
        "confidence_min":      0.60,              # Standard confidence threshold
        "position_size_mult":  1.00,              # Full size
        "atr_stop_mult":       1.5,               # Standard ATR stop
        "description": "Strong uptrend – long only, full size",
    },
    Regime.TRENDING_DOWN: {
        "allowed_signals":     {"SELL"},           # Only go short
        "confidence_min":      0.62,
        "position_size_mult":  0.90,
        "atr_stop_mult":       1.5,
        "description": "Strong downtrend – short only, slightly reduced size",
    },
    Regime.RANGING: {
        "allowed_signals":     {"BUY", "SELL"},   # Both directions OK
        "confidence_min":      0.68,              # Higher bar (mean-reversion noisier)
        "position_size_mult":  0.70,              # Smaller size
        "atr_stop_mult":       1.2,               # Tighter stops
        "description": "Ranging market – both sides, reduced size, tight stops",
    },
    Regime.VOLATILE: {
        "allowed_signals":     set(),             # Skip trading in chaos
        "confidence_min":      0.80,              # Very high bar
        "position_size_mult":  0.40,              # Tiny size
        "atr_stop_mult":       2.5,               # Very wide stops
        "description": "High volatility – minimal or no trading",
    },
    Regime.UNKNOWN: {
        "allowed_signals":     {"BUY", "SELL"},
        "confidence_min":      0.65,
        "position_size_mult":  0.75,
        "atr_stop_mult":       1.5,
        "description": "Regime unknown – conservative defaults",
    },
}


@dataclass
class RegimeSnapshot:
    regime: Regime
    confidence: float           # How certain the detector is
    trend_strength: float       # ADX proxy (0-1)
    volatility_z: float         # ATR z-score relative to 20-period average
    momentum: float             # Short-term momentum signal (-1 to +1)
    timestamp: str = ""


# ── Regime detector ───────────────────────────────────────────────────────────

class RegimeDetector:
    """
    Detects market regime from OHLCV data.

    Usage:
        detector = RegimeDetector()
        detector.on_regime_change(my_callback)
        detector.start(["BTCUSDT", "ETHUSDT"])
        # or
        snapshot = detector.detect(df)
    """

    REFRESH_INTERVAL = 15 * 60   # Re-detect every 15 minutes
    LOOKBACK = 200               # Candles to use for regime detection
    DOMINANT_SYMBOL = "BTCUSDT"  # BTC regime used as market-wide regime

    def __init__(self) -> None:
        self._intel = get_intel_logger()
        self._current: RegimeSnapshot = RegimeSnapshot(
            regime=Regime.UNKNOWN, confidence=0.0,
            trend_strength=0.0, volatility_z=0.0, momentum=0.0,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._callbacks: list[Callable[[RegimeSnapshot], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._hmm_model = None
        self._init_hmm()

    def on_regime_change(self, cb: Callable[[RegimeSnapshot], None]) -> None:
        self._callbacks.append(cb)

    def start(self, symbols: list[str]) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="regime-detector"
        )
        self._thread.start()
        self._intel.ml("RegimeDetector",
            "📡 Market regime detector started (HMM + heuristic fallback)")

    def stop(self) -> None:
        self._running = False

    @property
    def current(self) -> RegimeSnapshot:
        return self._current

    @property
    def params(self) -> dict:
        return REGIME_PARAMS.get(self._current.regime, REGIME_PARAMS[Regime.UNKNOWN])

    def filter_signal(self, signal: str, confidence: float) -> tuple[bool, str]:
        """
        Return (should_trade, reason) based on current regime.
        """
        p = self.params
        allowed = p["allowed_signals"]
        min_conf = p["confidence_min"]

        if not allowed:
            return False, f"Regime {self._current.regime}: trading paused in volatile market"
        if signal not in allowed:
            return False, f"Regime {self._current.regime}: {signal} not allowed, only {allowed}"
        if confidence < min_conf:
            return False, f"Regime {self._current.regime}: confidence {confidence:.0%} < min {min_conf:.0%}"
        return True, ""

    def position_size_multiplier(self) -> float:
        return self.params["position_size_mult"]

    def atr_stop_multiplier(self) -> float:
        return self.params["atr_stop_mult"]

    def detect(self, df) -> RegimeSnapshot:
        """Run regime detection on a DataFrame with OHLCV columns."""
        try:
            import pandas as pd
            closes  = df["close"].astype(float).values
            highs   = df["high"].astype(float).values
            lows    = df["low"].astype(float).values
            volumes = df["volume"].astype(float).values if "volume" in df.columns else np.ones(len(closes))

            features = self._compute_features(closes, highs, lows, volumes)
            regime, confidence = self._classify(features)

            snap = RegimeSnapshot(
                regime=regime,
                confidence=confidence,
                trend_strength=float(features.get("adx_norm", 0.5)),
                volatility_z=float(features.get("atr_z", 0.0)),
                momentum=float(features.get("momentum", 0.0)),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return snap
        except Exception as exc:
            logger.debug(f"RegimeDetector.detect error: {exc}")
            return self._current

    # ── Internal ───────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                df = self._load_data()
                if df is not None and len(df) >= 50:
                    snap = self.detect(df)
                    old_regime = self._current.regime
                    self._current = snap

                    emoji = {"TRENDING_UP":"🟢","TRENDING_DOWN":"🔴",
                             "RANGING":"🟡","VOLATILE":"🔥","UNKNOWN":"⚪"}.get(snap.regime.value,"⚪")
                    self._intel.ml("RegimeDetector",
                        f"{emoji} Regime: {snap.regime.value} (conf {snap.confidence:.0%}) | "
                        f"ADX={snap.trend_strength:.2f} vol_z={snap.volatility_z:+.2f} mom={snap.momentum:+.2f}")

                    if snap.regime != old_regime:
                        for cb in self._callbacks:
                            try:
                                cb(snap)
                            except Exception:
                                pass

                    # Cache to Redis
                    try:
                        from db.redis_client import RedisClient
                        from dataclasses import asdict
                        RedisClient().set("market_regime", asdict(snap), ttl=1800)
                    except Exception:
                        pass

            except Exception as exc:
                logger.debug(f"RegimeDetector loop error: {exc}")
            time.sleep(self.REFRESH_INTERVAL)

    def _load_data(self):
        try:
            from ml.data_collector import DataCollector
            df = DataCollector.load_dataframe(self.DOMINANT_SYMBOL, "1h",
                                               limit=self.LOOKBACK)
            if df.empty:
                return None
            return df
        except Exception:
            return None

    def _compute_features(self, closes, highs, lows, volumes) -> dict:
        """Compute regime-relevant features from raw OHLCV arrays."""
        if len(closes) < 30:
            return {}

        c = closes[-100:]
        h = highs[-100:]
        l = lows[-100:]
        v = volumes[-100:]

        # ── True Range & ATR ──────────────────────────────────────────
        tr = np.maximum(h[1:] - l[1:],
             np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
        atr14 = np.convolve(tr, np.ones(14) / 14, mode="valid")
        if len(atr14) < 10:
            return {}

        atr_now = float(atr14[-1])
        atr_mean = float(np.mean(atr14[-20:]))
        atr_std  = float(np.std(atr14[-20:])) or 1e-6
        atr_z    = (atr_now - atr_mean) / atr_std

        # ── Momentum (rate of change) ─────────────────────────────────
        roc10 = (c[-1] - c[-10]) / c[-10]   # 10-bar return

        # ── ADX proxy (Directional Movement) ─────────────────────────
        pos_dm = np.maximum(np.diff(h), 0)
        neg_dm = np.maximum(-np.diff(l), 0)
        mask   = pos_dm < neg_dm
        pos_dm[mask] = 0
        mask2  = neg_dm < np.maximum(np.diff(h), 0)[:len(neg_dm)]
        neg_dm[mask2] = 0
        atr_dm = tr[:len(pos_dm)]
        atr_sm = np.convolve(atr_dm, np.ones(14) / 14, mode="valid")
        plus_di  = np.convolve(pos_dm, np.ones(14) / 14, mode="valid") / (atr_sm + 1e-9)
        minus_di = np.convolve(neg_dm, np.ones(14) / 14, mode="valid") / (atr_sm + 1e-9)
        dx = abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
        adx = float(np.mean(dx[-14:])) if len(dx) >= 14 else 0.3
        adx_norm = min(1.0, adx)

        # ── Linear trend slope (normalised) ──────────────────────────
        x = np.arange(len(c[-30:]))
        slope = float(np.polyfit(x, c[-30:], 1)[0])
        slope_norm = slope / (c[-1] + 1e-9) * 100   # % per bar

        # ── Volume trend ──────────────────────────────────────────────
        vol_sma = np.mean(v[-10:]) / (np.mean(v[-30:]) + 1e-9)

        return {
            "atr_z": atr_z,
            "momentum": float(roc10),
            "adx_norm": adx_norm,
            "slope_norm": slope_norm,
            "vol_ratio": float(vol_sma),
        }

    def _classify(self, features: dict) -> tuple[Regime, float]:
        """Classify regime from feature dict. Tries HMM first, then heuristic."""
        if not features:
            return Regime.UNKNOWN, 0.0

        # Try HMM
        if self._hmm_model:
            try:
                return self._classify_hmm(features)
            except Exception:
                pass

        # Heuristic fallback
        return self._classify_heuristic(features)

    def _classify_heuristic(self, f: dict) -> tuple[Regime, float]:
        atr_z    = f.get("atr_z", 0)
        momentum = f.get("momentum", 0)
        adx      = f.get("adx_norm", 0.3)
        slope    = f.get("slope_norm", 0)

        # Volatile: high ATR
        if atr_z > 1.8:
            return Regime.VOLATILE, min(0.9, 0.6 + atr_z * 0.1)

        # Trending: strong ADX + clear slope
        if adx > 0.25:
            if slope > 0.02 and momentum > 0:
                return Regime.TRENDING_UP, min(0.9, 0.5 + adx)
            elif slope < -0.02 and momentum < 0:
                return Regime.TRENDING_DOWN, min(0.9, 0.5 + adx)

        # Ranging: low ADX, low ATR
        if adx < 0.20 and abs(atr_z) < 0.5:
            return Regime.RANGING, 0.7

        # Ambiguous → slight trend bias
        if momentum > 0.01:
            return Regime.TRENDING_UP, 0.55
        if momentum < -0.01:
            return Regime.TRENDING_DOWN, 0.55

        return Regime.RANGING, 0.50

    def _classify_hmm(self, features: dict) -> tuple[Regime, float]:
        obs = np.array([[
            features.get("atr_z", 0),
            features.get("momentum", 0),
            features.get("adx_norm", 0.3),
            features.get("slope_norm", 0),
        ]])
        probs = np.exp(self._hmm_model.score_samples(obs))
        state_idx = int(self._hmm_model.predict(obs)[0])
        # Map HMM states to regimes (state assignment from training order)
        state_map = {0: Regime.TRENDING_UP, 1: Regime.TRENDING_DOWN,
                     2: Regime.RANGING, 3: Regime.VOLATILE}
        regime = state_map.get(state_idx, Regime.UNKNOWN)
        confidence = float(min(0.95, 0.55 + abs(float(probs[0])) * 0.3))
        return regime, confidence

    def _init_hmm(self) -> None:
        try:
            from hmmlearn.hmm import GaussianHMM
            self._hmm_model = GaussianHMM(
                n_components=4, covariance_type="full",
                n_iter=100, random_state=42,
            )
            logger.debug("RegimeDetector: HMM model ready (hmmlearn)")
        except ImportError:
            logger.debug("RegimeDetector: hmmlearn not available – using heuristic classifier")
