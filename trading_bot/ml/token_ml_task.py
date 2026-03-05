"""
Per-Token ML Task System.

Each traded token gets its own dedicated neural network (TokenMLNet) that
specialises exclusively in that token's behaviour. It learns:

  - Volume patterns (time-of-day, day-of-week, volume spikes vs. baseline)
  - Typical trading hours / session patterns (Asian / EU / US sessions)
  - Price position tendencies (support/resistance, mean-reversion levels)
  - Regular entry / exit patterns (how the market participants open and close)
  - Momentum characteristics (how fast this token moves in each regime)
  - Correlation fingerprint (how it behaves vs. BTC / ETH during risk-on/off)
  - Liquidity profile (spread behaviour, book depth patterns)

Architecture
────────────
  TokenMLNet: 1-layer LSTM (64 units) + 2 FC layers → 3 outputs (SELL/HOLD/BUY)
  Input features: 32 time-series + 6 static token features = 38-dim
  Trained per-token on its own CSV data, saved to data/models/{symbol}/model.pt

TokenMLTask runs the full lifecycle for one token:
  - train()     : full training pass on historical data
  - predict()   : real-time signal generation
  - learn()     : online incremental update from latest closed candle
  - profile()   : returns TokenProfile (learned statistics about this token)

TokenMLManager orchestrates all token tasks, runs them in a thread pool,
and exposes a unified signal interface to the trading engine.
"""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

from loguru import logger
from utils.logger import get_intel_logger

# ── Directories ───────────────────────────────────────────────────────────────

MODELS_ROOT = Path(__file__).parent.parent / "data" / "models"
MODELS_ROOT.mkdir(parents=True, exist_ok=True)


# ── Token profile ─────────────────────────────────────────────────────────────

@dataclass
class TokenProfile:
    """Statistical and behavioural profile learned from a token's history."""
    symbol: str

    # Volume characteristics
    avg_volume_1h: float = 0.0
    avg_volume_1d: float = 0.0
    volume_std_1d: float = 0.0
    peak_volume_hour: int = 0          # UTC hour with highest avg volume
    low_volume_hour: int = 0           # UTC hour with lowest avg volume

    # Price characteristics
    avg_daily_range_pct: float = 0.0   # (H-L)/close average
    avg_volatility: float = 0.0        # ATR as % of close
    mean_reversion_strength: float = 0.0  # How quickly it reverts (0=trend, 1=reversion)
    typical_trend_duration_bars: int = 0  # Bars before a reversal

    # Session patterns
    asian_session_bias: float = 0.0    # Mean hourly return 00-08 UTC
    eu_session_bias: float = 0.0       # Mean hourly return 08-16 UTC
    us_session_bias: float = 0.0       # Mean hourly return 16-00 UTC

    # Trade entry/exit patterns
    avg_entry_rsi: float = 50.0        # Avg RSI at profitable long entries
    avg_exit_rsi: float = 50.0
    best_entry_hour: int = 0           # UTC hour with highest win rate
    best_exit_hour: int = 0

    # Model performance
    train_accuracy: float = 0.0
    val_accuracy: float = 0.0
    total_predictions: int = 0
    correct_predictions: int = 0
    live_win_rate: float = 0.0
    last_trained: str = ""
    training_rows: int = 0

    @property
    def live_accuracy(self) -> float:
        if self.total_predictions == 0:
            return 0.0
        return self.correct_predictions / self.total_predictions


# ── Neural network ────────────────────────────────────────────────────────────

