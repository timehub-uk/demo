"""
Minimal pandas_ta compatibility shim.
Implements only the functions used by data_collector.py and archive_downloader.py
using pure numpy/pandas so the project runs without the pandas-ta package.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(close: pd.Series, length: int = 14, **kwargs) -> pd.Series:
    return close.ewm(span=length, adjust=False).mean()


def rsi(close: pd.Series, length: int = 14, **kwargs) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    **kwargs,
) -> pd.DataFrame:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({
        f"MACD_{fast}_{slow}_{signal}": macd_line,
        f"MACDs_{fast}_{slow}_{signal}": signal_line,
        f"MACDh_{fast}_{slow}_{signal}": hist,
    })


def bbands(
    close: pd.Series,
    length: int = 20,
    std: float = 2.0,
    **kwargs,
) -> pd.DataFrame:
    mid = close.rolling(length).mean()
    stddev = close.rolling(length).std(ddof=0)
    upper = mid + std * stddev
    lower = mid - std * stddev
    return pd.DataFrame({
        f"BBU_{length}_{std}": upper,
        f"BBM_{length}_{std}": mid,
        f"BBL_{length}_{std}": lower,
        f"BBB_{length}_{std}": (upper - lower) / mid,
    })


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 14,
    **kwargs,
) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def obv(close: pd.Series, volume: pd.Series, **kwargs) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 14,
    **kwargs,
) -> pd.DataFrame:
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    dm_plus = high - prev_high
    dm_minus = prev_low - low
    dm_plus = dm_plus.where((dm_plus > dm_minus) & (dm_plus > 0), 0.0)
    dm_minus = dm_minus.where((dm_minus > dm_plus) & (dm_minus > 0), 0.0)

    atr_s = tr.ewm(alpha=1 / length, adjust=False).mean()
    di_plus = 100 * dm_plus.ewm(alpha=1 / length, adjust=False).mean() / atr_s.replace(0, np.nan)
    di_minus = 100 * dm_minus.ewm(alpha=1 / length, adjust=False).mean() / atr_s.replace(0, np.nan)

    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx_val = dx.ewm(alpha=1 / length, adjust=False).mean()

    return pd.DataFrame({
        f"ADX_{length}": adx_val,
        f"DMP_{length}": di_plus,
        f"DMN_{length}": di_minus,
    })
