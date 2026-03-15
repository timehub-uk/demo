"""
pandas-ta compatibility router.

Tries the installed pandas-ta package first (requires Python >=3.12).
If unavailable, falls back to the pure numpy/pandas shim below which
covers the indicators used throughout this project.

Consumers can check ``pandas_ta.USING_REAL_PANDAS_TA`` (bool) to know
which backend is active.  When the real package is loaded this module is
replaced in sys.modules, so all 130+ indicators are automatically available.
"""
from __future__ import annotations

import pathlib
import sys

_THIS_DIR = str(pathlib.Path(__file__).parent.resolve())


def _load_real() -> "object | None":
    """Import the real pandas-ta package, bypassing this shim file."""
    saved = sys.path[:]
    sys.path = [p for p in sys.path
                if str(pathlib.Path(p).resolve()) != _THIS_DIR]
    try:
        import importlib
        return importlib.import_module("pandas_ta")
    except Exception:
        return None
    finally:
        sys.path[:] = saved


_real = _load_real()

if _real is not None:
    # Hand off entirely to the real package; all 130+ indicators available.
    sys.modules[__name__] = _real

else:
    # ── Pure numpy/pandas fallback ────────────────────────────────────────────
    USING_REAL_PANDAS_TA = False

    import numpy as np
    import pandas as pd

    # ── Trend ─────────────────────────────────────────────────────────────────

    def sma(close: pd.Series, length: int = 20, **kwargs) -> pd.Series:
        return close.rolling(length).mean()

    def ema(close: pd.Series, length: int = 14, **kwargs) -> pd.Series:
        return close.ewm(span=length, adjust=False).mean()

    def wma(close: pd.Series, length: int = 10, **kwargs) -> pd.Series:
        weights = np.arange(1, length + 1, dtype=float)
        return close.rolling(length).apply(
            lambda x: np.dot(x, weights) / weights.sum(), raw=True
        )

    def dema(close: pd.Series, length: int = 10, **kwargs) -> pd.Series:
        e = ema(close, length)
        return 2 * e - ema(e, length)

    def tema(close: pd.Series, length: int = 10, **kwargs) -> pd.Series:
        e1 = ema(close, length)
        e2 = ema(e1, length)
        e3 = ema(e2, length)
        return 3 * e1 - 3 * e2 + e3

    def psar(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        af0: float = 0.02,
        af: float = 0.02,
        max_af: float = 0.2,
        **kwargs,
    ) -> pd.DataFrame:
        """Parabolic SAR (simplified)."""
        n = len(close)
        sar = close.copy() * np.nan
        bull = pd.Series([True] * n, index=close.index)
        ep = pd.Series([0.0] * n, index=close.index)
        _af = pd.Series([af0] * n, index=close.index)

        sar.iloc[0] = low.iloc[0]
        bull.iloc[0] = True
        ep.iloc[0] = high.iloc[0]

        for i in range(1, n):
            prev_sar = sar.iloc[i - 1]
            prev_bull = bull.iloc[i - 1]
            prev_ep = ep.iloc[i - 1]
            prev_af = _af.iloc[i - 1]

            if prev_bull:
                new_sar = prev_sar + prev_af * (prev_ep - prev_sar)
                new_sar = min(new_sar, low.iloc[i - 1],
                              low.iloc[i - 2] if i >= 2 else low.iloc[i - 1])
                if low.iloc[i] < new_sar:
                    bull.iloc[i] = False
                    sar.iloc[i] = prev_ep
                    ep.iloc[i] = low.iloc[i]
                    _af.iloc[i] = af0
                else:
                    bull.iloc[i] = True
                    sar.iloc[i] = new_sar
                    if high.iloc[i] > prev_ep:
                        ep.iloc[i] = high.iloc[i]
                        _af.iloc[i] = min(prev_af + af, max_af)
                    else:
                        ep.iloc[i] = prev_ep
                        _af.iloc[i] = prev_af
            else:
                new_sar = prev_sar + prev_af * (prev_ep - prev_sar)
                new_sar = max(new_sar, high.iloc[i - 1],
                              high.iloc[i - 2] if i >= 2 else high.iloc[i - 1])
                if high.iloc[i] > new_sar:
                    bull.iloc[i] = True
                    sar.iloc[i] = prev_ep
                    ep.iloc[i] = high.iloc[i]
                    _af.iloc[i] = af0
                else:
                    bull.iloc[i] = False
                    sar.iloc[i] = new_sar
                    if low.iloc[i] < prev_ep:
                        ep.iloc[i] = low.iloc[i]
                        _af.iloc[i] = min(prev_af + af, max_af)
                    else:
                        ep.iloc[i] = prev_ep
                        _af.iloc[i] = prev_af

        return pd.DataFrame({"PSARl_0.02_0.2": sar.where(bull),
                              "PSARs_0.02_0.2": sar.where(~bull)})

    # ── Momentum ──────────────────────────────────────────────────────────────

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

    def stoch(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        k: int = 14,
        d: int = 3,
        smooth_k: int = 3,
        **kwargs,
    ) -> pd.DataFrame:
        lowest = low.rolling(k).min()
        highest = high.rolling(k).max()
        fast_k = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
        slow_k = fast_k.rolling(smooth_k).mean()
        slow_d = slow_k.rolling(d).mean()
        return pd.DataFrame({
            f"STOCHk_{k}_{d}_{smooth_k}": slow_k,
            f"STOCHd_{k}_{d}_{smooth_k}": slow_d,
        })

    def willr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        length: int = 14,
        **kwargs,
    ) -> pd.Series:
        highest = high.rolling(length).max()
        lowest = low.rolling(length).min()
        return -100 * (highest - close) / (highest - lowest).replace(0, np.nan)

    def cci(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        length: int = 14,
        c: float = 0.015,
        **kwargs,
    ) -> pd.Series:
        tp = (high + low + close) / 3
        mean_tp = tp.rolling(length).mean()
        mad = tp.rolling(length).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
        return (tp - mean_tp) / (c * mad.replace(0, np.nan))

    def mfi(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        volume: pd.Series,
        length: int = 14,
        **kwargs,
    ) -> pd.Series:
        tp = (high + low + close) / 3
        mf = tp * volume
        pos = mf.where(tp > tp.shift(1), 0.0)
        neg = mf.where(tp < tp.shift(1), 0.0)
        pos_sum = pos.rolling(length).sum()
        neg_sum = neg.rolling(length).sum()
        mfr = pos_sum / neg_sum.replace(0, np.nan)
        return 100 - (100 / (1 + mfr))

    def roc(close: pd.Series, length: int = 10, **kwargs) -> pd.Series:
        return 100 * close.pct_change(length)

    def cmo(close: pd.Series, length: int = 14, **kwargs) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(length).sum()
        loss = (-delta.clip(upper=0)).rolling(length).sum()
        return 100 * (gain - loss) / (gain + loss).replace(0, np.nan)

    def tsi(
        close: pd.Series,
        fast: int = 13,
        slow: int = 25,
        **kwargs,
    ) -> pd.Series:
        delta = close.diff()
        double_smooth = delta.ewm(span=slow, adjust=False).mean().ewm(span=fast, adjust=False).mean()
        double_smooth_abs = delta.abs().ewm(span=slow, adjust=False).mean().ewm(span=fast, adjust=False).mean()
        return 100 * double_smooth / double_smooth_abs.replace(0, np.nan)

    def ppo(
        close: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        **kwargs,
    ) -> pd.DataFrame:
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        ppo_line = 100 * (ema_fast - ema_slow) / ema_slow.replace(0, np.nan)
        sig = ppo_line.ewm(span=signal, adjust=False).mean()
        hist = ppo_line - sig
        return pd.DataFrame({
            f"PPO_{fast}_{slow}_{signal}": ppo_line,
            f"PPOs_{fast}_{slow}_{signal}": sig,
            f"PPOh_{fast}_{slow}_{signal}": hist,
        })

    # ── Volatility ────────────────────────────────────────────────────────────

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

    def natr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        length: int = 14,
        **kwargs,
    ) -> pd.Series:
        return 100 * atr(high, low, close, length) / close.replace(0, np.nan)

    def kc(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        length: int = 20,
        scalar: float = 2.0,
        **kwargs,
    ) -> pd.DataFrame:
        mid = ema(close, length)
        _atr = atr(high, low, close, length)
        return pd.DataFrame({
            f"KCUe_{length}_{scalar}": mid + scalar * _atr,
            f"KCMe_{length}_{scalar}": mid,
            f"KCLe_{length}_{scalar}": mid - scalar * _atr,
        })

    def donchian(
        high: pd.Series,
        low: pd.Series,
        length: int = 20,
        **kwargs,
    ) -> pd.DataFrame:
        upper = high.rolling(length).max()
        lower = low.rolling(length).min()
        mid = (upper + lower) / 2
        return pd.DataFrame({
            f"DCU_{length}": upper,
            f"DCM_{length}": mid,
            f"DCL_{length}": lower,
        })

    # ── Volume ────────────────────────────────────────────────────────────────

    def obv(close: pd.Series, volume: pd.Series, **kwargs) -> pd.Series:
        direction = np.sign(close.diff()).fillna(0)
        return (direction * volume).cumsum()

    def cmf(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        volume: pd.Series,
        length: int = 20,
        **kwargs,
    ) -> pd.Series:
        clv = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
        mfv = clv * volume
        return mfv.rolling(length).sum() / volume.rolling(length).sum().replace(0, np.nan)

    def vpt(close: pd.Series, volume: pd.Series, **kwargs) -> pd.Series:
        return (volume * close.pct_change()).cumsum()

    def ad(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        volume: pd.Series,
        **kwargs,
    ) -> pd.Series:
        clv = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
        return (clv * volume).cumsum()

    # ── Trend strength ────────────────────────────────────────────────────────

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

    def aroon(
        high: pd.Series,
        low: pd.Series,
        length: int = 14,
        **kwargs,
    ) -> pd.DataFrame:
        aroon_up = 100 * high.rolling(length + 1).apply(
            lambda x: (length - x[::-1].argmax()) / length, raw=True
        )
        aroon_down = 100 * low.rolling(length + 1).apply(
            lambda x: (length - x[::-1].argmin()) / length, raw=True
        )
        return pd.DataFrame({
            f"AROONU_{length}": aroon_up,
            f"AROOND_{length}": aroon_down,
            f"AROONOSC_{length}": aroon_up - aroon_down,
        })

    def ichimoku(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        tenkan: int = 9,
        kijun: int = 26,
        senkou: int = 52,
        **kwargs,
    ) -> pd.DataFrame:
        tenkan_sen = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
        kijun_sen = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2
        senkou_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
        senkou_b = ((high.rolling(senkou).max() + low.rolling(senkou).min()) / 2).shift(kijun)
        chikou = close.shift(-kijun)
        return pd.DataFrame({
            f"ITS_{tenkan}": tenkan_sen,
            f"IKS_{kijun}": kijun_sen,
            f"ISA_{tenkan}": senkou_a,
            f"ISB_{kijun}": senkou_b,
            f"ICS_{kijun}": chikou,
        })
