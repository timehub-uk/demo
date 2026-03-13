"""
Redis client for real-time market data caching, pub/sub and rate-limit throttling.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Optional

import redis
from loguru import logger

_lock = threading.Lock()
_client: redis.Redis | None = None
_pubsub_threads: list = []


def init_redis(
    host: str = "localhost",
    port: int = 6379,
    db: int = 0,
    password: str = "",
    max_connections: int = 50,
    ssl: bool = False,
) -> None:
    global _client
    with _lock:
        if _client is not None:
            return
        _client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password or None,
            max_connections=max_connections,
            ssl=ssl,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            retry_on_timeout=True,
        )
        _client.ping()
        logger.info(f"Redis connected at {host}:{port}/{db}")


def get_redis() -> redis.Redis:
    if _client is None:
        raise RuntimeError("Redis not initialised – call init_redis() first.")
    return _client


class RedisClient:
    """Application-level Redis wrapper with typed helpers."""

    KEY_PREFIX = "bml:"
    ORDERBOOK_TTL = 5          # seconds
    TICKER_TTL = 2
    CANDLE_TTL = 60
    PORTFOLIO_TTL = 30

    def __init__(self) -> None:
        self._r = get_redis()

    # ── Generic ─────────────────────────────────────────────────────────
    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        k = self.KEY_PREFIX + key
        v = json.dumps(value) if not isinstance(value, str) else value
        if ttl:
            self._r.setex(k, ttl, v)
        else:
            self._r.set(k, v)

    def get(self, key: str) -> Any | None:
        v = self._r.get(self.KEY_PREFIX + key)
        if v is None:
            return None
        try:
            return json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return v

    def delete(self, key: str) -> None:
        self._r.delete(self.KEY_PREFIX + key)

    # ── Market data helpers ──────────────────────────────────────────────
    def cache_ticker(self, symbol: str, data: dict) -> None:
        self.set(f"ticker:{symbol}", data, ttl=self.TICKER_TTL)

    def get_ticker(self, symbol: str) -> dict | None:
        return self.get(f"ticker:{symbol}")

    def cache_orderbook(self, symbol: str, data: dict) -> None:
        self.set(f"orderbook:{symbol}", data, ttl=self.ORDERBOOK_TTL)

    def get_orderbook(self, symbol: str) -> dict | None:
        return self.get(f"orderbook:{symbol}")

    def cache_candles(self, symbol: str, interval: str, data: list) -> None:
        self.set(f"candles:{symbol}:{interval}", data, ttl=self.CANDLE_TTL)

    def get_candles(self, symbol: str, interval: str) -> list | None:
        return self.get(f"candles:{symbol}:{interval}")

    # ── Portfolio ─────────────────────────────────────────────────────────
    def cache_portfolio(self, data: dict) -> None:
        self.set("portfolio:snapshot", data, ttl=self.PORTFOLIO_TTL)

    def get_portfolio(self) -> dict | None:
        return self.get("portfolio:snapshot")

    # ── ML Signals ─────────────────────────────────────────────────────────
    def publish_signal(self, symbol: str, signal: dict) -> None:
        self._r.publish(f"bml:signal:{symbol}", json.dumps(signal))

    def cache_ml_signal(self, symbol: str, signal: dict) -> None:
        self.set(f"ml_signal:{symbol}", signal, ttl=120)

    def get_ml_signal(self, symbol: str) -> dict | None:
        return self.get(f"ml_signal:{symbol}")

    # ── Training progress ─────────────────────────────────────────────────
    def set_training_progress(self, data: dict) -> None:
        self.set("training:progress", data, ttl=3600)

    def get_training_progress(self) -> dict | None:
        return self.get("training:progress")

    # ── Rate limiting ─────────────────────────────────────────────────────
    def check_rate_limit(self, key: str, max_calls: int, window_secs: int) -> bool:
        """Return True if call is allowed, False if rate limit exceeded."""
        k = self.KEY_PREFIX + f"rl:{key}"
        pipe = self._r.pipeline()
        pipe.incr(k)
        pipe.expire(k, window_secs)
        results = pipe.execute()
        count = int(results[0])
        # Only set TTL when the key is newly created to enforce a fixed window
        if count == 1:
            self._r.expire(k, window_secs)
        return count <= max_calls

    # ── Pub/Sub ───────────────────────────────────────────────────────────
    def subscribe(self, channel: str, callback: Callable) -> None:
        def _listener():
            ps = self._r.pubsub()
            ps.subscribe(**{f"bml:{channel}": callback})
            ps.run_in_thread(sleep_time=0.001, daemon=True)
        t = threading.Thread(target=_listener, daemon=True)
        t.start()
        _pubsub_threads.append(t)

    # ── Health ─────────────────────────────────────────────────────────────
    def health_check(self) -> bool:
        try:
            return self._r.ping()
        except Exception:
            return False