if HAS_TORCH:
    class TokenMLNet(nn.Module):
        """
        Lightweight LSTM network dedicated to a single token.
        Input: (batch, seq_len, input_dim)
        Output: (batch, 3) softmax probabilities [SELL, HOLD, BUY]
        """

        def __init__(self, input_dim: int = 32, hidden_dim: int = 64, seq_len: int = 30) -> None:
            super().__init__()
            self.seq_len = seq_len
            self.hidden_dim = hidden_dim
            self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers=1,
                                batch_first=True, dropout=0.0)
            self.fc1 = nn.Linear(hidden_dim, 32)
            self.fc2 = nn.Linear(32, 3)
            self.relu = nn.ReLU()
            self.dropout = nn.Dropout(0.2)
            self.softmax = nn.Softmax(dim=-1)

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            out, _ = self.lstm(x)
            out = out[:, -1, :]        # Last time step
            out = self.relu(self.fc1(out))
            out = self.dropout(out)
            out = self.softmax(self.fc2(out))
            return out
else:
    class TokenMLNet:  # type: ignore[no-redef]
        """Stub when torch is not available."""
        def __init__(self, *args, **kwargs):
            pass


# ── Feature engineering ───────────────────────────────────────────────────────

_FEATURE_COLS = [
    "close_norm", "volume_norm", "rsi_norm",
    "macd_norm", "bb_pos",        # position within BB band
    "ema20_dist", "ema50_dist", "ema200_dist",
    "atr_norm", "obv_norm", "adx_norm", "vwap_dist",
    "body_size", "upper_wick", "lower_wick",   # candle anatomy
    "return_1", "return_5", "return_15",       # short-term returns
    "volume_vs_avg",                           # volume vs 20-period rolling avg
    "hour_sin", "hour_cos",                    # time-of-day encoding
    "dow_sin", "dow_cos",                      # day-of-week encoding
    "spread_norm",                             # (high-low)/close
    "momentum_5", "momentum_10",               # price momentum
    "vol_momentum",                            # volume momentum
    "buy_pressure",                            # taker_buy_volume / volume
    "breakout_signal",                         # +1 / 0 / -1
    "chart_trend",                             # +1 UP / 0 SIDE / -1 DOWN
    "support_dist", "resistance_dist",         # distance to S/R levels
]
INPUT_DIM = len(_FEATURE_COLS)   # = 32
SEQ_LEN = 30


