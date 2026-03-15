"""
Order manager – creates, tracks, and reconciles orders with the exchange.
All orders are persisted to PostgreSQL and signalled via Redis pub/sub.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Optional

from loguru import logger
from sqlalchemy import select

from config import get_settings
from db.postgres import get_db
from db.models import Order, Trade
from db.redis_client import RedisClient


class OrderManager:
    """Thread-safe order lifecycle manager."""

    # Minimum notional value per order — aligned with £12 GBP floor
    # 12 GBP × 1.27 GBP/USDT ≈ 15.24 USDT; using 15.0 for a round number
    MIN_NOTIONAL_USDT: float = 15.0

    def __init__(self, binance_client=None, portfolio_manager=None) -> None:
        self._client = binance_client
        self._portfolio = portfolio_manager
        self._redis = RedisClient()
        self._settings = get_settings()
        self._lock = threading.Lock()
        self._open_orders: dict[str, dict] = {}   # order_id → order_dict
        self._callbacks: list[Callable] = []

    # ── Order creation ─────────────────────────────────────────────────
    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        user_id: str,
        is_automated: bool = False,
        ml_signal: str | None = None,
        ml_confidence: float = 0.0,
    ) -> Optional[dict]:
        return self._place_order(
            symbol=symbol, side=side, quantity=quantity,
            order_type="MARKET", user_id=user_id,
            is_automated=is_automated, ml_signal=ml_signal,
            ml_confidence=ml_confidence,
        )

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        user_id: str,
        stop_price: Decimal | None = None,
        is_automated: bool = False,
        ml_signal: str | None = None,
        ml_confidence: float = 0.0,
    ) -> Optional[dict]:
        return self._place_order(
            symbol=symbol, side=side, quantity=quantity,
            order_type="LIMIT", price=price, stop_price=stop_price,
            user_id=user_id, is_automated=is_automated,
            ml_signal=ml_signal, ml_confidence=ml_confidence,
        )

    def _place_order(self, *, symbol, side, quantity, order_type,
                     user_id, price=None, stop_price=None,
                     is_automated=False, ml_signal=None, ml_confidence=0.0) -> Optional[dict]:
        try:
            # ── Minimum notional check (£12 GBP floor) ──────────────────────────
            if price is not None:
                notional = float(quantity) * float(price)
                if notional < self.MIN_NOTIONAL_USDT:
                    logger.warning(
                        f"OrderManager: rejecting {side} {symbol} — notional "
                        f"{notional:.2f} USDT below minimum {self.MIN_NOTIONAL_USDT:.2f} USDT "
                        f"(≈ £12 GBP)"
                    )
                    return None

            result = None
            if self._client:
                result = self._client.place_order(
                    symbol=symbol, side=side, order_type=order_type,
                    quantity=float(quantity),
                    price=float(price) if price else None,
                    stop_price=float(stop_price) if stop_price else None,
                )

            binance_id = str(result.get("orderId", "")) if result else f"sim-{uuid.uuid4().hex[:8]}"

            with get_db() as db:
                order = Order(
                    user_id=user_id,
                    binance_order_id=binance_id,
                    symbol=symbol,
                    side=side.upper(),
                    order_type=order_type,
                    status=result.get("status", "NEW") if result else "NEW",
                    quantity=quantity,
                    price=price,
                    stop_price=stop_price,
                )
                db.add(order)

                trade = Trade(
                    user_id=user_id,
                    binance_order_id=binance_id,
                    symbol=symbol,
                    side=side.upper(),
                    order_type=order_type,
                    status=result.get("status", "OPEN") if result else "OPEN",
                    quantity=quantity,
                    price=price or Decimal("0"),
                    ml_signal=ml_signal,
                    ml_confidence=ml_confidence,
                    is_automated=is_automated,
                )
                db.add(trade)

            order_dict = {
                "id": binance_id,
                "symbol": symbol,
                "side": side,
                "type": order_type,
                "quantity": float(quantity),
                "price": float(price) if price else None,
                "status": "NEW",
                "is_automated": is_automated,
            }
            with self._lock:
                self._open_orders[binance_id] = order_dict

            self._redis.publish_signal(symbol, {
                "event": "ORDER_PLACED", "order": order_dict
            })
            self._notify(order_dict)
            logger.info(f"Order placed: {symbol} {side} {quantity} @ {price}")
            return order_dict

        except Exception as exc:
            # Surface Binance error codes when available (format: "Binance API error -XXXX: msg")
            exc_str = str(exc)
            logger.error(
                f"OrderManager: order placement failed "
                f"[{side} {quantity} {symbol} @ {price}]: {exc_str}"
            )
            return None

    # ── Order management ───────────────────────────────────────────────
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            if self._client:
                self._client.cancel_order(symbol, order_id)
            with self._lock:
                self._open_orders.pop(order_id, None)
            with get_db() as db:
                order = db.execute(select(Order).filter_by(binance_order_id=order_id)).scalar_one_or_none()
                if order:
                    order.status = "CANCELLED"
            return True
        except Exception as exc:
            logger.error(f"Cancel order failed: {exc}")
            return False

    def cancel_all(self, symbol: str) -> None:
        orders = [o for o in self._open_orders.values() if o["symbol"] == symbol]
        for o in orders:
            self.cancel_order(symbol, o["id"])

    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        with self._lock:
            if symbol:
                return [o for o in self._open_orders.values() if o["symbol"] == symbol]
            return list(self._open_orders.values())

    def sync_orders(self) -> None:
        """Reconcile local state with exchange."""
        if not self._client:
            return
        try:
            symbols = {o["symbol"] for o in self._open_orders.values()}
            for sym in symbols:
                live = self._client.get_open_orders(sym)
                live_ids = {str(o["orderId"]) for o in live}
                with self._lock:
                    filled = [
                        oid for oid in list(self._open_orders)
                        if self._open_orders[oid]["symbol"] == sym and oid not in live_ids
                    ]
                for oid in filled:
                    self._mark_filled(oid)
        except Exception as exc:
            logger.error(f"Order sync failed: {exc}")
            try:
                from utils.logger import get_intel_logger
                get_intel_logger().warning("OrderManager", f"Order sync failed – portfolio may be stale: {exc}")
            except Exception:
                pass

    def _mark_filled(self, order_id: str) -> None:
        with self._lock:
            order = self._open_orders.pop(order_id, None)
        if order:
            order["status"] = "FILLED"
            self._notify(order)

    def register_callback(self, fn: Callable) -> None:
        self._callbacks.append(fn)

    def _notify(self, order: dict) -> None:
        for cb in self._callbacks:
            try:
                cb(order)
            except Exception as exc:
                logger.error(f"Order callback error: {exc}")
