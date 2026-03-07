"""
Exchange Market Data Collector  (Layer 2 – Module 7)
=====================================================
Streams spot, perp, futures, and options market data from centralised
exchanges (primarily Binance) via WebSocket and REST polling.

Dependency activation:
  Requires: BINANCE_API_KEY, BINANCE_SECRET_KEY
  Auto-enables: real_time_cache
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from loguru import logger


class MarketDataEvent:
    __slots__ = ("symbol", "event_type", "data", "timestamp", "exchange")

    def __init__(self, symbol: str, event_type: str, data: dict,
                 exchange: str = "binance"):
        self.symbol = symbol
        self.event_type = event_type
        self.data = data
        self.exchange = exchange
        self.timestamp = time.time()


class ExchangeMarketDataCollector:
    """
    Collects live market data from exchange websocket streams.

    Streams:
    - Kline (1m, 5m, 15m, 1h, 4h, 1d)
    - Ticker (24h stats)
    - Book ticker (best bid/ask)
    - Mini ticker (all markets)
    - Aggregate trades

    Feature flag: 'ml_trading'
    """

    MAX_BUFFER = 10_000

    def __init__(self, binance_client=None):
        self._client = binance_client
        self._subscribers: List[Callable[[MarketDataEvent], None]] = []
        self._buffer: Deque[MarketDataEvent] = deque(maxlen=self.MAX_BUFFER)
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._subscribed_symbols: List[str] = []
        self._last_tickers: Dict[str, dict] = {}

    # ── Control ───────────────────────────────────────────────────────────────

    def subscribe(self, symbols: List[str]) -> None:
        with self._lock:
            self._subscribed_symbols = list(set(self._subscribed_symbols + symbols))

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="exchange-mdc"
        )
        self._thread.start()
        logger.info(f"[ExchangeMDC] Started for {len(self._subscribed_symbols)} symbols")

    def stop(self) -> None:
        self._running = False

    def on_event(self, callback: Callable[[MarketDataEvent], None]) -> None:
        self._subscribers.append(callback)

    # ── Data access ───────────────────────────────────────────────────────────

    def get_latest_ticker(self, symbol: str) -> Optional[dict]:
        with self._lock:
            return self._last_tickers.get(symbol)

    def get_recent_events(self, n: int = 100) -> List[MarketDataEvent]:
        with self._lock:
            return list(self._buffer)[-n:]

    def get_subscribed_symbols(self) -> List[str]:
        return list(self._subscribed_symbols)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while self._running:
            if self._client and self._subscribed_symbols:
                self._fetch_tickers()
            time.sleep(5)

    def _fetch_tickers(self) -> None:
        try:
            if hasattr(self._client, "get_ticker"):
                for sym in self._subscribed_symbols[:20]:  # rate-limit
                    try:
                        ticker = self._client.get_ticker(symbol=sym)
                        if ticker:
                            evt = MarketDataEvent(sym, "ticker", ticker)
                            with self._lock:
                                self._last_tickers[sym] = ticker
                                self._buffer.append(evt)
                            self._publish(evt)
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug(f"[ExchangeMDC] Fetch error: {exc}")

    def _publish(self, event: MarketDataEvent) -> None:
        for cb in self._subscribers:
            try:
                cb(event)
            except Exception as exc:
                logger.debug(f"[ExchangeMDC] Subscriber error: {exc}")

    @property
    def is_running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())