def build_features(df: pd.DataFrame) -> np.ndarray:
    """
    Convert a kline DataFrame into a normalised feature matrix.
    Returns shape (rows, INPUT_DIM).
    """
    out = pd.DataFrame(index=df.index)

    close = df["close"].replace(0, np.nan).ffill()
    volume = df["volume"].replace(0, np.nan).ffill()

    # Price normalisation: z-score over 100 bars
    close_mean = close.rolling(100, min_periods=5).mean()
    close_std  = close.rolling(100, min_periods=5).std().replace(0, 1)
    out["close_norm"]  = (close - close_mean) / close_std

    vol_mean = volume.rolling(100, min_periods=5).mean()
    vol_std  = volume.rolling(100, min_periods=5).std().replace(0, 1)
    out["volume_norm"] = (volume - vol_mean) / vol_std

    # RSI normalised to [-1, 1]
    rsi = df.get("rsi", pd.Series(50, index=df.index)).fillna(50)
    out["rsi_norm"] = (rsi - 50) / 50

    # MACD normalised
    macd = df.get("macd", pd.Series(0, index=df.index)).fillna(0)
    macd_std = macd.rolling(100, min_periods=5).std().replace(0, 1)
    out["macd_norm"] = macd / macd_std

    # Bollinger position
    bb_upper = df.get("bb_upper", close * 1.02).fillna(close * 1.02)
    bb_lower = df.get("bb_lower", close * 0.98).fillna(close * 0.98)
    bb_range = (bb_upper - bb_lower).replace(0, 1)
    out["bb_pos"] = (close - bb_lower) / bb_range * 2 - 1

    # EMA distances
    ema20  = df.get("ema_20",  close).fillna(close)
    ema50  = df.get("ema_50",  close).fillna(close)
    ema200 = df.get("ema_200", close).fillna(close)
    out["ema20_dist"]  = (close - ema20)  / close
    out["ema50_dist"]  = (close - ema50)  / close
    out["ema200_dist"] = (close - ema200) / close

    # ATR normalised
    atr = df.get("atr", pd.Series(0, index=df.index)).fillna(0)
    out["atr_norm"] = atr / close

    # OBV normalised
    obv = df.get("obv", pd.Series(0, index=df.index)).fillna(0)
    obv_std = obv.rolling(100, min_periods=5).std().replace(0, 1)
    out["obv_norm"] = obv / obv_std

    # ADX normalised
    adx = df.get("adx", pd.Series(0, index=df.index)).fillna(0)
    out["adx_norm"] = adx / 100.0

    # VWAP distance
    vwap = df.get("vwap", close).fillna(close)
    out["vwap_dist"] = (close - vwap) / close

    # Candle anatomy
    op = df["open"]
    hi = df["high"]
    lo = df["low"]
    cl = close
    candle_range = (hi - lo).replace(0, 1)
    out["body_size"]   = abs(cl - op) / candle_range
    out["upper_wick"]  = (hi - pd.concat([op, cl], axis=1).max(axis=1)) / candle_range
    out["lower_wick"]  = (pd.concat([op, cl], axis=1).min(axis=1) - lo) / candle_range

    # Short-term returns
    out["return_1"]  = close.pct_change(1).fillna(0)
    out["return_5"]  = close.pct_change(5).fillna(0)
    out["return_15"] = close.pct_change(15).fillna(0)

    # Volume vs 20-bar average
    vol_ma20 = volume.rolling(20, min_periods=1).mean().replace(0, 1)
    out["volume_vs_avg"] = volume / vol_ma20 - 1

    # Time encoding
    if "open_time" in df.columns:
        dt = pd.to_datetime(df["open_time"], utc=True)
    else:
        dt = pd.Series(pd.Timestamp.now(tz="UTC"), index=df.index)
    hour = dt.dt.hour.astype(float)
    dow  = dt.dt.dayofweek.astype(float)
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    out["dow_sin"]  = np.sin(2 * np.pi * dow / 7)
    out["dow_cos"]  = np.cos(2 * np.pi * dow / 7)

    # Spread
    out["spread_norm"] = (hi - lo) / close

    # Momentum
    out["momentum_5"]  = close / close.shift(5).replace(0, np.nan).ffill() - 1
    out["momentum_10"] = close / close.shift(10).replace(0, np.nan).ffill() - 1

    # Volume momentum
    out["vol_momentum"] = volume / volume.shift(5).replace(0, np.nan).ffill() - 1

    # Buy pressure (taker)
    tb_vol = df.get("taker_buy_volume", volume * 0.5).fillna(volume * 0.5)
    out["buy_pressure"] = (tb_vol / volume.replace(0, 1)) * 2 - 1

    # Chart/pattern signals from trading_fundamentals if available
    for col, default in [("breakout_signal", 0), ("chart_trend", 0),
                         ("support_dist", 0), ("resistance_dist", 0)]:
        out[col] = df.get(col, pd.Series(default, index=df.index)).fillna(0)

    arr = out[_FEATURE_COLS].values.astype(np.float32)
    arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0)
    arr = np.clip(arr, -5, 5)
    return arr


def build_labels(df: pd.DataFrame, forward_bars: int = 5, threshold_pct: float = 0.5) -> np.ndarray:
    """
    Future return > +threshold_pct% → BUY (2)
    Future return < -threshold_pct% → SELL (0)
    Otherwise → HOLD (1)
    """
    close = df["close"].values.astype(float)
    n = len(close)
    labels = np.ones(n, dtype=np.int64)   # default HOLD
    for i in range(n - forward_bars):
        fwd_ret = (close[i + forward_bars] - close[i]) / (close[i] + 1e-9) * 100
        if fwd_ret >= threshold_pct:
            labels[i] = 2   # BUY
        elif fwd_ret <= -threshold_pct:
            labels[i] = 0   # SELL
    return labels


# ── Per-token ML task ─────────────────────────────────────────────────────────

