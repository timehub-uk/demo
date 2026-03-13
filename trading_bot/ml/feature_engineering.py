"""
Feature engineering for ML models.
Produces normalised tensors ready for LSTM / Transformer training.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
import torch
from typing import Tuple


FEATURE_COLUMNS = [
    "open","high","low","close","volume",
    "rsi","macd","macd_signal","bb_upper","bb_lower",
    "ema_20","ema_50","ema_200","atr","obv","adx",
    # Derived
    "pct_change","hl_range","bb_width","macd_hist",
    "vol_sma_ratio","price_ema20_ratio","price_ema50_ratio",
    "rsi_norm","adx_norm",
    # Timeframe encoding (normalised 0-1: 1m=0.0 … 1w=1.0)
    "timeframe_id",
]

# Optional on-chain DEX features — appended when CoinGecko/Codex are active.
# The model automatically expands to include them if present; they are filled
# with 0 when the APIs are unavailable so training is never blocked.
DEX_FEATURE_COLUMNS = [
    "dex_volume_24h_usd_norm",   # log-normalised DEX 24h volume
    "dex_liquidity_usd_norm",    # log-normalised pool liquidity
    "dex_vol_liq_ratio",         # volume / liquidity pressure ratio
    "dex_pool_count_top5",       # number of active top-5 pools (0-5 normalised)
]

# Mapping from interval string to normalised 0-1 timeframe id
TIMEFRAME_IDS: dict[str, float] = {
    "1m": 0.0, "3m": 0.10, "5m": 0.20, "15m": 0.30, "30m": 0.40,
    "1h": 0.55, "2h": 0.65, "4h": 0.75, "1d": 0.90, "1w": 1.0,
}


class FeatureEngineer:
    """
    Transforms raw OHLCV + indicator DataFrames into
    normalised (X, y) tensors for training and inference.
    """

    def __init__(self, lookback: int = 60, horizon: int = 5) -> None:
        self.lookback = lookback
        self.horizon = horizon
        self.scaler = RobustScaler()
        self._fitted = False

    # ── Feature creation ───────────────────────────────────────────────
    @staticmethod
    def add_derived_features(df: pd.DataFrame, interval: str = "") -> pd.DataFrame:
        df = df.copy()
        df["pct_change"] = df["close"].pct_change()
        df["hl_range"] = (df["high"] - df["low"]) / df["close"]
        df["bb_width"] = (
            (df["bb_upper"] - df["bb_lower"]) / df["close"]
            if "bb_upper" in df.columns else np.nan
        )
        df["macd_hist"] = (
            df["macd"] - df["macd_signal"]
            if "macd" in df.columns else np.nan
        )
        if "volume" in df.columns:
            df["vol_sma_ratio"] = df["volume"] / df["volume"].rolling(20).mean()
        if "ema_20" in df.columns:
            df["price_ema20_ratio"] = df["close"] / df["ema_20"]
        if "ema_50" in df.columns:
            df["price_ema50_ratio"] = df["close"] / df["ema_50"]
        if "rsi" in df.columns:
            df["rsi_norm"] = df["rsi"] / 100.0
        if "adx" in df.columns:
            df["adx_norm"] = df["adx"] / 100.0
        # Timeframe identity – constant column so the model knows which TF it's on
        tf_id = TIMEFRAME_IDS.get(interval, 0.55)   # default to 1h if unknown
        df["timeframe_id"] = tf_id
        return df

    @staticmethod
    def inject_dex_features(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Fetch on-chain DEX features from CoinGecko/Codex and inject them as
        constant columns over the whole DataFrame.  Safe to call even when
        the APIs are disabled — columns are filled with 0 in that case.
        """
        import math
        try:
            from core.dex_data_provider import get_dex_provider
            provider = get_dex_provider()
            raw = provider.get_dex_features_for_symbol(symbol)
        except Exception:
            raw = {}

        vol  = float(raw.get("dex_volume_24h_usd", 0))
        liq  = float(raw.get("dex_liquidity_usd", 0))
        ratio = float(raw.get("dex_vol_liq_ratio", 0))
        pools = float(raw.get("dex_pool_count_top5", 0))

        df["dex_volume_24h_usd_norm"] = math.log1p(vol) / 25.0   # normalise ~0-1
        df["dex_liquidity_usd_norm"]  = math.log1p(liq) / 25.0
        df["dex_vol_liq_ratio"]       = min(ratio, 10.0) / 10.0
        df["dex_pool_count_top5"]     = pools / 5.0
        return df

    # ── Label generation ───────────────────────────────────────────────
    @staticmethod
    def generate_labels(df: pd.DataFrame, horizon: int = 5, threshold: float = 0.005) -> pd.Series:
        """
        Multi-class label:
          2 = strong buy  (future return > threshold)
          1 = hold
          0 = sell        (future return < -threshold)
        """
        future_return = df["close"].shift(-horizon) / df["close"] - 1
        labels = pd.Series(1, index=df.index)   # default hold
        labels[future_return > threshold] = 2
        labels[future_return < -threshold] = 0
        return labels

    # ── Build tensors ──────────────────────────────────────────────────
    def build_sequences(
        self,
        df: pd.DataFrame,
        fit_scaler: bool = True,
        interval: str = "",
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Return (X, y) tensors with shape:
          X: (N, lookback, features)
          y: (N,) int64 class labels
        """
        df = self.add_derived_features(df, interval=interval)
        labels = self.generate_labels(df, self.horizon)

        available = [c for c in FEATURE_COLUMNS if c in df.columns]
        data = df[available].ffill().bfill().values

        if fit_scaler or not self._fitted:
            data = self.scaler.fit_transform(data)
            self._fitted = True
        else:
            data = self.scaler.transform(data)

        label_arr = labels.values
        X, y = [], []
        for i in range(self.lookback, len(data) - self.horizon):
            X.append(data[i - self.lookback: i])
            y.append(label_arr[i])

        if not X:
            return torch.empty(0), torch.empty(0)

        X_t = torch.tensor(np.array(X), dtype=torch.float32)
        y_t = torch.tensor(np.array(y), dtype=torch.long)
        return X_t, y_t

    def transform_live(self, df: pd.DataFrame, interval: str = "") -> torch.Tensor:
        """Transform the latest lookback window for inference."""
        df = self.add_derived_features(df, interval=interval)
        available = [c for c in FEATURE_COLUMNS if c in df.columns]
        data = df[available].tail(self.lookback).ffill().bfill().values
        if len(data) < self.lookback:
            pad = np.zeros((self.lookback - len(data), data.shape[1]))
            data = np.vstack([pad, data])
        data = self.scaler.transform(data) if self._fitted else data
        return torch.tensor(data[np.newaxis], dtype=torch.float32)

    @property
    def n_features(self) -> int:
        """Number of features after calling build_sequences at least once."""
        return self.scaler.n_features_in_ if self._fitted else len(FEATURE_COLUMNS)
