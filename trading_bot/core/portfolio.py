"""
Portfolio manager – tracks balances, positions, P&L, and GBP value
using live Binance data with Redis caching.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from loguru import logger

from config import get_settings
from db.redis_client import RedisClient


@dataclass
class Position:
    symbol: str
    qty: Decimal
    avg_entry: Decimal
    current_price: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    unrealized_pnl_pct: float = 0.0
    side: str = "LONG"

    def update_price(self, price: Decimal) -> None:
        self.current_price = price
        if self.avg_entry > 0:
            self.unrealized_pnl = (price - self.avg_entry) * self.qty
            self.unrealized_pnl_pct = float(
                (price - self.avg_entry) / self.avg_entry * 100
            )


@dataclass
class PortfolioSnapshot:
    total_usdt: Decimal = Decimal("0")
    total_gbp: Decimal = Decimal("0")
    realized_pnl_today: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    assets: dict = field(default_factory=dict)
    positions: list = field(default_factory=list)
    timestamp: float = 0.0


class PortfolioManager:
    """Thread-safe portfolio state management."""

    def __init__(self, binance_client=None) -> None:
        self._client = binance_client
        self._redis = RedisClient()
        self._settings = get_settings()
        self._lock = threading.RLock()
        self._positions: dict[str, Position] = {}
        self._balances: dict[str, dict] = {}
        self._gbp_rate: Decimal = Decimal("0.79")  # USD→GBP multiplier default (1/1.27)
        self._gbp_rate_updated_at: float = 0.0     # epoch – 0 means "never refreshed"
        self._snapshot = PortfolioSnapshot()
        self._callbacks: list = []

    # ── Public API ─────────────────────────────────────────────────────
    def refresh(self) -> PortfolioSnapshot:
        """Fetch live balances from Binance and update snapshot."""
        if not self._client or not self._settings.binance.api_key:
            return self._snapshot
        try:
            balances = self._client.get_balances()
            self._update_from_balances(balances)
            self._gbp_rate = self._get_gbp_rate()
            self._compute_snapshot()
        except Exception as exc:
            logger.error(f"Portfolio refresh error: {exc}")
        return self._snapshot

    def get_snapshot(self) -> PortfolioSnapshot:
        cached = self._redis.get_portfolio()
        if cached:
            return cached
        return self._snapshot

    def add_position(self, symbol: str, qty: Decimal, price: Decimal) -> None:
        with self._lock:
            if symbol in self._positions:
                pos = self._positions[symbol]
                total_cost = pos.avg_entry * pos.qty + price * qty
                pos.qty += qty
                pos.avg_entry = total_cost / pos.qty if pos.qty > 0 else Decimal("0")
            else:
                self._positions[symbol] = Position(
                    symbol=symbol, qty=qty, avg_entry=price
                )

    def close_position(self, symbol: str, qty: Decimal, exit_price: Decimal) -> Decimal:
        """Close (or reduce) a position, return realised P&L."""
        with self._lock:
            pos = self._positions.get(symbol)
            if not pos:
                return Decimal("0")
            pnl = (exit_price - pos.avg_entry) * qty
            pos.qty -= qty
            if pos.qty <= Decimal("0.00001"):
                del self._positions[symbol]
            return pnl

    def update_prices(self, prices: dict[str, Decimal]) -> None:
        with self._lock:
            for sym, price in prices.items():
                if sym in self._positions:
                    self._positions[sym].update_price(price)

    def register_callback(self, fn) -> None:
        self._callbacks.append(fn)

    # ── Internals ───────────────────────────────────────────────────────
    def _update_from_balances(self, balances: list[dict]) -> None:
        with self._lock:
            self._balances = {
                b["asset"]: b for b in balances
                if float(b["free"]) + float(b["locked"]) > 0.00001
            }

    def _compute_snapshot(self) -> None:
        import time
        # Take a consistent snapshot of balances and positions under the lock,
        # then do all I/O (price fetches) outside the lock to avoid holding it.
        with self._lock:
            balances_snapshot = dict(self._balances)
            positions_snapshot = dict(self._positions)

        # Batch-fetch prices for all non-USDT assets in one pass to avoid N+1
        non_usdt = [a for a in balances_snapshot if a != "USDT"]
        prices: dict[str, Decimal] = {}
        if self._client and non_usdt:
            try:
                all_tickers = self._client.get_all_tickers()
                ticker_map = {t["symbol"]: Decimal(str(t["price"])) for t in all_tickers}
                for asset in non_usdt:
                    sym = f"{asset}USDT"
                    if sym in ticker_map:
                        prices[asset] = ticker_map[sym]
            except Exception as exc:
                logger.debug(f"Batch price fetch failed, falling back per-asset: {exc}")
                for asset in non_usdt:
                    try:
                        prices[asset] = self._client.get_price(f"{asset}USDT")
                    except Exception:
                        pass

        total_usdt = Decimal("0")
        assets = {}
        for asset, b in balances_snapshot.items():
            free = Decimal(str(b["free"]))
            locked = Decimal(str(b["locked"]))
            total = free + locked
            if asset == "USDT":
                usd_val = total
            else:
                usd_val = total * prices.get(asset, Decimal("0"))
            total_usdt += usd_val
            assets[asset] = {
                "free": float(free),
                "locked": float(locked),
                "usd_value": float(usd_val),
                "gbp_value": float(usd_val * self._gbp_rate),
            }

        unrealized = sum(
            p.unrealized_pnl for p in positions_snapshot.values()
        )

        snap = PortfolioSnapshot(
            total_usdt=total_usdt,
            total_gbp=total_usdt * self._gbp_rate,
            unrealized_pnl=unrealized,
            assets=assets,
            positions=list(positions_snapshot.values()),
            timestamp=__import__("time").time(),
        )
        self._snapshot = snap
        self._redis.cache_portfolio(
            {"total_usdt": float(total_usdt), "total_gbp": float(snap.total_gbp)}
        )
        for cb in self._callbacks:
            try:
                cb(snap)
            except Exception as _cb_exc:
                logger.warning(f"[Portfolio] Snapshot callback raised: {_cb_exc}")

    def _get_gbp_rate(self) -> Decimal:
        """Approximate GBP/USD using GBPUSDT if available."""
        import time as _time
        try:
            if self._client:
                price = self._client.get_price("GBPUSDT")
                rate = Decimal("1") / price
                self._gbp_rate_updated_at = _time.time()
                return rate
        except Exception as exc:
            logger.warning(f"[Portfolio] Could not refresh GBP/USD rate: {exc}")
        # Fallback – warn if the cached rate is more than 1 hour old
        age = _time.time() - self._gbp_rate_updated_at
        if age > 3600:
            logger.warning(
                f"[Portfolio] GBP/USD rate is stale ({age / 3600:.1f} h old). "
                "Using hardcoded fallback 0.79 – P&L values in GBP may be inaccurate."
            )
        return self._gbp_rate
