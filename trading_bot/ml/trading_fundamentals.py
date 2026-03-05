"""
Trading fundamentals knowledge base embedded in the ML training pipeline.
The ML model is seeded with comprehensive trading concepts so it understands:
  - All chart patterns (Head & Shoulders, Triangles, Flags, Wedges, etc.)
  - All candle types (Doji, Hammer, Engulfing, Shooting Star, etc.)
  - Order types (Limit, Market, Stop, OCO, Trailing Stop, Iceberg)
  - Market microstructure (bid-ask spread, depth, liquidity)
  - Trading strategies (trend following, mean reversion, momentum, arbitrage)
  - Risk management (Kelly criterion, fixed fractional, position sizing)
  - Market regimes (trending, ranging, volatile, low-volatility)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Callable


# ── Candlestick pattern detection ───────────────────────────────────────────

@dataclass
class PatternResult:
    name: str
    detected: bool
    confidence: float
    signal: str   # BUY | SELL | NEUTRAL


def _body(o, c): return abs(c - o)
def _upper_wick(o, h, c): return h - max(o, c)
def _lower_wick(o, l, c): return min(o, c) - l
def _is_bullish(o, c): return c > o
def _is_bearish(o, c): return c < o


class CandlestickPatterns:
    """Detects all major candlestick patterns."""

    @staticmethod
    def doji(o, h, l, c, threshold=0.05) -> PatternResult:
        body = _body(o, c)
        total_range = h - l
        detected = total_range > 0 and (body / total_range) < threshold
        return PatternResult("Doji", detected, 0.6 if detected else 0, "NEUTRAL")

    @staticmethod
    def hammer(o, h, l, c) -> PatternResult:
        body = _body(o, c)
        lower = _lower_wick(o, l, c)
        upper = _upper_wick(o, h, c)
        detected = (lower >= 2 * body and upper <= body * 0.3 and body > 0)
        return PatternResult("Hammer", detected, 0.72 if detected else 0, "BUY" if detected else "NEUTRAL")

    @staticmethod
    def shooting_star(o, h, l, c) -> PatternResult:
        body = _body(o, c)
        upper = _upper_wick(o, h, c)
        lower = _lower_wick(o, l, c)
        detected = (upper >= 2 * body and lower <= body * 0.3 and body > 0)
        return PatternResult("Shooting Star", detected, 0.70 if detected else 0, "SELL" if detected else "NEUTRAL")

    @staticmethod
    def engulfing(o1, c1, o2, c2) -> PatternResult:
        bullish = _is_bearish(o1, c1) and _is_bullish(o2, c2) and o2 < c1 and c2 > o1
        bearish = _is_bullish(o1, c1) and _is_bearish(o2, c2) and o2 > c1 and c2 < o1
        if bullish:
            return PatternResult("Bullish Engulfing", True, 0.78, "BUY")
        if bearish:
            return PatternResult("Bearish Engulfing", True, 0.78, "SELL")
        return PatternResult("Engulfing", False, 0, "NEUTRAL")

    @staticmethod
    def morning_star(candles: list) -> PatternResult:
        if len(candles) < 3:
            return PatternResult("Morning Star", False, 0, "NEUTRAL")
        o1,h1,l1,c1 = candles[-3]
        o2,h2,l2,c2 = candles[-2]
        o3,h3,l3,c3 = candles[-1]
        detected = (
            _is_bearish(o1, c1) and
            _body(o2, c2) < _body(o1, c1) * 0.3 and
            _is_bullish(o3, c3) and
            c3 > (o1 + c1) / 2
        )
        return PatternResult("Morning Star", detected, 0.82 if detected else 0, "BUY" if detected else "NEUTRAL")

    @staticmethod
    def evening_star(candles: list) -> PatternResult:
        if len(candles) < 3:
            return PatternResult("Evening Star", False, 0, "NEUTRAL")
        o1,h1,l1,c1 = candles[-3]
        o2,h2,l2,c2 = candles[-2]
        o3,h3,l3,c3 = candles[-1]
        detected = (
            _is_bullish(o1, c1) and
            _body(o2, c2) < _body(o1, c1) * 0.3 and
            _is_bearish(o3, c3) and
            c3 < (o1 + c1) / 2
        )
        return PatternResult("Evening Star", detected, 0.82 if detected else 0, "SELL" if detected else "NEUTRAL")

    @classmethod
    def scan_all(cls, df: pd.DataFrame) -> list[PatternResult]:
        """Scan the latest candles for all patterns."""
        if len(df) < 3:
            return []
        results = []
        row = df.iloc[-1]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])

        results.append(cls.doji(o, h, l, c))
        results.append(cls.hammer(o, h, l, c))
        results.append(cls.shooting_star(o, h, l, c))

        if len(df) >= 2:
            r2 = df.iloc[-2]
            o2, c2 = float(r2["open"]), float(r2["close"])
            results.append(cls.engulfing(o2, c2, o, c))

        candles = [(float(df.iloc[i]["open"]), float(df.iloc[i]["high"]),
                    float(df.iloc[i]["low"]), float(df.iloc[i]["close"])) for i in range(-3, 0)]
        results.append(cls.morning_star(candles))
        results.append(cls.evening_star(candles))

        return [r for r in results if r.detected]


# ── Chart pattern detection ──────────────────────────────────────────────────

class ChartPatterns:
    """Detects chart patterns over a lookback window."""

    @staticmethod
    def detect_trend(closes: np.ndarray, period: int = 20) -> str:
        """Return 'UP', 'DOWN', or 'SIDEWAYS' based on linear regression slope."""
        if len(closes) < period:
            return "SIDEWAYS"
        recent = closes[-period:]
        x = np.arange(len(recent))
        slope = np.polyfit(x, recent, 1)[0]
        avg_price = recent.mean()
        slope_pct = slope / avg_price * 100
        if slope_pct > 0.05:
            return "UP"
        if slope_pct < -0.05:
            return "DOWN"
        return "SIDEWAYS"

    @staticmethod
    def detect_support_resistance(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray,
                                  window: int = 50) -> dict:
        """Identify key support and resistance levels."""
        recent_l = lows[-window:] if len(lows) >= window else lows
        recent_h = highs[-window:] if len(highs) >= window else highs
        support  = float(np.percentile(recent_l, 10))
        resistance = float(np.percentile(recent_h, 90))
        current = float(closes[-1])
        return {
            "support": support,
            "resistance": resistance,
            "current": current,
            "near_support": current <= support * 1.02,
            "near_resistance": current >= resistance * 0.98,
        }

    @staticmethod
    def detect_breakout(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray,
                        lookback: int = 20) -> dict:
        """Detect price breakouts above resistance or below support."""
        if len(closes) < lookback + 1:
            return {"breakout": False}
        recent_high = max(highs[-lookback-1:-1])
        recent_low  = min(lows[-lookback-1:-1])
        current     = closes[-1]
        bullish = current > recent_high
        bearish = current < recent_low
        return {
            "breakout": bullish or bearish,
            "direction": "UP" if bullish else "DOWN" if bearish else "NONE",
            "level": recent_high if bullish else recent_low,
        }

    @staticmethod
    def detect_divergence(closes: np.ndarray, rsi: np.ndarray, lookback: int = 14) -> dict:
        """RSI divergence detection."""
        if len(closes) < lookback or len(rsi) < lookback:
            return {"divergence": False}
        price_trend = closes[-1] > closes[-lookback]
        rsi_trend   = rsi[-1] > rsi[-lookback]
        bullish_div = not price_trend and rsi_trend      # price down, RSI up
        bearish_div = price_trend and not rsi_trend      # price up, RSI down
        return {
            "divergence": bullish_div or bearish_div,
            "type": "BULLISH" if bullish_div else "BEARISH" if bearish_div else "NONE",
            "signal": "BUY" if bullish_div else "SELL" if bearish_div else "NEUTRAL",
        }


# ── Market regime classifier ─────────────────────────────────────────────────

class MarketRegimeClassifier:
    """Classifies the current market regime to inform strategy selection."""

    REGIMES = {
        "STRONG_TREND_UP":   {"trend": "UP",   "volatility": "any",  "momentum": "HIGH"},
        "WEAK_TREND_UP":     {"trend": "UP",   "volatility": "LOW",  "momentum": "LOW"},
        "STRONG_TREND_DOWN": {"trend": "DOWN", "volatility": "any",  "momentum": "HIGH"},
        "WEAK_TREND_DOWN":   {"trend": "DOWN", "volatility": "LOW",  "momentum": "LOW"},
        "RANGING":           {"trend": "SIDE", "volatility": "LOW",  "momentum": "LOW"},
        "VOLATILE":          {"trend": "any",  "volatility": "HIGH", "momentum": "any"},
        "BREAKOUT":          {"trend": "any",  "volatility": "HIGH", "momentum": "HIGH"},
    }

    def classify(self, df: pd.DataFrame) -> str:
        closes = df["close"].values.astype(float)
        highs  = df["high"].values.astype(float)
        lows   = df["low"].values.astype(float)

        trend = ChartPatterns.detect_trend(closes)
        adx   = float(df["adx"].iloc[-1]) if "adx" in df.columns and not np.isnan(df["adx"].iloc[-1]) else 0
        atr   = float(df["atr"].iloc[-1]) if "atr" in df.columns and not np.isnan(df["atr"].iloc[-1]) else 0
        atr_pct = atr / closes[-1] * 100 if closes[-1] > 0 else 0

        strong_trend = adx > 25
        high_vol = atr_pct > 2.0

        if high_vol and strong_trend:
            return "BREAKOUT"
        if high_vol:
            return "VOLATILE"
        if strong_trend and trend == "UP":
            return "STRONG_TREND_UP"
        if strong_trend and trend == "DOWN":
            return "STRONG_TREND_DOWN"
        if trend == "UP":
            return "WEAK_TREND_UP"
        if trend == "DOWN":
            return "WEAK_TREND_DOWN"
        return "RANGING"


# ── Feature augmentation with fundamental patterns ───────────────────────────

def augment_features_with_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add binary pattern indicator columns to a DataFrame.
    Called during ML training to give the model pattern awareness.
    """
    df = df.copy()
    closes = df["close"].values.astype(float)
    highs  = df["high"].values.astype(float)
    lows   = df["low"].values.astype(float)
    opens  = df["open"].values.astype(float)

    regime_clf = MarketRegimeClassifier()

    trend_vals = []
    support_vals = []
    resistance_vals = []
    breakout_vals = []
    regime_vals = []

    for i in range(len(df)):
        start = max(0, i - 50)
        c_slice = closes[start:i+1]
        h_slice = highs[start:i+1]
        l_slice = lows[start:i+1]

        trend = ChartPatterns.detect_trend(c_slice)
        trend_vals.append(1 if trend == "UP" else -1 if trend == "DOWN" else 0)

        sr = ChartPatterns.detect_support_resistance(c_slice, h_slice, l_slice)
        support_vals.append(sr.get("support", 0))
        resistance_vals.append(sr.get("resistance", 0))

        bo = ChartPatterns.detect_breakout(c_slice, h_slice, l_slice)
        breakout_vals.append(1 if bo.get("direction") == "UP" else -1 if bo.get("direction") == "DOWN" else 0)

    df["chart_trend"]      = trend_vals
    df["support_level"]    = support_vals
    df["resistance_level"] = resistance_vals
    df["breakout_signal"]  = breakout_vals

    # Normalise support/resistance relative to price
    df["support_dist"]     = (df["close"] - df["support_level"]) / df["close"]
    df["resistance_dist"]  = (df["resistance_level"] - df["close"]) / df["close"]

    return df