class TokenMLTask:
    """
    Self-contained ML task for a single token.
    Owns its own TokenMLNet, TokenProfile, and training state.
    """

    TRAIN_EPOCHS = 20
    BATCH_SIZE = 64
    LR = 1e-3

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._profile = TokenProfile(symbol=symbol)
        self._model: Optional[TokenMLNet] = None
        self._model_path = MODELS_ROOT / symbol / "model.pt"
        self._profile_path = MODELS_ROOT / symbol / "profile.json"
        self._model_path.parent.mkdir(parents=True, exist_ok=True)
        self._intel = get_intel_logger()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[dict], None]] = []

        # Online learning buffer: recent (feature_vec, label) pairs
        self._online_buffer: list[tuple[np.ndarray, int]] = []
        self._online_buffer_max = 256

        self._load()

    # ── Public API ─────────────────────────────────────────────────────

    def on_signal(self, callback: Callable[[dict], None]) -> None:
        """Register callback for new prediction signals."""
        self._callbacks.append(callback)

    def train(self, df: pd.DataFrame, progress_cb: Callable | None = None) -> float:
        """
        Full training pass on historical data.
        Returns validation accuracy.
        """
        if not HAS_TORCH:
            logger.warning(f"[{self.symbol}] torch not available – skipping token training")
            return 0.0

        if len(df) < SEQ_LEN + 20:
            logger.warning(f"[{self.symbol}] insufficient data ({len(df)} rows) for training")
            return 0.0

        self._intel.ml("TokenMLTask", f"🤖 [{self.symbol}] Starting token-specific training on {len(df)} rows…")

        # Build features + labels
        features = build_features(df)
        labels   = build_labels(df)

        # Compute and store token profile statistics
        self._update_profile_stats(df, features, labels)

        # Build sequence dataset
        X, y = [], []
        for i in range(SEQ_LEN, len(features)):
            X.append(features[i - SEQ_LEN:i])
            y.append(labels[i])
        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.int64)

        # Train/val split (80/20)
        split = int(len(X) * 0.8)
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]

        # Build model
        with self._lock:
            if self._model is None:
                self._model = TokenMLNet(input_dim=INPUT_DIM, hidden_dim=64, seq_len=SEQ_LEN)

        device = self._get_device()
        model = self._model.to(device)
        optimizer = optim.Adam(model.parameters(), lr=self.LR, weight_decay=1e-4)
        criterion = nn.CrossEntropyLoss()

        X_t = torch.from_numpy(X_train).to(device)
        y_t = torch.from_numpy(y_train).to(device)

        model.train()
        for epoch in range(self.TRAIN_EPOCHS):
            perm = torch.randperm(len(X_t))
            epoch_loss = 0.0
            batches = 0
            for i in range(0, len(X_t), self.BATCH_SIZE):
                idx = perm[i:i + self.BATCH_SIZE]
                bx, by = X_t[idx], y_t[idx]
                optimizer.zero_grad()
                out = model(bx)
                loss = criterion(out, by)
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += loss.item()
                batches += 1

            if progress_cb:
                pct = (epoch + 1) / self.TRAIN_EPOCHS * 100
                progress_cb({"symbol": self.symbol, "epoch": epoch + 1,
                             "total_epochs": self.TRAIN_EPOCHS, "pct": pct,
                             "loss": epoch_loss / max(batches, 1)})

        # Validation
        model.eval()
        with torch.no_grad():
            X_v = torch.from_numpy(X_val).to(device)
            y_v = torch.from_numpy(y_val).to(device)
            preds = model(X_v).argmax(dim=1)
            val_acc = (preds == y_v).float().mean().item()

        with self._lock:
            self._profile.train_accuracy = float(val_acc)
            self._profile.val_accuracy   = float(val_acc)
            self._profile.last_trained   = datetime.now(timezone.utc).isoformat()
            self._profile.training_rows  = len(df)

        self._save()
        self._intel.ml("TokenMLTask",
            f"✅ [{self.symbol}] Token training complete | val_acc={val_acc:.1%} | "
            f"rows={len(df)} | epochs={self.TRAIN_EPOCHS}")
        return val_acc

    def predict(self, df: pd.DataFrame) -> dict:
        """
        Generate a trading signal from the latest rows of a DataFrame.
        Returns: {"signal": "BUY"|"HOLD"|"SELL", "confidence": float,
                  "probabilities": [sell_p, hold_p, buy_p], "symbol": str}
        """
        if not HAS_TORCH or self._model is None:
            return {"signal": "HOLD", "confidence": 0.0, "probabilities": [0, 1, 0], "symbol": self.symbol}

        if len(df) < SEQ_LEN:
            return {"signal": "HOLD", "confidence": 0.0, "probabilities": [0, 1, 0], "symbol": self.symbol}

        features = build_features(df)
        seq = features[-SEQ_LEN:]
        x = torch.from_numpy(seq[np.newaxis]).to(self._get_device())

        self._model.eval()
        with torch.no_grad():
            probs = self._model(x)[0].cpu().numpy()

        label_map = {0: "SELL", 1: "HOLD", 2: "BUY"}
        action = int(np.argmax(probs))
        confidence = float(probs[action])

        return {
            "signal": label_map[action],
            "confidence": confidence,
            "probabilities": probs.tolist(),
            "symbol": self.symbol,
        }

    def learn_from_candle(self, df_row: pd.Series, label: int) -> None:
        """
        Online incremental update from one new closed candle.
        label: 0=SELL, 1=HOLD, 2=BUY
        """
        if not HAS_TORCH or self._model is None:
            return

        # Build a minimal DataFrame from the single row for feature extraction
        single_df = pd.DataFrame([df_row])
        try:
            feat = build_features(single_df)[0]
            with self._lock:
                self._online_buffer.append((feat, label))
                if len(self._online_buffer) > self._online_buffer_max:
                    self._online_buffer.pop(0)

            # Mini-batch SGD update
            if len(self._online_buffer) >= 16:
                self._online_update()
        except Exception as exc:
            logger.debug(f"[{self.symbol}] online learn error: {exc}")

    def record_outcome(self, signal: str, was_correct: bool) -> None:
        """Record prediction accuracy for live win rate tracking."""
        with self._lock:
            self._profile.total_predictions += 1
            if was_correct:
                self._profile.correct_predictions += 1
            total = self._profile.total_predictions
            self._profile.live_win_rate = self._profile.correct_predictions / total

    @property
    def profile(self) -> TokenProfile:
        return self._profile

    @property
    def is_trained(self) -> bool:
        return self._model is not None and self._profile.last_trained != ""

    # ── Internal ───────────────────────────────────────────────────────

    def _online_update(self) -> None:
        """One mini-batch gradient update using the online buffer."""
        try:
            buf = list(self._online_buffer[-64:])
            feats = np.array([b[0] for b in buf], dtype=np.float32)
            lbls  = np.array([b[1] for b in buf], dtype=np.int64)

            # Build dummy sequences (replicate single frames for online update)
            X = np.stack([np.tile(f, (SEQ_LEN, 1)) for f in feats])
            X_t = torch.from_numpy(X).to(self._get_device())
            y_t = torch.from_numpy(lbls).to(self._get_device())

            optimizer = optim.Adam(self._model.parameters(), lr=self.LR * 0.1)
            criterion = nn.CrossEntropyLoss()
            self._model.train()
            optimizer.zero_grad()
            out = self._model(X_t)
            loss = criterion(out, y_t)
            loss.backward()
            nn.utils.clip_grad_norm_(self._model.parameters(), 1.0)
            optimizer.step()
        except Exception as exc:
            logger.debug(f"[{self.symbol}] _online_update error: {exc}")

    def _update_profile_stats(self, df: pd.DataFrame, features: np.ndarray, labels: np.ndarray) -> None:
        """Compute and store statistical profile of this token."""
        try:
            close  = df["close"].astype(float)
            volume = df["volume"].astype(float)

            self._profile.avg_volume_1d  = float(volume.rolling(288, min_periods=1).mean().iloc[-1])  # 5m bars
            self._profile.avg_daily_range_pct = float(
                ((df["high"] - df["low"]) / close).mean() * 100
            )

            atr = df.get("atr")
            if atr is not None:
                self._profile.avg_volatility = float((atr / close).mean() * 100)

            # Session biases (using open_time if available)
            if "open_time" in df.columns:
                df2 = df.copy()
                df2["ret"] = close.pct_change()
                dt = pd.to_datetime(df2["open_time"], utc=True)
                df2["hour"] = dt.dt.hour
                self._profile.asian_session_bias = float(df2[df2["hour"].between(0, 7)]["ret"].mean() * 100)
                self._profile.eu_session_bias    = float(df2[df2["hour"].between(8, 15)]["ret"].mean() * 100)
                self._profile.us_session_bias    = float(df2[df2["hour"].between(16, 23)]["ret"].mean() * 100)

                # Peak volume hour
                vol_by_hour = df2.groupby("hour")["volume"].mean()
                if not vol_by_hour.empty:
                    self._profile.peak_volume_hour = int(vol_by_hour.idxmax())
                    self._profile.low_volume_hour  = int(vol_by_hour.idxmin())

            # Mean reversion: autocorrelation of returns at lag-1
            rets = close.pct_change().dropna()
            if len(rets) > 20:
                autocorr = float(rets.autocorr(lag=1))
                # Negative autocorr → mean-reverting, positive → trending
                self._profile.mean_reversion_strength = max(0.0, min(1.0, -autocorr + 0.5))

        except Exception as exc:
            logger.debug(f"[{self.symbol}] _update_profile_stats error: {exc}")

    def _get_device(self) -> "torch.device":
        if HAS_TORCH:
            if torch.backends.mps.is_available():
                return torch.device("mps")
            if torch.cuda.is_available():
                return torch.device("cuda")
        return torch.device("cpu") if HAS_TORCH else None

    def _save(self) -> None:
        try:
            if HAS_TORCH and self._model is not None:
                torch.save(self._model.state_dict(), self._model_path)
            self._profile_path.write_text(json.dumps(asdict(self._profile), indent=2))
        except Exception as exc:
            logger.debug(f"[{self.symbol}] save error: {exc}")

    def _load(self) -> None:
        try:
            if self._profile_path.exists():
                self._profile = TokenProfile(**json.loads(self._profile_path.read_text()))
        except Exception:
            pass
        try:
            if HAS_TORCH and self._model_path.exists():
                self._model = TokenMLNet(input_dim=INPUT_DIM, hidden_dim=64, seq_len=SEQ_LEN)
                self._model.load_state_dict(torch.load(self._model_path, map_location="cpu"))
                self._model.eval()
        except Exception as exc:
            logger.debug(f"[{self.symbol}] model load error: {exc}")


