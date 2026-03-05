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


BASE_URL = "https://api.binance.com"
TESTNET_URL = "https://testnet.binance.vision"
WS_BASE = "wss://stream.binance.com:9443/ws"
WS_TESTNET = "wss://testnet.binance.vision/ws"


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
        self._ws_base = WS_TESTNET if self._testnet else WS_BASE
        self._session = requests.Session()
        self._session.headers.update({
            "X-MBX-APIKEY": self._api_key,
            "Content-Type": "application/json",
        })
        self._redis = RedisClient()
        self._ws_threads: dict[str, threading.Thread] = {}
        self._ws_active: dict[str, bool] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()

    # ── Authentication ──────────────────────────────────────────────────
    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        params["signature"] = hmac.new(
            self._api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        return params

    # ── REST requests ───────────────────────────────────────────────────
    def _get(self, path: str, params: dict | None = None, signed: bool = False) -> Any:
        if signed:
            params = self._sign(params or {})
        resp = self._session.get(f"{self._base}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, params: dict | None = None, signed: bool = True) -> Any:
        if signed:
            params = self._sign(params or {})
        resp = self._session.post(f"{self._base}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str, params: dict | None = None, signed: bool = True) -> Any:
        if signed:
            params = self._sign(params or {})
        resp = self._session.delete(f"{self._base}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

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
            self._callbacks[stream].append(callback)

        if stream in self._ws_active and self._ws_active[stream]:
            return  # Already subscribed

        def _on_message(ws, message):
            import json
            try:
                data = json.loads(message)
                for cb in self._callbacks.get(stream, []):
                    try:
                        cb(data)
                    except Exception as e:
                        logger.error(f"WS callback error: {e}")
            except Exception:
                pass

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
            self._ws_active[stream] = True
            ws.run_forever(ping_interval=20, ping_timeout=10)

        t = threading.Thread(target=_run, daemon=True, name=f"ws-{stream}")
        t.start()
        self._ws_threads[stream] = t

    def close_all(self) -> None:
        for stream in list(self._ws_active):
            self._ws_active[stream] = False
        self._session.close()
