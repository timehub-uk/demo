"""
Binance REST + WebSocket client with automatic reconnection,
rate-limit tracking, and signature verification.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import threading
from decimal import Decimal
from typing import Any, Callable, Optional
from urllib.parse import urlencode

import requests
from loguru import logger

from config import get_settings
from db.redis_client import RedisClient


BASE_URL    = "https://api.binance.com"
TESTNET_URL = "https://testnet.binance.vision"
WS_BASE     = "wss://stream.binance.com:9443/ws"
WS_TESTNET  = "wss://stream.testnet.binance.vision/ws"

_MAX_RETRIES   = 3     # Max retries on transient network / timeout errors
_RETRY_BACKOFF = 1.0   # Initial backoff seconds (doubles each retry)


class _RateLimiter:
    """
    Thread-safe token-bucket rate limiter.

    Binance published limits (spot):
      - 1 200 weighted request units / minute (general endpoints)
      - 10 orders / second (signed trade endpoints)
    """

    def __init__(self, calls: int, period_sec: float) -> None:
        self._calls  = calls
        self._period = period_sec
        self._tokens = float(calls)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until one token is available."""
        with self._lock:
            now     = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                float(self._calls),
                self._tokens + elapsed / self._period * self._calls,
            )
            self._last_refill = now
            if self._tokens < 1:
                wait = (1.0 - self._tokens) / self._calls * self._period
            else:
                wait = 0.0
            self._tokens -= 1.0
        if wait > 0:
            time.sleep(wait)


