"""
Binance REST + WebSocket client with automatic reconnection,
rate-limit tracking, and signature verification.

Two WebSocket subsystems are provided:

1. Market-data stream multiplexer (_WsMultiplexer)
   - Spec: https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
   - Public endpoint: wss://data-stream.binance.vision/ws
   - SUBSCRIBE / UNSUBSCRIBE management on a single connection.
   - Combined-stream {"stream":"…","data":{…}} payloads unwrapped.
   - Management messages rate-limited to 5/second per Binance spec.
   - Proactive 23-hour reconnect (server force-disconnects at 24 h).
   - Partial-depth levels validated: only 5, 10, 20 are supported.
   - Port-443 fallback when 9443 is blocked.

2. WebSocket API client (_WsApiClient)
   - Spec: https://developers.binance.com/docs/binance-spot-api-docs/websocket-api
   - Endpoint: wss://ws-api.binance.com/ws-api/v3
   - Request/response over WebSocket with per-request id correlation.
   - Security types per Binance spec:
       NONE        — public (no auth)
       USER_STREAM — apiKey only
       TRADE / USER_DATA — SIGNED (apiKey + timestamp + signature)
   - Signing algorithms supported:
       HMAC-SHA256 — hex-encoded signature, case-insensitive params
       Ed25519     — Base64 signature, case-sensitive params (session auth)
   - Alphabetises params before signing per Binance WS API spec.
   - Session authentication (session.logon/status/logout) via Ed25519:
       Once authenticated, apiKey + signature are not required per request.
       timestamp is still required for SIGNED requests.
   - Rate-limit consumption tracked from response rateLimits array.
   - serverShutdown event handled — triggers immediate reconnect.
   - Exponential back-off on reconnect (2 s → 4 → 8 → … capped at 60 s).
   - Data source latency tiers per Binance spec:
       Matching Engine > Memory > Database
"""

from __future__ import annotations

import base64
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

# ── WebSocket options market-data endpoint (European Vanilla Options) ────────
# Spec: https://developers.binance.com/docs/derivatives/options-trading/websocket-market-streams
# Stream format: <underlying>@optionOpenInterest@<expirationDate>  (60 s update)
# expirationDate format: YYMMDD  (e.g. "221125" for 2022-11-25)
_WS_OPTIONS_PRIMARY  = "wss://nbstream.binance.com/eoptions/ws"
_WS_OPTIONS_FALLBACK = "wss://nbstream.binance.com/eoptions/ws"  # single PoP; retry same host

# ── WebSocket API endpoints (authenticated trading API) ──────────────────────
# Distinct from market-data streams — supports request/response trading
# Security types: NONE, USER_STREAM, TRADE, USER_DATA (SIGNED)
_WS_API_URL     = "wss://ws-api.binance.com/ws-api/v3"
_WS_API_TESTNET = "wss://testnet.binance.vision/ws-api/v3"

_MAX_RETRIES   = 3     # Max retries on transient network / timeout errors
_RETRY_BACKOFF = 1.0   # Initial backoff seconds (doubles each retry)

# Valid partial-depth levels per Binance spec (only 5, 10, 20 are supported)
_VALID_DEPTH_LEVELS = frozenset({5, 10, 20})