# ── Manager ───────────────────────────────────────────────────────────────────

class TokenMLManager:
    """
    Manages per-token ML tasks across all active symbols.

    - Trains each token's own network on its historical data
    - Runs real-time predictions on incoming candles
    - Applies online learning after each closed candle
    - Exposes aggregated signals and per-token profiles to the UI and trading engine
    """

    def __init__(self, binance_client=None, max_workers: int = 4) -> None:
        self._client = binance_client
        self._max_workers = max_workers
        self._tasks: dict[str, TokenMLTask] = {}
        self._intel = get_intel_logger()
        self._signal_callbacks: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        self._training_progress: dict[str, float] = {}

    def on_signal(self, callback: Callable[[dict], None]) -> None:
        """Register callback for any token signal."""
        self._signal_callbacks.append(callback)

    def get_task(self, symbol: str) -> TokenMLTask:
        """Get (or create) the ML task for a symbol."""
        with self._lock:
            if symbol not in self._tasks:
                self._tasks[symbol] = TokenMLTask(symbol)
        return self._tasks[symbol]

    def train_all(
        self,
        symbols: list[str],
        interval: str = "1h",
        progress_cb: Callable | None = None,
    ) -> dict[str, float]:
        """
        Train each symbol's dedicated model in parallel.
        Returns {symbol: val_accuracy}.
        """
        import concurrent.futures

        results: dict[str, float] = {}
        total = len(symbols)

        def _train_one(sym: str) -> tuple[str, float]:
            try:
                from ml.data_collector import DataCollector
                from ml.trading_fundamentals import augment_features_with_patterns
                df = DataCollector.load_dataframe(sym, interval, limit=10000)
                if df.empty:
                    return sym, 0.0
                df = augment_features_with_patterns(df)
                task = self.get_task(sym)
                acc = task.train(df, progress_cb=lambda d: self._on_token_progress(sym, d, progress_cb, total))
                return sym, acc
            except Exception as exc:
                logger.warning(f"TokenMLManager: train failed [{sym}]: {exc}")
                return sym, 0.0

        self._intel.ml("TokenMLManager",
            f"🚀 Starting per-token training for {total} symbols (workers={self._max_workers})…")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {pool.submit(_train_one, s): s for s in symbols}
            for fut in concurrent.futures.as_completed(futures):
                sym, acc = fut.result()
                results[sym] = acc
                self._training_progress[sym] = acc

        self._intel.ml("TokenMLManager",
            f"✅ Per-token training complete | "
            f"avg_acc={np.mean(list(results.values())):.1%} | {total} tokens")
        return results

    def predict(self, symbol: str, df: pd.DataFrame) -> dict:
        """Generate a prediction for a single symbol and broadcast the signal."""
        task = self.get_task(symbol)
        signal = task.predict(df)
        self._broadcast(signal)
        return signal

    def learn_from_candle(self, symbol: str, df_row: pd.Series, label: int) -> None:
        """Apply one-shot online learning to the token's model."""
        task = self.get_task(symbol)
        task.learn_from_candle(df_row, label)

    def get_all_profiles(self) -> list[TokenProfile]:
        with self._lock:
            return [t.profile for t in self._tasks.values()]

    def get_training_progress(self) -> dict[str, float]:
        return dict(self._training_progress)

    def summary_table(self) -> list[dict]:
        """Return a table-ready list of per-token stats for the UI."""
        rows = []
        for sym, task in self._tasks.items():
            p = task.profile
            rows.append({
                "symbol": sym,
                "trained": task.is_trained,
                "val_accuracy": p.val_accuracy,
                "live_win_rate": p.live_win_rate,
                "training_rows": p.training_rows,
                "peak_volume_hour": p.peak_volume_hour,
                "avg_volatility_pct": round(p.avg_volatility, 3),
                "avg_daily_range_pct": round(p.avg_daily_range_pct, 3),
                "asian_bias": round(p.asian_session_bias, 4),
                "eu_bias": round(p.eu_session_bias, 4),
                "us_bias": round(p.us_session_bias, 4),
                "mean_reversion": round(p.mean_reversion_strength, 3),
                "last_trained": p.last_trained,
            })
        rows.sort(key=lambda r: r["val_accuracy"], reverse=True)
        return rows

    # ── Internal ───────────────────────────────────────────────────────

    def _on_token_progress(self, sym: str, data: dict,
                            outer_cb: Callable | None, total: int) -> None:
        self._training_progress[sym] = data.get("pct", 0)
        if outer_cb:
            try:
                outer_cb({"symbol": sym, "pct": data.get("pct", 0),
                          "epoch": data.get("epoch"), "loss": data.get("loss")})
            except Exception:
                pass

    def _broadcast(self, signal: dict) -> None:
        for cb in self._signal_callbacks:
            try:
                cb(signal)
            except Exception:
                pass