class BinanceClient:
    """
    Full Binance API client supporting:
    - Spot trading (market, limit, stop-loss, take-profit)
    - Order book (L1 / L2)
    - Account & portfolio
    - Historical klines
    - WebSocket streams for real-time data
    """

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = True) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.binance.api_key
        self._api_secret = api_secret or settings.binance.api_secret
        self._testnet = testnet if api_key else settings.binance.testnet
        self._base = TESTNET_URL if self._testnet else BASE_URL
        # Market-data WebSocket streams are public and always use the
        # production endpoint – the testnet WS does not support all symbols
        # or stream types, causing Handshake 404 errors (e.g. depth20@100ms).
        self._ws_base = WS_BASE
        self._session = requests.Session()
        self._session.headers.update({
            "X-MBX-APIKEY": self._api_key,
            "Content-Type": "application/json",
        })
        self._redis = RedisClient()
        self._ws_threads: dict[str, threading.Thread] = {}
        self._ws_active: dict[str, bool] = {}
        self._ws_objects: dict[str, Any] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()

        # Rate limiters — Binance spot: 1200 req/min general, 10 orders/sec
        self._rl_general = _RateLimiter(calls=1200, period_sec=60)
        self._rl_orders  = _RateLimiter(calls=10,   period_sec=1)

    # ── Authentication ──────────────────────────────────────────────────
    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        params["signature"] = hmac.new(
            self._api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        return params

    # ── REST requests ───────────────────────────────────────────────────
    def _request(self, method: str, path: str, params: dict | None) -> Any:
        """
        Shared HTTP executor with:
          - Binance 429 (rate-limit) and 418 (IP ban) back-off
          - Transient network/timeout retry with exponential back-off
          - Clean Binance error-code surfacing (code + msg)
        """
        url  = f"{self._base}{path}"
        send = {
            "GET":    self._session.get,
            "POST":   self._session.post,
            "DELETE": self._session.delete,
        }[method]
        backoff = _RETRY_BACKOFF

        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = send(url, params=params, timeout=10)
            except requests.exceptions.Timeout:
                logger.warning(
                    f"Binance {method} {path} timed out (attempt {attempt + 1}/{_MAX_RETRIES + 1})"
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise
            except requests.exceptions.ConnectionError as exc:
                logger.warning(
                    f"Binance {method} {path} connection error "
                    f"(attempt {attempt + 1}/{_MAX_RETRIES + 1}): {exc!r}"
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise

            # Handle Binance-specific HTTP status codes
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", backoff * 2))
                logger.warning(
                    f"Binance rate-limit hit (429) on {method} {path} — "
                    f"backing off {wait:.1f}s"
                )
                time.sleep(wait)
                backoff = min(backoff * 2, 60)
                continue

            if resp.status_code == 418:
                logger.error(
                    f"Binance IP temporarily banned (418) on {method} {path} — "
                    f"cooling off 60 s"
                )
                time.sleep(60)
                backoff = min(backoff * 4, 120)
                continue

            # Surface Binance JSON error body before raise_for_status
            if not resp.ok:
                try:
                    err  = resp.json()
                    code = err.get("code", resp.status_code)
                    msg  = err.get("msg",  resp.text)
                    raise requests.exceptions.HTTPError(
                        f"Binance API error {code}: {msg}",
                        response=resp,
                    )
                except (ValueError, KeyError):
                    resp.raise_for_status()

            return resp.json()

        raise RuntimeError(
            f"Binance {method} {path} failed after {_MAX_RETRIES} retries"
        )

    def _get(self, path: str, params: dict | None = None, signed: bool = False) -> Any:
        self._rl_general.acquire()
        if signed:
            params = self._sign(params or {})
        return self._request("GET", path, params)

    def _post(self, path: str, params: dict | None = None, signed: bool = True) -> Any:
        self._rl_general.acquire()
        self._rl_orders.acquire()
        if signed:
            params = self._sign(params or {})
        return self._request("POST", path, params)

    def _delete(self, path: str, params: dict | None = None, signed: bool = True) -> Any:
        self._rl_general.acquire()
        self._rl_orders.acquire()
        if signed:
            params = self._sign(params or {})
        return self._request("DELETE", path, params)

    # ── Market data ─────────────────────────────────────────────────────
    def ping(self) -> bool:
        try:
            self._get("/api/v3/ping")
            return True
        except Exception:
            return False

    def get_server_time(self) -> int:
        return self._get("/api/v3/time")["serverTime"]

    def get_exchange_info(self) -> dict:
        return self._get("/api/v3/exchangeInfo")

    def get_ticker_24hr(self, symbol: str | None = None) -> Any:
        params = {"symbol": symbol} if symbol else {}
        return self._get("/api/v3/ticker/24hr", params)

    def get_price(self, symbol: str) -> Decimal:
        cached = self._redis.get_ticker(symbol)
        if cached and "price" in cached:
            return Decimal(str(cached["price"]))
        data = self._get("/api/v3/ticker/price", {"symbol": symbol})
        price = Decimal(data["price"])
        self._redis.cache_ticker(symbol, {"price": float(price)})
        return price

    def get_all_tickers(self) -> list[dict]:
        """Return all symbol prices from /api/v3/ticker/price (single round-trip)."""
        return self._get("/api/v3/ticker/price")

    def get_orderbook(self, symbol: str, limit: int = 20) -> dict:
        cached = self._redis.get_orderbook(symbol)
        if cached:
            return cached
        data = self._get("/api/v3/depth", {"symbol": symbol, "limit": limit})
        self._redis.cache_orderbook(symbol, data)
        return data

    def get_klines(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 500,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list:
        params: dict = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return self._get("/api/v3/klines", params)

    def get_top_symbols(self, quote: str = "USDT", top_n: int = 100) -> list[str]:
        """Return top N symbols by 24-h quote volume."""
        tickers = self._get("/api/v3/ticker/24hr")
        usdt = [
            t for t in tickers
            if t["symbol"].endswith(quote)
            and float(t["quoteVolume"]) > 0
        ]
        usdt.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
        return [t["symbol"] for t in usdt[:top_n]]

    # ── Account ─────────────────────────────────────────────────────────
    def get_account(self) -> dict:
        return self._get("/api/v3/account", signed=True)

    def get_balances(self) -> list[dict]:
        account = self.get_account()
        return [b for b in account["balances"] if float(b["free"]) > 0 or float(b["locked"]) > 0]

    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        params = {"symbol": symbol} if symbol else {}
        return self._get("/api/v3/openOrders", params, signed=True)

    def get_all_orders(self, symbol: str, limit: int = 500) -> list[dict]:
        return self._get("/api/v3/allOrders", {"symbol": symbol, "limit": limit}, signed=True)

    def get_my_trades(self, symbol: str, limit: int = 500) -> list[dict]:
        return self._get("/api/v3/myTrades", {"symbol": symbol, "limit": limit}, signed=True)

    # ── Trading ─────────────────────────────────────────────────────────
    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = "GTC",
    ) -> dict:
        params: dict = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": f"{quantity:.8f}",
        }
        if order_type.upper() == "LIMIT":
            params["price"] = f"{price:.8f}"
            params["timeInForce"] = time_in_force
        if stop_price:
            params["stopPrice"] = f"{stop_price:.8f}"
        result = self._post("/api/v3/order", params)
        logger.info(f"Order placed: {symbol} {side} {quantity} @ {price} → {result.get('orderId')}")
        return result

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        return self._delete("/api/v3/order", {"symbol": symbol, "orderId": order_id})

    def cancel_all_orders(self, symbol: str) -> list:
        return self._delete("/api/v3/openOrders", {"symbol": symbol})

    # ── WebSocket streams ────────────────────────────────────────────────
    def subscribe_ticker(self, symbol: str, callback: Callable) -> None:
        self._ws_subscribe(f"{symbol.lower()}@ticker", callback)

    def subscribe_kline(self, symbol: str, interval: str, callback: Callable) -> None:
        self._ws_subscribe(f"{symbol.lower()}@kline_{interval}", callback)

    def subscribe_depth(self, symbol: str, callback: Callable, levels: int = 20) -> None:
        self._ws_subscribe(f"{symbol.lower()}@depth{levels}@100ms", callback)

    def subscribe_trade(self, symbol: str, callback: Callable) -> None:
        self._ws_subscribe(f"{symbol.lower()}@aggTrade", callback)

    def _ws_subscribe(self, stream: str, callback: Callable) -> None:
        import websocket

        url = f"{self._ws_base}/{stream}"
        with self._lock:
            if stream not in self._callbacks:
                self._callbacks[stream] = []
            if callback not in self._callbacks[stream]:
                self._callbacks[stream].append(callback)
            if stream in self._ws_active and self._ws_active[stream]:
                return  # Already subscribed

        def _on_message(ws, message):
            import json
            try:
                data = json.loads(message)
                with self._lock:
                    callbacks = list(self._callbacks.get(stream, []))
                for cb in callbacks:
                    try:
                        cb(data)
                    except Exception as e:
                        logger.error(f"WS callback error: {e}")
            except Exception as exc:
                logger.warning(f"WS message parse error [{stream}]: {exc}")

        def _on_error(ws, error):
            logger.warning(f"WS error [{stream}]: {error}")

        def _on_close(ws, *args):
            self._ws_active[stream] = False
            logger.info(f"WS closed [{stream}], reconnecting…")
            time.sleep(3)
            self._ws_subscribe(stream, callback)

        def _run():
            ws = websocket.WebSocketApp(
                url,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
            )
            with self._lock:
                self._ws_active[stream] = True
                self._ws_objects[stream] = ws
            ws.run_forever(ping_interval=20, ping_timeout=10)

        t = threading.Thread(target=_run, daemon=True, name=f"ws-{stream}")
        t.start()
        self._ws_threads[stream] = t

    def close_all(self) -> None:
        with self._lock:
            streams = list(self._ws_active.keys())
            for stream in streams:
                self._ws_active[stream] = False
            ws_objects = dict(self._ws_objects)
        for ws in ws_objects.values():
            try:
                ws.close()
            except Exception:
                pass
        for stream, t in list(self._ws_threads.items()):
            t.join(timeout=3)
        self._session.close()
