"""
Binance REST + WebSocket client with automatic reconnection,
rate-limit tracking, and signature verification.

WebSocket implementation follows the Binance Spot API specification:
  https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams

Key compliance points:
  - Single multiplexed connection per client via JSON SUBSCRIBE / UNSUBSCRIBE
    commands (not one WS connection per stream).
  - Binance closes connections after exactly 24 hours; we proactively reconnect
    at 23 hours to avoid stream interruption.
  - Management messages (SUBSCRIBE / UNSUBSCRIBE) are rate-limited to 5/second
    as required by the Binance docs.
  - Combined-stream payloads {"stream":"…","data":{…}} are unwrapped before
    dispatching to per-stream callbacks.
  - Market-data streams always use the public data-stream endpoint
    (data-stream.binance.vision) — the testnet WS does not support all
    stream types / symbols (causes Handshake 404 errors).
  - Partial-depth level is validated to only use the supported values 5, 10, 20.
  - Port 443 is used as a fallback when port 9443 is unavailable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from decimal import Decimal
from typing import Any, Callable, Optional
from urllib.parse import urlencode

import requests
from loguru import logger

from config import get_settings
from db.redis_client import RedisClient


# ── REST endpoints ───────────────────────────────────────────────────────────
BASE_URL    = "https://api.binance.com"
TESTNET_URL = "https://testnet.binance.vision"

# ── WebSocket market-data endpoints (public, no auth required) ───────────────
# Primary:   data-stream.binance.vision  (market-data only, as per Binance docs)
# Fallback:  stream.binance.com:443      (alternative port if 9443 is blocked)
_WS_PRIMARY  = "wss://data-stream.binance.vision/ws"
_WS_FALLBACK = "wss://stream.binance.com:443/ws"

_MAX_RETRIES   = 3     # Max retries on transient network / timeout errors
_RETRY_BACKOFF = 1.0   # Initial backoff seconds (doubles each retry)

# Valid partial-depth levels per Binance spec (only 5, 10, 20 are supported)
_VALID_DEPTH_LEVELS = frozenset({5, 10, 20})


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


class _WsMultiplexer:
    """
    Single persistent WebSocket connection that multiplexes all Binance
    market-data streams for one BinanceClient instance.

    Binance rules enforced
    ──────────────────────
    • Streams managed via SUBSCRIBE / UNSUBSCRIBE JSON messages on a single
      connection (up to 1 024 streams per connection).
    • Management messages rate-limited to 5 per second.
    • Proactive reconnect every 23 h (server force-disconnects at 24 h).
    • On reconnect, all registered streams are re-subscribed automatically in
      a single batched SUBSCRIBE message.
    • Combined-stream payloads {"stream":"…","data":{…}} unwrapped before
      delivering to per-stream callbacks.
    • Exponential back-off on errors: 2 s → 4 → 8 → … capped at 60 s.
    • Falls back from primary URL to port-443 alternative after 3 consecutive
      connection failures.
    """

    _RECONNECT_S  = 23 * 3600  # proactive cycle before the 24-hour server limit
    _MSG_PER_SEC  = 5           # Binance management rate limit
    _MAX_STREAMS  = 1024
    _FAIL_SWITCH  = 3           # consecutive failures before trying fallback URL

    def __init__(self) -> None:
        self._lock          = threading.Lock()
        self._cbs: dict[str, list[Callable]] = {}   # stream → [callback, …]
        self._ws_lock       = threading.Lock()
        self._ws            = None                  # current WebSocketApp
        self._ready         = threading.Event()     # set when connection is open
        self._active        = False
        self._req_id        = 0
        self._fail_count    = 0                     # consecutive connection failures
        self._use_fallback  = False
        self._timer: threading.Timer | None = None
        # Throttle state – separate lock so it never blocks main logic
        self._throttle_lock = threading.Lock()
        self._msg_times: list[float] = []

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._active = True
        self._launch_thread()

    def close(self) -> None:
        self._active = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        with self._ws_lock:
            ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    # ── Public subscribe / unsubscribe ───────────────────────────────────────

    def subscribe(self, stream: str, callback: Callable) -> None:
        """Register *callback* for *stream*; sends SUBSCRIBE if first listener."""
        with self._lock:
            if stream not in self._cbs:
                self._cbs[stream] = []
            first = not self._cbs[stream]   # True when no listeners yet
            if callback not in self._cbs[stream]:
                self._cbs[stream].append(callback)
        # Only push a SUBSCRIBE command when this is a brand-new stream AND
        # the connection is already live.  If not live, _on_open will batch-
        # subscribe everything when the connection is established.
        if first and self._ready.is_set():
            threading.Thread(
                target=self._send_manage,
                args=("SUBSCRIBE", [stream]),
                daemon=True,
                name=f"ws-sub-{stream}",
            ).start()

    def unsubscribe(self, stream: str, callback: Callable | None = None) -> None:
        """Remove *callback* (or all callbacks) from *stream*; sends UNSUBSCRIBE
        when the last listener is removed."""
        drop_stream = False
        with self._lock:
            if stream not in self._cbs:
                return
            if callback is None:
                self._cbs.pop(stream, None)
                drop_stream = True
            else:
                try:
                    self._cbs[stream].remove(callback)
                except ValueError:
                    pass
                if not self._cbs[stream]:
                    self._cbs.pop(stream, None)
                    drop_stream = True
        if drop_stream:
            threading.Thread(
                target=self._send_manage,
                args=("UNSUBSCRIBE", [stream]),
                daemon=True,
                name=f"ws-unsub-{stream}",
            ).start()

    @property
    def stream_count(self) -> int:
        with self._lock:
            return len(self._cbs)

    # ── Internal connection management ───────────────────────────────────────

    def _launch_thread(self) -> None:
        t = threading.Thread(target=self._run_loop, daemon=True, name="ws-mux")
        t.start()

    def _schedule_reconnect(self) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self._RECONNECT_S, self._proactive_reconnect)
        self._timer.daemon = True
        self._timer.start()

    def _proactive_reconnect(self) -> None:
        if not self._active:
            return
        logger.info("WS: proactive 23-hour reconnect")
        self._ready.clear()
        with self._ws_lock:
            ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    def _run_loop(self) -> None:
        import websocket as _wslib

        backoff = 2.0

        while self._active:
            url = _WS_FALLBACK if self._use_fallback else _WS_PRIMARY

            # -- Callbacks are defined fresh each iteration so closures are clean --

            def _on_open(ws, _url=url):
                nonlocal backoff
                backoff      = 2.0
                self._fail_count = 0
                with self._ws_lock:
                    self._ws = ws
                self._ready.set()
                logger.info(f"WS multiplexer: connected ({_url})")
                # Re-subscribe all streams in one batched message so the
                # websocket thread is not blocked by per-message throttling.
                with self._lock:
                    streams = list(self._cbs.keys())
                if streams:
                    threading.Thread(
                        target=self._send_manage,
                        args=("SUBSCRIBE", streams),
                        kwargs={"ws": ws},
                        daemon=True,
                        name="ws-resubscribe",
                    ).start()
                self._schedule_reconnect()

            def _on_message(ws, raw):
                try:
                    msg = json.loads(raw)
                except Exception:
                    return
                # Ack for SUBSCRIBE / UNSUBSCRIBE: {"result": null, "id": N}
                if "id" in msg and "result" in msg:
                    return
                # Unwrap combined-stream envelope {"stream":"…","data":{…}}
                stream  = msg.get("stream")
                payload = msg.get("data", msg)
                if stream:
                    with self._lock:
                        cbs = list(self._cbs.get(stream, []))
                    for cb in cbs:
                        try:
                            cb(payload)
                        except Exception as exc:
                            logger.error(f"WS callback error [{stream}]: {exc}")

            def _on_error(ws, error):
                self._ready.clear()
                logger.warning(f"WS error: {error}")

            def _on_close(ws, code, msg):
                self._ready.clear()
                logger.info(f"WS closed (code={code})")

            with self._ws_lock:
                self._ws = None

            app = _wslib.WebSocketApp(
                url,
                on_open=_on_open,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
            )
            app.run_forever(ping_interval=20, ping_timeout=10)

            if not self._active:
                break

            # Track failures and optionally switch to the fallback URL
            self._fail_count += 1
            if self._fail_count >= self._FAIL_SWITCH:
                self._use_fallback = not self._use_fallback
                self._fail_count   = 0
                logger.info(
                    f"WS: switching to {'fallback' if self._use_fallback else 'primary'} URL"
                )

            logger.info(f"WS: reconnecting in {backoff:.1f}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    # ── Subscription message helpers ─────────────────────────────────────────

    def _send_manage(
        self,
        method: str,
        streams: list[str],
        ws=None,
    ) -> None:
        """Send a SUBSCRIBE or UNSUBSCRIBE command.

        Waits up to 5 s for the connection to be ready, then rate-limits to
        5 management messages per second as required by the Binance spec.
        Multiple streams are batched into a single message where possible.
        """
        if not streams:
            return
        if not self._ready.wait(timeout=5.0):
            logger.warning(f"WS {method}: connection not ready; streams={streams}")
            return
        with self._ws_lock:
            target = ws or self._ws
        if target is None:
            return
        with self._lock:
            self._req_id += 1
            req_id = self._req_id
        self._throttle()
        try:
            target.send(json.dumps({
                "method": method,
                "params": streams,
                "id":     req_id,
            }))
        except Exception as exc:
            logger.warning(f"WS {method} send failed: {exc}")

    def _throttle(self) -> None:
        """Block if needed to stay within the 5-messages/second limit."""
        with self._throttle_lock:
            now = time.monotonic()
            self._msg_times = [t for t in self._msg_times if now - t < 1.0]
            if len(self._msg_times) >= self._MSG_PER_SEC:
                wait = 1.0 - (now - self._msg_times[0])
            else:
                wait = 0.0
            self._msg_times.append(time.monotonic())
        if wait > 0:
            time.sleep(wait)


class BinanceClient:
    """
    Full Binance API client supporting:
    - Spot trading (market, limit, stop-loss, take-profit)
    - Order book (L1 / L2)
    - Account & portfolio
    - Historical klines
    - WebSocket streams for real-time data (multiplexed, spec-compliant)
    """

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = True) -> None:
        settings = get_settings()
        self._api_key    = api_key or settings.binance.api_key
        self._api_secret = api_secret or settings.binance.api_secret
        self._testnet    = testnet if api_key else settings.binance.testnet
        self._base       = TESTNET_URL if self._testnet else BASE_URL
        self._session    = requests.Session()
        self._session.headers.update({
            "X-MBX-APIKEY": self._api_key,
            "Content-Type": "application/json",
        })
        self._redis = RedisClient()
        self._lock  = threading.Lock()

        # Rate limiters — Binance spot: 1200 req/min general, 10 orders/sec
        self._rl_general = _RateLimiter(calls=1200, period_sec=60)
        self._rl_orders  = _RateLimiter(calls=10,   period_sec=1)

        # Single multiplexed WebSocket connection (started lazily on first subscribe)
        self._ws_mux: _WsMultiplexer | None = None
        self._ws_mux_lock = threading.Lock()

    def _get_mux(self) -> _WsMultiplexer:
        """Return the shared WS multiplexer, creating and starting it if needed."""
        with self._ws_mux_lock:
            if self._ws_mux is None:
                self._ws_mux = _WsMultiplexer()
                self._ws_mux.start()
            return self._ws_mux

    # ── Authentication ───────────────────────────────────────────────────────
    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        params["signature"] = hmac.new(
            self._api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        return params

    # ── REST requests ────────────────────────────────────────────────────────
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

    # ── Market data ──────────────────────────────────────────────────────────
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

    # ── Account ──────────────────────────────────────────────────────────────
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

    # ── Trading ──────────────────────────────────────────────────────────────
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
            "symbol":   symbol,
            "side":     side.upper(),
            "type":     order_type.upper(),
            "quantity": f"{quantity:.8f}",
        }
        if order_type.upper() == "LIMIT":
            params["price"]       = f"{price:.8f}"
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

    # ── WebSocket streams ────────────────────────────────────────────────────
    #
    # All subscribe_* methods register a callback on the shared _WsMultiplexer.
    # The multiplexer maintains a single persistent connection and manages
    # SUBSCRIBE / UNSUBSCRIBE lifecycle transparently.
    #
    # Stream name formats (Binance spec):
    #   ticker      <symbol>@ticker
    #   miniTicker  <symbol>@miniTicker
    #   bookTicker  <symbol>@bookTicker        (best bid/ask, real-time)
    #   avgPrice    <symbol>@avgPrice
    #   kline       <symbol>@kline_<interval>
    #   aggTrade    <symbol>@aggTrade          (aggregated trades)
    #   trade       <symbol>@trade             (individual trades)
    #   depth       <symbol>@depth<N>@100ms   (N ∈ {5, 10, 20} only)

    def subscribe_ticker(self, symbol: str, callback: Callable) -> None:
        """24-hour rolling ticker statistics (1 000 ms update)."""
        self._get_mux().subscribe(f"{symbol.lower()}@ticker", callback)

    def subscribe_mini_ticker(self, symbol: str, callback: Callable) -> None:
        """Condensed 24-hour ticker (1 000 ms update)."""
        self._get_mux().subscribe(f"{symbol.lower()}@miniTicker", callback)

    def subscribe_book_ticker(self, symbol: str, callback: Callable) -> None:
        """Best bid/ask price & quantity (real-time)."""
        self._get_mux().subscribe(f"{symbol.lower()}@bookTicker", callback)

    def subscribe_avg_price(self, symbol: str, callback: Callable) -> None:
        """Current average price (1 000 ms update)."""
        self._get_mux().subscribe(f"{symbol.lower()}@avgPrice", callback)

    def subscribe_kline(self, symbol: str, interval: str, callback: Callable) -> None:
        """Kline/candlestick stream (1 000 ms for 1 s bars; 2 000 ms for others).

        Valid intervals: 1s 1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w 1M
        """
        self._get_mux().subscribe(f"{symbol.lower()}@kline_{interval}", callback)

    def subscribe_trade(self, symbol: str, callback: Callable) -> None:
        """Aggregated trade stream (real-time).

        Each message represents one or more trades executed at the same price.
        """
        self._get_mux().subscribe(f"{symbol.lower()}@aggTrade", callback)

    def subscribe_raw_trade(self, symbol: str, callback: Callable) -> None:
        """Individual (non-aggregated) trade stream (real-time)."""
        self._get_mux().subscribe(f"{symbol.lower()}@trade", callback)

    def subscribe_depth(
        self,
        symbol: str,
        callback: Callable,
        levels: int = 20,
    ) -> None:
        """Partial order-book depth snapshot (100 ms update).

        *levels* must be 5, 10, or 20 — the only values supported by Binance.
        Any other value is silently clamped to 20.
        """
        if levels not in _VALID_DEPTH_LEVELS:
            logger.warning(
                f"subscribe_depth: levels={levels} is not supported by Binance "
                f"(valid: {sorted(_VALID_DEPTH_LEVELS)}); using 20."
            )
            levels = 20
        self._get_mux().subscribe(f"{symbol.lower()}@depth{levels}@100ms", callback)

    def unsubscribe_stream(
        self,
        stream: str,
        callback: Callable | None = None,
    ) -> None:
        """Remove *callback* from *stream* (or all callbacks if None).

        Sends an UNSUBSCRIBE command when the last listener is removed.
        """
        mux = self._get_mux()
        mux.unsubscribe(stream, callback)

    @property
    def active_stream_count(self) -> int:
        """Number of currently active WebSocket streams."""
        if self._ws_mux is None:
            return 0
        return self._ws_mux.stream_count

    def close_all(self) -> None:
        """Close the WebSocket multiplexer and the REST session."""
        with self._ws_mux_lock:
            mux = self._ws_mux
            self._ws_mux = None
        if mux:
            mux.close()
        self._session.close()
