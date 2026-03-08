"""
Real-time ML predictor.
Loads the active model and generates BUY/SELL/HOLD signals
with confidence scores for each subscribed symbol.
"""

from __future__ import annotations

import time
import threading
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

import torch
import numpy as np
from loguru import logger

from sqlalchemy import select

from config import get_settings
from db.postgres import get_db
from db.models import MLModel
from db.redis_client import RedisClient
from .models import LSTMModel, get_device
from .data_collector import DataCollector
from .feature_engineering import FeatureEngineer

ACTION_MAP = {0: "SELL", 1: "HOLD", 2: "BUY"}


class MLPredictor:
    """
    Live inference engine. Runs in a background thread,
    emitting signals for each symbol on every candle close.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._redis = RedisClient()
        self._device = get_device()
        self._model: Optional[LSTMModel] = None
        self._fe = FeatureEngineer(
            lookback=self._settings.ml.lookback_window,
            horizon=self._settings.ml.prediction_horizon,
        )
        self._signal_callbacks: list[Callable] = []
        self._symbols: set[str] = set()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._load_active_model()

    # ── Setup ──────────────────────────────────────────────────────────
    def on_signal(self, callback: Callable) -> None:
        self._signal_callbacks.append(callback)

    def add_symbol(self, symbol: str) -> None:
        with self._lock:
            self._symbols.add(symbol)

    def remove_symbol(self, symbol: str) -> None:
        with self._lock:
            self._symbols.discard(symbol)

    def reload_model(self) -> bool:
        return self._load_active_model()

    # ── Lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._inference_loop, daemon=True, name="ml-predictor"
        )
        self._thread.start()
        logger.info(f"MLPredictor started on {self._device}")

    def stop(self) -> None:
        self._running = False

    # ── Inference loop ─────────────────────────────────────────────────
    def _inference_loop(self) -> None:
        interval_sec = 60   # Run inference every minute
        while self._running:
            with self._lock:
                symbols = list(self._symbols)
            for sym in symbols:
                if not self._running:
                    break
                try:
                    signal = self.predict(sym)
                    if signal:
                        self._redis.cache_ml_signal(sym, signal)
                        self._redis.publish_signal(sym, signal)
                        self._emit(signal)
                except Exception as exc:
                    logger.debug(f"Prediction error [{sym}]: {exc}")
            time.sleep(interval_sec)

    # ── Single prediction ──────────────────────────────────────────────
    def predict(self, symbol: str, interval: str = "1h") -> Optional[dict]:
        if self._model is None:
            return self._heuristic_signal(symbol)

        df = DataCollector.load_dataframe(symbol, interval, limit=200)
        if len(df) < self._settings.ml.lookback_window + 10:
            return self._heuristic_signal(symbol)

        x = self._fe.transform_live(df)
        if len(x) == 0:
            return None

        self._model.eval()
        with torch.no_grad():
            x = x.to(self._device)
            logits = self._model(x)
            probs = torch.softmax(logits, dim=-1).squeeze()
            pred_class = int(probs.argmax().item())
            confidence = float(probs[pred_class].item())

        action = ACTION_MAP[pred_class]
        current_price = float(df["close"].iloc[-1])

        signal = {
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "price": current_price,
            "probs": {
                "SELL": float(probs[0].item()),
                "HOLD": float(probs[1].item()),
                "BUY":  float(probs[2].item()),
            },
            "timestamp": time.time(),
        }
        return signal if confidence >= self._settings.ml.confidence_threshold else None

    def _heuristic_signal(self, symbol: str) -> Optional[dict]:
        """Simple RSI-based heuristic when no ML model is loaded."""
        df = DataCollector.load_dataframe(symbol, "1h", limit=30)
        if df.empty or "rsi" not in df.columns:
            return None
        rsi = df["rsi"].iloc[-1]
        if rsi is None or np.isnan(rsi):
            return None
        price = float(df["close"].iloc[-1])
        if rsi < 30:
            return {"symbol": symbol, "action": "BUY", "confidence": 0.65, "price": price, "timestamp": time.time()}
        if rsi > 70:
            return {"symbol": symbol, "action": "SELL", "confidence": 0.65, "price": price, "timestamp": time.time()}
        return {"symbol": symbol, "action": "HOLD", "confidence": 0.55, "price": price, "timestamp": time.time()}

    # ── Model loading ──────────────────────────────────────────────────
    def _load_active_model(self) -> bool:
        try:
            with get_db() as db:
                ml_model = db.execute(
                    select(MLModel).filter_by(is_active=True).order_by(MLModel.created_at.desc())
                ).scalar_one_or_none()
            if ml_model and ml_model.model_path:
                path = Path(ml_model.model_path)
                if path.exists():
                    from .feature_engineering import FEATURE_COLUMNS
                    ml_cfg = self._settings.ml
                    model = LSTMModel(
                        n_features=len(FEATURE_COLUMNS),
                        hidden_size=ml_cfg.lstm_hidden_size,
                        n_layers=ml_cfg.lstm_layers,
                    ).to(self._device)
                    model.load_state_dict(torch.load(path, map_location=self._device))
                    self._model = model
                    logger.info(f"ML model loaded: {ml_model.version}")
                    return True
        except Exception as exc:
            logger.warning(f"Could not load ML model: {exc}")
        return False

    # ── Event emission ─────────────────────────────────────────────────
    def _emit(self, signal: dict) -> None:
        for cb in self._signal_callbacks:
            try:
                cb(signal)
            except Exception:
                pass
