"""
Feature Store  (Layer 3 – Module 22)
======================================
Stores reusable engineered features for model training and live inference.
Provides versioned feature sets with point-in-time correctness.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from loguru import logger


@dataclass
class FeatureVector:
    symbol: str
    timestamp: float
    features: Dict[str, float]
    version: str = "v1"
    source: str = "unknown"


@dataclass
class FeatureDefinition:
    name: str
    description: str
    dtype: str = "float32"
    default: float = 0.0
    normalise: bool = True
    version: str = "v1"


class FeatureStore:
    """
    Centralised feature storage with:
    - In-memory latest features per symbol
    - Rolling window history (configurable depth)
    - Feature schema registry
    - Version tracking for model compatibility
    """

    def __init__(self, max_history: int = 10_000):
        self._max_history = max_history
        self._latest: Dict[str, FeatureVector] = {}
        self._history: Dict[str, List[FeatureVector]] = {}
        self._schema: Dict[str, FeatureDefinition] = {}
        self._lock = threading.RLock()

    # ── Schema ────────────────────────────────────────────────────────────────

    def register_feature(self, defn: FeatureDefinition) -> None:
        with self._lock:
            self._schema[defn.name] = defn

    def get_schema(self) -> Dict[str, FeatureDefinition]:
        with self._lock:
            return dict(self._schema)

    # ── Write ─────────────────────────────────────────────────────────────────

    def upsert(self, vector: FeatureVector) -> None:
        with self._lock:
            self._latest[vector.symbol] = vector
            hist = self._history.setdefault(vector.symbol, [])
            hist.append(vector)
            if len(hist) > self._max_history:
                self._history[vector.symbol] = hist[-self._max_history // 2:]

    def upsert_dict(self, symbol: str, features: Dict[str, float],
                    source: str = "unknown") -> FeatureVector:
        vec = FeatureVector(
            symbol=symbol,
            timestamp=time.time(),
            features=features,
            source=source,
        )
        self.upsert(vec)
        return vec

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_latest(self, symbol: str) -> Optional[FeatureVector]:
        with self._lock:
            return self._latest.get(symbol)

    def get_history(self, symbol: str, n: int = 100) -> List[FeatureVector]:
        with self._lock:
            hist = self._history.get(symbol, [])
            return hist[-n:]

    def get_feature_matrix(
        self, symbol: str, feature_names: List[str], n: int = 100
    ) -> Optional[np.ndarray]:
        """Return (n, len(feature_names)) numpy array for ML training."""
        history = self.get_history(symbol, n)
        if not history:
            return None
        rows = []
        for vec in history:
            row = [vec.features.get(fname, 0.0) for fname in feature_names]
            rows.append(row)
        return np.array(rows, dtype=np.float32)

    def get_all_symbols(self) -> List[str]:
        with self._lock:
            return list(self._latest.keys())

    def get_feature_names(self) -> List[str]:
        """Return all feature names seen across all symbols."""
        with self._lock:
            names: set = set()
            for vec in self._latest.values():
                names.update(vec.features.keys())
            return sorted(names)

    def snapshot(self, symbol: str) -> Dict[str, float]:
        """Return flat dict of latest feature values for a symbol."""
        vec = self.get_latest(symbol)
        return dict(vec.features) if vec else {}

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "symbols": len(self._latest),
                "total_vectors": sum(len(v) for v in self._history.values()),
                "schema_features": len(self._schema),
            }


# Singleton
_store: Optional[FeatureStore] = None


def get_feature_store() -> FeatureStore:
    global _store
    if _store is None:
        _store = FeatureStore()
    return _store