class _RateLimiter:
    """
    Thread-safe token-bucket rate limiter.

    Binance published limits (spot) — https://developers.binance.com/docs/binance-spot-api-docs/rest-api/limits:
      - 6 000 weighted request units / minute  (REQUEST_WEIGHT; IP-based)
      - 50 orders / 10 seconds                 (ORDERS; account-based)
      - 160 000 orders / 24 hours              (ORDERS; account-based)

    The bot targets 80% of each limit to maintain a safety margin and
    avoid the automated IP ban that follows repeated 429 responses.
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

    def __init__(
        self,
        primary_url: str = _WS_PRIMARY,
        fallback_url: str = _WS_FALLBACK,
    ) -> None:
        self._primary_url   = primary_url
        self._fallback_url  = fallback_url
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
            url = self._fallback_url if self._use_fallback else self._primary_url

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


class _WsApiClient:
    """
    Binance WebSocket API client — authenticated request/response trading.

    Endpoint
    ────────
    wss://ws-api.binance.com/ws-api/v3   (production)
    wss://testnet.binance.vision/ws-api/v3 (testnet)

    Security types (Binance spec)
    ─────────────────────────────
    NONE        — public requests, no auth parameters
    USER_STREAM — apiKey only (no signature)
    TRADE / USER_DATA — SIGNED:
        • apiKey  — included in params
        • timestamp — milliseconds since epoch
        • signature — HMAC-SHA256 (hex) or Ed25519 (Base64)
        • recvWindow — optional, default 5000 ms, max 60 000 ms

    Signing algorithms
    ──────────────────
    HMAC-SHA256 (default for send_signed):
        1. Add apiKey + timestamp to params
        2. Alphabetise all params (excluding signature)
        3. Format: "key1=val1&key2=val2&…"  (UTF-8)
        4. HMAC-SHA256 with secret → lowercase hex string
        5. Append signature to params

    Ed25519 (used exclusively for session.logon):
        Steps 1-3 same as HMAC.
        4. Ed25519 sign with private key → Base64-encoded string
        5. Append signature to params
        Note: Ed25519 params are case-sensitive.

    Session authentication
    ──────────────────────
    Call session_logon() with Ed25519 key loaded via load_ed25519_key().
    After logon, subsequent TRADE/USER_DATA requests omit apiKey/signature
    (timestamp is still required).  Individual requests can still override
    the session key by including their own apiKey + signature (ad-hoc auth).

    Rate limiting
    ─────────────
    Each response includes a rateLimits array showing current consumption.
    This client logs warning when >80% of any limit is consumed.

    Reconnection
    ────────────
    Exponential back-off: 2 s → 4 → 8 → … capped at 60 s.
    serverShutdown events trigger immediate reconnect.
    Session authentication state is cleared on disconnect.
    """

    _RECONNECT_CAP = 60.0

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False) -> None:
        self._api_key    = api_key
        self._api_secret = api_secret
        self._url        = _WS_API_TESTNET if testnet else _WS_API_URL

        self._lock    = threading.Lock()
        self._ws_lock = threading.Lock()
        self._ws      = None
        self._ready   = threading.Event()
        self._active  = False
        self._req_id  = 0

        # Pending request tracking: id → (Event, result_slot)
        self._pending: dict[int, threading.Event] = {}
        self._results: dict[int, dict]            = {}

        # Session authentication state
        self._session_auth    = False
        self._session_api_key: str | None = None

        # Ed25519 private key object (loaded on demand)
        self._ed25519_key = None

    # ── Key management ───────────────────────────────────────────────────────

    def load_ed25519_key(self, pem_path: str) -> None:
        """Load an Ed25519 private key from a PEM file.

        Required for session authentication (session.logon).
        The cryptography package must be installed:  pip install cryptography
        """
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        with open(pem_path, "rb") as fh:
            self._ed25519_key = load_pem_private_key(fh.read(), password=None)
        logger.info(f"WS API: Ed25519 key loaded from {pem_path}")

    def set_ed25519_key_bytes(self, pem_bytes: bytes) -> None:
        """Load an Ed25519 private key from raw PEM bytes (e.g. from secrets store)."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        self._ed25519_key = load_pem_private_key(pem_bytes, password=None)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._active = True
        threading.Thread(target=self._run_loop, daemon=True, name="ws-api").start()

    def close(self) -> None:
        self._active = False
        with self._ws_lock:
            ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    # ── Connection loop ──────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        import websocket as _wslib
        backoff = 2.0

        while self._active:
            def _on_open(ws):
                nonlocal backoff
                backoff = 2.0
                with self._ws_lock:
                    self._ws = ws
                self._ready.set()
                logger.info(f"WS API: connected ({self._url})")

            def _on_message(ws, raw):
                try:
                    msg = json.loads(raw)
                except Exception:
                    return

                # serverShutdown — server is about to restart; reconnect now
                if msg.get("method") == "serverShutdown":
                    logger.warning("WS API: serverShutdown received — reconnecting")
                    self._session_auth = False
                    self._session_api_key = None
                    self._ready.clear()
                    try:
                        ws.close()
                    except Exception:
                        pass
                    return

                req_id = msg.get("id")
                if req_id is not None:
                    # Track rate-limit consumption
                    for rl in msg.get("rateLimits", []):
                        used  = rl.get("count", 0)
                        limit = rl.get("limit", 1)
                        if limit and used / limit >= 0.8:
                            logger.warning(
                                f"WS API rate-limit [{rl.get('rateLimitType')}]: "
                                f"{used}/{limit} ({used/limit*100:.0f}%)"
                            )
                    with self._lock:
                        self._results[req_id] = msg
                        evt = self._pending.get(req_id)
                    if evt:
                        evt.set()

            def _on_error(ws, error):
                self._ready.clear()
                self._session_auth = False
                self._session_api_key = None
                logger.warning(f"WS API error: {error}")

            def _on_close(ws, code, msg):
                self._ready.clear()
                self._session_auth = False
                self._session_api_key = None
                logger.info(f"WS API closed (code={code})")

            with self._ws_lock:
                self._ws = None

            app = _wslib.WebSocketApp(
                self._url,
                on_open=_on_open,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
            )
            app.run_forever(ping_interval=20, ping_timeout=10)

            if not self._active:
                break

            logger.info(f"WS API: reconnecting in {backoff:.1f}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, self._RECONNECT_CAP)

    # ── Request / response ───────────────────────────────────────────────────

    def _next_id(self) -> int:
        with self._lock:
            self._req_id += 1
            return self._req_id

    def _send_request(
        self,
        method: str,
        params: dict | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Send a WebSocket API request and block until the matching response arrives.

        Returns the full response dict (id, status, result, rateLimits).
        Raises RuntimeError on API errors; TimeoutError if no response arrives.
        """
        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("WS API: connection not ready")

        req_id = self._next_id()
        evt    = threading.Event()

        with self._lock:
            self._pending[req_id] = evt

        payload: dict[str, Any] = {"id": req_id, "method": method}
        if params:
            payload["params"] = params

        with self._ws_lock:
            ws = self._ws
        if ws is None:
            with self._lock:
                self._pending.pop(req_id, None)
            raise RuntimeError("WS API: no active connection")

        try:
            ws.send(json.dumps(payload))
        except Exception as exc:
            with self._lock:
                self._pending.pop(req_id, None)
            raise RuntimeError(f"WS API send failed: {exc}") from exc

        if not evt.wait(timeout=timeout):
            with self._lock:
                self._pending.pop(req_id, None)
                self._results.pop(req_id, None)
            raise TimeoutError(f"WS API: no response for {method!r} within {timeout}s")

        with self._lock:
            self._pending.pop(req_id, None)
            result = self._results.pop(req_id, {})

        status = result.get("status", 0)
        if status != 200:
            err  = result.get("error", {})
            code = err.get("code", status)
            msg  = err.get("msg", "Unknown error")
            raise RuntimeError(f"WS API [{method}] error {code}: {msg}")

        return result

    # ── Signing ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_payload(params: dict) -> str:
        """Alphabetise params and format as key=value& string (Binance WS API spec)."""
        return "&".join(f"{k}={v}" for k, v in sorted(params.items()))

    def _sign_hmac(self, params: dict) -> dict:
        """Add apiKey, timestamp, and HMAC-SHA256 hex signature to params.

        Signing algorithm (Binance WS API spec):
          1. Add apiKey and timestamp.
          2. Alphabetise all params (excluding signature).
          3. Format as UTF-8 "key=value&…" string.
          4. HMAC-SHA256 with api_secret → lowercase hex.
          5. Append signature to params.
        """
        params["apiKey"]    = self._api_key
        params["timestamp"] = int(time.time() * 1000)
        payload             = self._build_payload(params)
        params["signature"] = hmac.new(
            self._api_secret.encode(),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return params

    def _sign_ed25519(self, params: dict) -> dict:
        """Add apiKey, timestamp, and Ed25519 Base64 signature to params.

        Signing algorithm (Binance WS API spec — case-sensitive):
          1. Add apiKey and timestamp.
          2. Alphabetise all params (excluding signature).
          3. Format as UTF-8 "key=value&…" string.
          4. Ed25519 sign with private key → Base64-encoded bytes.
          5. Append signature to params.

        Required for session.logon (only Ed25519 supports session auth).
        """
        if self._ed25519_key is None:
            raise RuntimeError(
                "Ed25519 private key not loaded. "
                "Call load_ed25519_key(path) or set_ed25519_key_bytes(pem) first."
            )
        params["apiKey"]    = self._api_key
        params["timestamp"] = int(time.time() * 1000)
        payload             = self._build_payload(params)
        sig_bytes           = self._ed25519_key.sign(payload.encode("utf-8"))
        params["signature"] = base64.b64encode(sig_bytes).decode("ascii")
        return params

    # ── Public request helpers ───────────────────────────────────────────────

    def send_unsigned(
        self,
        method: str,
        params: dict | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Send a NONE-security request (public market data, connectivity tests)."""
        return self._send_request(method, params, timeout=timeout)

    def send_api_key(
        self,
        method: str,
        params: dict | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Send a USER_STREAM request (apiKey only, no signature)."""
        p = dict(params or {})
        p["apiKey"] = self._api_key
        return self._send_request(method, p, timeout=timeout)

    def send_signed(
        self,
        method: str,
        params: dict | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Send a TRADE/USER_DATA request signed with HMAC-SHA256.

        If the session is authenticated (after session.logon), apiKey and
        signature are NOT added — only timestamp is required per Binance spec.
        To override the session key for a specific request, pass explicit
        apiKey and signature in params (ad-hoc authorisation).
        """
        p = dict(params or {})
        if self._session_auth and "apiKey" not in p:
            # Session already authenticated — only timestamp required
            p.setdefault("timestamp", int(time.time() * 1000))
            return self._send_request(method, p, timeout=timeout)
        return self._send_request(method, self._sign_hmac(p), timeout=timeout)

    # ── Session authentication ────────────────────────────────────────────────
    # Only Ed25519 keys are supported for session authentication.
    # Reference: https://developers.binance.com/docs/binance-spot-api-docs/
    #            websocket-api/session-authentication

    def session_logon(self, timeout: float = 10.0) -> dict:
        """Authenticate the WebSocket session using Ed25519.

        After a successful logon, subsequent TRADE/USER_DATA requests sent via
        send_signed() will omit apiKey and signature automatically.
        timestamp is still included in every SIGNED request.

        Raises RuntimeError if the Ed25519 key is not loaded.
        """
        params = self._sign_ed25519({})
        result = self._send_request("session.logon", params, timeout=timeout)
        self._session_auth    = True
        self._session_api_key = self._api_key
        logger.info("WS API: session authenticated")
        return result

    def session_status(self, timeout: float = 10.0) -> dict:
        """Query the authentication status of the current WebSocket connection.

        Returns the authorizedSince timestamp and current apiKey if authenticated,
        or null if unauthenticated.  Weight: 2.  Data source: Memory.
        """
        return self._send_request("session.status", timeout=timeout)

    def session_logout(self, timeout: float = 10.0) -> dict:
        """Forget the API key associated with the current WebSocket connection.

        After logout, TRADE/USER_DATA requests must include apiKey + signature.
        Weight: 2.  Data source: Memory.
        """
        result = self._send_request("session.logout", timeout=timeout)
        self._session_auth    = False
        self._session_api_key = None
        logger.info("WS API: session logged out")
        return result

    @property
    def is_session_authenticated(self) -> bool:
        """True if session.logon has succeeded and has not been revoked."""
        return self._session_auth

    # ── General requests ─────────────────────────────────────────────────────
    # Reference: https://developers.binance.com/docs/binance-spot-api-docs/
    #            websocket-api/general-requests

    def ping(self, timeout: float = 5.0) -> bool:
        """Test WebSocket connectivity.  Weight: 1.  Data source: Memory."""
        self._send_request("ping", timeout=timeout)
        return True

    def get_server_time(self, timeout: float = 5.0) -> int:
        """Get server time in milliseconds.  Weight: 1.  Data source: Memory."""
        return self._send_request("time", timeout=timeout)["result"]["serverTime"]

    def get_exchange_info(
        self,
        symbol: str | None = None,
        symbols: list[str] | None = None,
        permissions: list[str] | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Get exchange trading rules.  Weight: 20.  Data source: Memory.

        Only one filter (symbol / symbols / permissions) may be provided.
        """
        params: dict = {}
        if symbol:
            params["symbol"] = symbol
        elif symbols:
            params["symbols"] = symbols
        elif permissions:
            params["permissions"] = permissions
        return self._send_request("exchangeInfo", params or None, timeout=timeout)["result"]

    # ── Market data requests ──────────────────────────────────────────────────
    # Reference: https://developers.binance.com/docs/binance-spot-api-docs/
    #            websocket-api/market-data-requests
    # Data sources: Memory (low latency) or Database (historical)

    def get_depth(
        self,
        symbol: str,
        limit: int = 100,
        timeout: float = 10.0,
    ) -> dict:
        """Get current order book.

        Weight: 5 (limit ≤ 100) / 25 (≤ 500) / 50 (≤ 1000) / 250 (≤ 5000).
        Data source: Memory.
        limit: 1–5000 (default 100).
        """
        return self._send_request(
            "depth", {"symbol": symbol, "limit": limit}, timeout=timeout
        )["result"]

    def get_recent_trades(
        self,
        symbol: str,
        limit: int = 500,
        timeout: float = 10.0,
    ) -> list:
        """Get recent trades.  Weight: 25.  Data source: Memory.  limit ≤ 1000."""
        return self._send_request(
            "trades.recent", {"symbol": symbol, "limit": limit}, timeout=timeout
        )["result"]

    def get_historical_trades(
        self,
        symbol: str,
        from_id: int | None = None,
        limit: int = 500,
        timeout: float = 10.0,
    ) -> list:
        """Get historical trades.  Weight: 25.  Data source: Database.  limit ≤ 1000."""
        params: dict = {"symbol": symbol, "limit": limit}
        if from_id is not None:
            params["fromId"] = from_id
        return self._send_request("trades.historical", params, timeout=timeout)["result"]

    def get_aggregate_trades(
        self,
        symbol: str,
        from_id: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
        timeout: float = 10.0,
    ) -> list:
        """Get compressed aggregate trades.  Weight: 4.  Data source: Database."""
        params: dict = {"symbol": symbol, "limit": limit}
        if from_id is not None:
            params["fromId"] = from_id
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return self._send_request("trades.aggregate", params, timeout=timeout)["result"]

    def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int | None = None,
        end_time: int | None = None,
        time_zone: str | None = None,
        limit: int = 500,
        timeout: float = 10.0,
    ) -> list:
        """Get kline/candlestick data.  Weight: 2.  Data source: Database.

        interval: 1s 1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w 1M
        time_zone: UTC offset string, e.g. "+05:30" (range: -12:00 to +14:00)
        """
        params: dict = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        if time_zone is not None:
            params["timeZone"] = time_zone
        return self._send_request("klines", params, timeout=timeout)["result"]

    def get_avg_price(self, symbol: str, timeout: float = 5.0) -> dict:
        """Get current average price.  Weight: 2.  Data source: Memory."""
        return self._send_request("avgPrice", {"symbol": symbol}, timeout=timeout)["result"]

    def get_ticker_24hr(
        self,
        symbol: str | None = None,
        symbols: list[str] | None = None,
        ticker_type: str = "FULL",
        timeout: float = 10.0,
    ) -> Any:
        """Get 24-hour rolling window price statistics.

        Weight: 2 (1 symbol) / 80 (all symbols).  Data source: Memory.
        ticker_type: "FULL" (default) or "MINI".
        """
        params: dict = {"type": ticker_type}
        if symbol:
            params["symbol"] = symbol
        elif symbols:
            params["symbols"] = symbols
        return self._send_request("ticker.24hr", params, timeout=timeout)["result"]

    def get_ticker_price(
        self,
        symbol: str | None = None,
        symbols: list[str] | None = None,
        timeout: float = 5.0,
    ) -> Any:
        """Get latest price(s).  Weight: 2 (all) / 4 (filtered).  Data source: Memory."""
        params: dict = {}
        if symbol:
            params["symbol"] = symbol
        elif symbols:
            params["symbols"] = symbols
        return self._send_request("ticker.price", params or None, timeout=timeout)["result"]

    def get_ticker_book(
        self,
        symbol: str | None = None,
        symbols: list[str] | None = None,
        timeout: float = 5.0,
    ) -> Any:
        """Get best bid/ask prices.  Weight: 2 (all) / 4 (filtered).  Data source: Memory."""
        params: dict = {}
        if symbol:
            params["symbol"] = symbol
        elif symbols:
            params["symbols"] = symbols
        return self._send_request("ticker.book", params or None, timeout=timeout)["result"]

    def get_ticker_rolling(
        self,
        symbol: str | None = None,
        symbols: list[str] | None = None,
        window_size: str = "1d",
        ticker_type: str = "FULL",
        timeout: float = 10.0,
    ) -> Any:
        """Get rolling-window price statistics.

        Weight: 4 per symbol (max 200).  Data source: Database.
        window_size: 1m-59m, 1h-23h, 1d-7d.
        """
        params: dict = {"windowSize": window_size, "type": ticker_type}
        if symbol:
            params["symbol"] = symbol
        elif symbols:
            params["symbols"] = symbols
        return self._send_request("ticker", params, timeout=timeout)["result"]

    # ── Trading requests ──────────────────────────────────────────────────────
    # Security: TRADE (apiKey + signature required).
    # Data source: Matching Engine (lowest latency).
    # Reference: https://developers.binance.com/docs/binance-spot-api-docs/
    #            websocket-api/trading-requests

    def order_place(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float | None = None,
        quote_order_qty: float | None = None,
        price: float | None = None,
        time_in_force: str | None = None,
        stop_price: float | None = None,
        iceberg_qty: float | None = None,
        new_client_order_id: str | None = None,
        new_order_resp_type: str | None = None,
        self_trade_prevention_mode: str | None = None,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Place a new order.  Weight: 1.  Security: TRADE.  Source: Matching Engine.

        new_order_resp_type: ACK | RESULT | FULL (default FULL for LIMIT/MARKET).
        """
        params: dict = {"symbol": symbol, "side": side.upper(), "type": order_type.upper()}
        if quantity is not None:
            params["quantity"] = f"{quantity:.8f}"
        if quote_order_qty is not None:
            params["quoteOrderQty"] = f"{quote_order_qty:.8f}"
        if price is not None:
            params["price"] = f"{price:.8f}"
        if time_in_force is not None:
            params["timeInForce"] = time_in_force
        if stop_price is not None:
            params["stopPrice"] = f"{stop_price:.8f}"
        if iceberg_qty is not None:
            params["icebergQty"] = f"{iceberg_qty:.8f}"
        if new_client_order_id is not None:
            params["newClientOrderId"] = new_client_order_id
        if new_order_resp_type is not None:
            params["newOrderRespType"] = new_order_resp_type
        if self_trade_prevention_mode is not None:
            params["selfTradePreventionMode"] = self_trade_prevention_mode
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        result = self.send_signed("order.place", params, timeout=timeout)
        logger.info(
            f"WS API order placed: {symbol} {side} {order_type} "
            f"qty={quantity} price={price} → {result.get('result', {}).get('orderId')}"
        )
        return result["result"]

    def order_test(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float | None = None,
        price: float | None = None,
        time_in_force: str | None = None,
        compute_commission_rates: bool = False,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Test order placement without sending.  Weight: 1 or 20.  Security: TRADE.

        Returns empty result normally; with compute_commission_rates=True returns
        commission rate details (weight: 20).
        """
        params: dict = {"symbol": symbol, "side": side.upper(), "type": order_type.upper()}
        if quantity is not None:
            params["quantity"] = f"{quantity:.8f}"
        if price is not None:
            params["price"] = f"{price:.8f}"
        if time_in_force is not None:
            params["timeInForce"] = time_in_force
        if compute_commission_rates:
            params["computeCommissionRates"] = True
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("order.test", params, timeout=timeout)["result"]

    def order_cancel(
        self,
        symbol: str,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
        new_client_order_id: str | None = None,
        cancel_restrictions: str | None = None,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Cancel an active order.  Weight: 1.  Security: TRADE.  Source: Matching Engine.

        One of order_id or orig_client_order_id is required.
        cancel_restrictions: ONLY_NEW | ONLY_PARTIALLY_FILLED
        """
        params: dict = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = order_id
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        if new_client_order_id is not None:
            params["newClientOrderId"] = new_client_order_id
        if cancel_restrictions is not None:
            params["cancelRestrictions"] = cancel_restrictions
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("order.cancel", params, timeout=timeout)["result"]

    def order_cancel_replace(
        self,
        symbol: str,
        side: str,
        order_type: str,
        cancel_replace_mode: str,
        cancel_order_id: int | None = None,
        cancel_orig_client_order_id: str | None = None,
        quantity: float | None = None,
        price: float | None = None,
        time_in_force: str | None = None,
        stop_price: float | None = None,
        new_client_order_id: str | None = None,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Cancel an existing order and immediately place a replacement.

        Weight: 1.  Security: TRADE.  Source: Matching Engine.
        cancel_replace_mode: STOP_ON_FAILURE | ALLOW_FAILURE.
        Response status: 200 (full success), 400 (failure), 409 (partial).
        """
        params: dict = {
            "symbol":            symbol,
            "side":              side.upper(),
            "type":              order_type.upper(),
            "cancelReplaceMode": cancel_replace_mode,
        }
        if cancel_order_id is not None:
            params["cancelOrderId"] = cancel_order_id
        if cancel_orig_client_order_id is not None:
            params["cancelOrigClientOrderId"] = cancel_orig_client_order_id
        if quantity is not None:
            params["quantity"] = f"{quantity:.8f}"
        if price is not None:
            params["price"] = f"{price:.8f}"
        if time_in_force is not None:
            params["timeInForce"] = time_in_force
        if stop_price is not None:
            params["stopPrice"] = f"{stop_price:.8f}"
        if new_client_order_id is not None:
            params["newClientOrderId"] = new_client_order_id
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("order.cancelReplace", params, timeout=timeout)["result"]

    def order_amend_keep_priority(
        self,
        symbol: str,
        new_qty: float,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Reduce order quantity while keeping queue priority.

        Weight: 4.  Security: TRADE.  Source: Matching Engine.
        new_qty must be less than the current order quantity.
        Does not count towards unfilled order limit.
        """
        params: dict = {"symbol": symbol, "newQty": f"{new_qty:.8f}"}
        if order_id is not None:
            params["orderId"] = order_id
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("order.amend.keepPriority", params, timeout=timeout)["result"]

    def open_orders_cancel_all(
        self,
        symbol: str,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> list:
        """Cancel all open orders on a symbol.  Weight: 1.  Security: TRADE."""
        params: dict = {"symbol": symbol}
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("openOrders.cancelAll", params, timeout=timeout)["result"]

    def order_list_place_oco(
        self,
        symbol: str,
        side: str,
        quantity: float,
        above_type: str,
        below_type: str,
        above_price: float | None = None,
        above_stop_price: float | None = None,
        below_price: float | None = None,
        below_stop_price: float | None = None,
        below_time_in_force: str | None = None,
        list_client_order_id: str | None = None,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Place an OCO (One-Cancels-the-Other) order list.  Weight: 1.  Security: TRADE."""
        params: dict = {
            "symbol":    symbol,
            "side":      side.upper(),
            "quantity":  f"{quantity:.8f}",
            "aboveType": above_type.upper(),
            "belowType": below_type.upper(),
        }
        if above_price is not None:
            params["abovePrice"] = f"{above_price:.8f}"
        if above_stop_price is not None:
            params["aboveStopPrice"] = f"{above_stop_price:.8f}"
        if below_price is not None:
            params["belowPrice"] = f"{below_price:.8f}"
        if below_stop_price is not None:
            params["belowStopPrice"] = f"{below_stop_price:.8f}"
        if below_time_in_force is not None:
            params["belowTimeInForce"] = below_time_in_force
        if list_client_order_id is not None:
            params["listClientOrderId"] = list_client_order_id
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("orderList.place.oco", params, timeout=timeout)["result"]

    # ── Account requests ──────────────────────────────────────────────────────
    # Security: USER_DATA (apiKey + signature required).
    # Reference: https://developers.binance.com/docs/binance-spot-api-docs/
    #            websocket-api/account-requests

    def account_status(
        self,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Get account information and balances.  Weight: 20.  Security: USER_DATA."""
        params: dict = {}
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("account.status", params or None, timeout=timeout)["result"]

    def order_status(
        self,
        symbol: str,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Check order execution status.  Weight: 4.  Security: USER_DATA."""
        params: dict = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = order_id
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("order.status", params, timeout=timeout)["result"]

    def open_orders_status(
        self,
        symbol: str | None = None,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> list:
        """Query open orders.  Weight: 6 (symbol) / 80 (all).  Security: USER_DATA."""
        params: dict = {}
        if symbol is not None:
            params["symbol"] = symbol
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("openOrders.status", params or None, timeout=timeout)["result"]

    def all_orders(
        self,
        symbol: str,
        order_id: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> list:
        """Retrieve account order history.  Weight: 20.  Security: USER_DATA.

        Time range max: 24 hours.  limit: 1–1000 (default 500).
        """
        params: dict = {"symbol": symbol, "limit": limit}
        if order_id is not None:
            params["orderId"] = order_id
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("allOrders", params, timeout=timeout)["result"]

    def my_trades(
        self,
        symbol: str,
        order_id: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        from_id: int | None = None,
        limit: int = 500,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> list:
        """Query trade history.  Weight: 5 (with orderId) / 20.  Security: USER_DATA."""
        params: dict = {"symbol": symbol, "limit": limit}
        if order_id is not None:
            params["orderId"] = order_id
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        if from_id is not None:
            params["fromId"] = from_id
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("myTrades", params, timeout=timeout)["result"]

    def account_rate_limits_orders(
        self,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> list:
        """Get unfilled order counts for all intervals.  Weight: 40.  Security: USER_DATA."""
        params: dict = {}
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed(
            "account.rateLimits.orders", params or None, timeout=timeout
        )["result"]

    def account_commission(
        self,
        symbol: str,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """Get current commission rates for a symbol.  Weight: 20.  Security: USER_DATA."""
        params: dict = {"symbol": symbol}
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        return self.send_signed("account.commission", params, timeout=timeout)["result"]

    # ── User data stream requests ─────────────────────────────────────────────
    # Reference: https://developers.binance.com/docs/binance-spot-api-docs/
    #            websocket-api/user-data-stream-requests
    # Max 1000 simultaneous subscriptions; max 65535 total per session lifetime.

    def user_data_stream_subscribe(self, timeout: float = 10.0) -> int:
        """Subscribe to User Data Stream on the current (session-authenticated) connection.

        Requires Ed25519 session authentication.  Weight: 2.
        Returns subscriptionId.
        """
        result = self._send_request("userDataStream.subscribe", timeout=timeout)
        return result["result"]["subscriptionId"]

    def user_data_stream_subscribe_signature(
        self,
        recv_window: int | None = None,
        timeout: float = 10.0,
    ) -> int:
        """Subscribe to User Data Stream using explicit HMAC/Ed25519 signature.

        Does not require session authentication.  Weight: 2.
        Returns subscriptionId.
        """
        params: dict = {}
        if recv_window is not None:
            params["recvWindow"] = min(recv_window, 60000)
        result = self.send_signed(
            "userDataStream.subscribe.signature", params or None, timeout=timeout
        )
        return result["result"]["subscriptionId"]

    def user_data_stream_unsubscribe(
        self,
        subscription_id: int | None = None,
        timeout: float = 10.0,
    ) -> None:
        """Unsubscribe from User Data Stream.  Weight: 2.

        If subscription_id is None, all active subscriptions are closed.
        Note: session.logout only closes subscriptions created via
        userDataStream.subscribe (not signature-based ones).
        """
        params: dict = {}
        if subscription_id is not None:
            params["subscriptionId"] = subscription_id
        self._send_request("userDataStream.unsubscribe", params or None, timeout=timeout)

    def session_subscriptions(self, timeout: float = 5.0) -> list:
        """List all active subscriptions in the current session.

        Weight: 2.  Data source: Memory.
        Returns array of subscription objects with subscriptionId values.
        """
        return self._send_request(
            "session.subscriptions", {}, timeout=timeout
        )["result"]


class BinanceClient:
    """
    Full Binance API client supporting:
    - Spot trading (market, limit, stop-loss, take-profit)
    - Order book (L1 / L2)
    - Account & portfolio
    - Historical klines
    - WebSocket streams for real-time data (multiplexed, spec-compliant)
    - WebSocket API for authenticated request/response trading (_WsApiClient)
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
        ed25519_key_path: str | None = None,
    ) -> None:
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

        # Rate limiters — Binance spot limits (80% safety margin applied):
        #   REQUEST_WEIGHT: 6000/min → target 4800/min
        #   ORDERS:         50/10s  → target 40/10s ; 160000/day → tracked separately
        self._rl_general = _RateLimiter(calls=4800, period_sec=60)
        self._rl_orders  = _RateLimiter(calls=40,   period_sec=10)

        # Daily order counter — Binance hard limit: 160 000 orders per 24 h.
        # Resets at UTC midnight (or when the bot restarts).
        self._daily_order_count = 0
        self._daily_order_reset = time.time() + 86400  # next reset in 24 h
        self._daily_order_lock  = threading.Lock()
        self._DAILY_ORDER_LIMIT = 128_000  # 80% of 160 000

        # Single multiplexed WebSocket connection (market-data streams, started lazily)
        self._ws_mux: _WsMultiplexer | None = None
        self._ws_mux_lock = threading.Lock()

        # Options market-data multiplexer (European Vanilla Options, started lazily)
        # Uses a separate connection to wss://nbstream.binance.com/eoptions/ws
        self._ws_opts_mux: _WsMultiplexer | None = None
        self._ws_opts_mux_lock = threading.Lock()

        # WebSocket API client (authenticated request/response, started lazily)
        self._ws_api_client: _WsApiClient | None = None
        self._ws_api_lock = threading.Lock()
        self._ed25519_key_path = ed25519_key_path

    def _get_mux(self) -> _WsMultiplexer:
        """Return the shared WS multiplexer, creating and starting it if needed."""
        with self._ws_mux_lock:
            if self._ws_mux is None:
                self._ws_mux = _WsMultiplexer()
                self._ws_mux.start()
            return self._ws_mux

    def _get_opts_mux(self) -> _WsMultiplexer:
        """Return the options WS multiplexer, creating and starting it if needed.

        Uses the Binance European Vanilla Options stream endpoint
        (wss://nbstream.binance.com/eoptions/ws) which is separate from the
        standard spot market-data endpoint.
        """
        with self._ws_opts_mux_lock:
            if self._ws_opts_mux is None:
                self._ws_opts_mux = _WsMultiplexer(
                    primary_url=_WS_OPTIONS_PRIMARY,
                    fallback_url=_WS_OPTIONS_FALLBACK,
                )
                self._ws_opts_mux.start()
            return self._ws_opts_mux

    def _get_ws_api(self) -> _WsApiClient:
        """Return the WS API client, creating and starting it if needed.

        The client connects to the Binance WebSocket API endpoint and supports
        authenticated trading requests, session management, and market data queries.
        Load an Ed25519 key via ed25519_key_path (constructor) to enable
        session.logon for reduced per-request overhead.
        """
        with self._ws_api_lock:
            if self._ws_api_client is None:
                client = _WsApiClient(
                    api_key=self._api_key,
                    api_secret=self._api_secret,
                    testnet=self._testnet,
                )
                if self._ed25519_key_path:
                    client.load_ed25519_key(self._ed25519_key_path)
                client.start()
                self._ws_api_client = client
            return self._ws_api_client

    @property
    def ws_api(self) -> _WsApiClient:
        """Direct access to the WebSocket API client (lazy-initialised).

        Example — place a LIMIT order over WebSocket::

            result = client.ws_api.order_place(
                symbol="BTCUSDT", side="BUY", order_type="LIMIT",
                quantity=0.001, price=30000.0, time_in_force="GTC",
            )

        Example — session authentication with Ed25519 (lower per-request overhead)::

            client = BinanceClient(ed25519_key_path="/secrets/ed25519.pem")
            client.ws_api.session_logon()   # authenticate once
            client.ws_api.order_place(...)  # subsequent requests need no signature
        """
        return self._get_ws_api()

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

            # Proactive rate-limit monitoring via Binance response headers.
            # X-MBX-USED-WEIGHT-1M: cumulative request weight consumed this minute.
            # X-MBX-ORDER-COUNT-1D: unfilled order count over the last 24 hours.
            used_weight = resp.headers.get("X-MBX-USED-WEIGHT-1M")
            if used_weight and int(used_weight) >= 4800:  # ≥80% of 6000
                logger.warning(
                    f"Binance REQUEST_WEIGHT at {used_weight}/6000 — "
                    "approaching rate limit"
                )
            order_count_1d = resp.headers.get("X-MBX-ORDER-COUNT-1D")
            if order_count_1d and int(order_count_1d) >= 128_000:  # ≥80% of 160 000
                logger.warning(
                    f"Binance daily ORDER count at {order_count_1d}/160000 — "
                    "approaching daily limit"
                )

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

    def _check_daily_order_limit(self) -> None:
        """Raise RuntimeError if the daily order budget (80% of 160 000) is exhausted.

        Resets the counter automatically at the 24-hour boundary.
        """
        with self._daily_order_lock:
            now = time.time()
            if now >= self._daily_order_reset:
                self._daily_order_count = 0
                self._daily_order_reset = now + 86400
            self._daily_order_count += 1
            if self._daily_order_count > self._DAILY_ORDER_LIMIT:
                raise RuntimeError(
                    f"Daily order budget exceeded ({self._daily_order_count}/"
                    f"{self._DAILY_ORDER_LIMIT}). "
                    "Trading paused to comply with Binance 160 000/day limit. "
                    "Counter resets in "
                    f"{int(self._daily_order_reset - now)}s."
                )
            if self._daily_order_count % 1000 == 0:
                logger.info(
                    f"Daily order count: {self._daily_order_count}/{self._DAILY_ORDER_LIMIT}"
                )

    def _post(self, path: str, params: dict | None = None, signed: bool = True) -> Any:
        self._rl_general.acquire()
        self._rl_orders.acquire()
        self._check_daily_order_limit()
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
    #   ticker             <symbol>@ticker
    #   miniTicker         <symbol>@miniTicker
    #   bookTicker         <symbol>@bookTicker        (best bid/ask, real-time)
    #   avgPrice           <symbol>@avgPrice
    #   kline              <symbol>@kline_<interval>
    #   aggTrade           <symbol>@aggTrade          (aggregated trades)
    #   trade              <symbol>@trade             (individual trades)
    #   depth              <symbol>@depth<N>@100ms   (N ∈ {5, 10, 20} only)
    #
    # Options stream name formats (Binance European Vanilla Options — separate endpoint):
    #   optionOpenInterest <underlying>@optionOpenInterest@<expirationDate>  (60 s update)
    #                      expirationDate: YYMMDD  e.g. "221125" for 2022-11-25
    #                      Payload fields: e, E, s (symbol), o (OI contracts), h (OI USDT)

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

    def subscribe_option_open_interest(
        self,
        underlying: str,
        expiration_date: str,
        callback: Callable,
    ) -> None:
        """Options open interest stream for one underlying/expiry pair (60 s update).

        Connects to the Binance European Vanilla Options endpoint
        (wss://nbstream.binance.com/eoptions/ws), which is separate from the
        standard spot market-data connection.

        Args:
            underlying:      Underlying asset symbol, e.g. ``"ETHUSDT"`` or
                             ``"BTCUSDT"``.  Case-insensitive; lowercased
                             internally as required by Binance.
            expiration_date: Contract expiry in ``YYMMDD`` format, e.g.
                             ``"221125"`` for 25 November 2022.
            callback:        Callable invoked with each payload ``dict``.

        Payload fields (Binance spec):
            ``e``  – event type (``"openInterest"``)
            ``E``  – event time (Unix ms)
            ``s``  – option symbol, e.g. ``"ETH-221125-2700-C"``
            ``o``  – open interest in contracts
            ``h``  – open interest value in USDT
        """
        stream = f"{underlying.lower()}@optionOpenInterest@{expiration_date}"
        self._get_opts_mux().subscribe(stream, callback)

    def unsubscribe_option_open_interest(
        self,
        underlying: str,
        expiration_date: str,
        callback: Callable | None = None,
    ) -> None:
        """Remove *callback* from the open-interest stream for *underlying*/*expiration_date*.

        Sends UNSUBSCRIBE to the options endpoint when the last listener is
        removed.  Pass ``callback=None`` to remove all listeners at once.
        """
        mux = self._ws_opts_mux
        if mux is None:
            return
        stream = f"{underlying.lower()}@optionOpenInterest@{expiration_date}"
        mux.unsubscribe(stream, callback)

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
        """Close all WebSocket connections and the REST session."""
        with self._ws_mux_lock:
            mux = self._ws_mux
            self._ws_mux = None
        if mux:
            mux.close()
        with self._ws_opts_mux_lock:
            opts_mux = self._ws_opts_mux
            self._ws_opts_mux = None
        if opts_mux:
            opts_mux.close()
        with self._ws_api_lock:
            ws_api = self._ws_api_client
            self._ws_api_client = None
        if ws_api:
            ws_api.close()
        self._session.close()
