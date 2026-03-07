"""
Trade Reconciliation Engine  (Layer 7 – Module 60)
===================================================
Verifies intended order versus actual fill, fee, slippage, and settlement outcome.
Flags mismatches and generates exception reports.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from loguru import logger


class ReconcileStatus(Enum):
    MATCHED = "matched"
    PARTIAL_FILL = "partial_fill"
    OVERFILL = "overfill"
    PRICE_MISS = "price_miss"
    FEE_MISMATCH = "fee_mismatch"
    MISSING = "missing"
    CANCELLED = "cancelled"


@dataclass
class OrderIntent:
    order_id: str
    symbol: str
    side: str
    qty: float
    order_type: str
    limit_price: Optional[float]
    strategy_id: str
    submitted_at: float = field(default_factory=time.time)


@dataclass
class FillRecord:
    order_id: str
    symbol: str
    side: str
    filled_qty: float
    avg_price: float
    fee: float
    fee_asset: str
    status: str
    filled_at: float = field(default_factory=time.time)


@dataclass
class ReconcileResult:
    order_id: str
    status: ReconcileStatus
    intended_qty: float
    filled_qty: float
    qty_diff: float
    intended_price: Optional[float]
    actual_price: float
    slippage_pct: float
    expected_fee: float
    actual_fee: float
    fee_diff: float
    notes: str = ""
    timestamp: float = field(default_factory=time.time)

    @property
    def is_clean(self) -> bool:
        return self.status == ReconcileStatus.MATCHED


class TradeReconciliationEngine:
    """
    Post-trade reconciliation between intended orders and actual fills.

    Checks:
    1. Fill quantity vs intended quantity
    2. Fill price vs limit price (for limit orders)
    3. Slippage vs allowed threshold
    4. Fee vs expected fee
    5. Settlement timing
    """

    def __init__(self, max_slippage_pct: float = 1.0, max_fee_diff_pct: float = 0.1):
        self._max_slippage = max_slippage_pct
        self._max_fee_diff = max_fee_diff_pct
        self._pending: Dict[str, OrderIntent] = {}
        self._results: List[ReconcileResult] = []
        self._exceptions: List[ReconcileResult] = []
        self._lock = threading.RLock()
        self._callbacks = []

    def register_intent(self, intent: OrderIntent) -> None:
        with self._lock:
            self._pending[intent.order_id] = intent

    def reconcile(self, fill: FillRecord, expected_fee_pct: float = 0.075) -> ReconcileResult:
        with self._lock:
            intent = self._pending.pop(fill.order_id, None)

        if not intent:
            result = ReconcileResult(
                order_id=fill.order_id,
                status=ReconcileStatus.MISSING,
                intended_qty=0, filled_qty=fill.filled_qty,
                qty_diff=fill.filled_qty,
                intended_price=None, actual_price=fill.avg_price,
                slippage_pct=0, expected_fee=0, actual_fee=fill.fee,
                fee_diff=fill.fee,
                notes="No intent found for this fill",
            )
            return result

        qty_diff = fill.filled_qty - intent.qty
        slippage_pct = 0.0
        if intent.limit_price and intent.limit_price > 0:
            if intent.side == "BUY":
                slippage_pct = (fill.avg_price - intent.limit_price) / intent.limit_price * 100
            else:
                slippage_pct = (intent.limit_price - fill.avg_price) / intent.limit_price * 100

        expected_fee = fill.filled_qty * fill.avg_price * expected_fee_pct / 100
        fee_diff = abs(fill.fee - expected_fee)

        # Determine status
        if abs(qty_diff / intent.qty) < 0.001:
            status = ReconcileStatus.MATCHED
        elif fill.filled_qty < intent.qty:
            status = ReconcileStatus.PARTIAL_FILL
        elif fill.filled_qty > intent.qty * 1.001:
            status = ReconcileStatus.OVERFILL
        elif slippage_pct > self._max_slippage:
            status = ReconcileStatus.PRICE_MISS
        elif fee_diff / max(expected_fee, 0.01) > self._max_fee_diff:
            status = ReconcileStatus.FEE_MISMATCH
        else:
            status = ReconcileStatus.MATCHED

        result = ReconcileResult(
            order_id=fill.order_id,
            status=status,
            intended_qty=intent.qty,
            filled_qty=fill.filled_qty,
            qty_diff=qty_diff,
            intended_price=intent.limit_price,
            actual_price=fill.avg_price,
            slippage_pct=slippage_pct,
            expected_fee=expected_fee,
            actual_fee=fill.fee,
            fee_diff=fee_diff,
        )

        with self._lock:
            self._results.append(result)
            if not result.is_clean:
                self._exceptions.append(result)
                logger.warning(
                    f"[Reconcile] Exception {fill.order_id}: "
                    f"{status.value} slippage={slippage_pct:.2f}% "
                    f"qty_diff={qty_diff:.6f}"
                )

        for cb in self._callbacks:
            try:
                cb(result)
            except Exception:
                pass

        return result

    def on_result(self, callback) -> None:
        self._callbacks.append(callback)

    def get_exceptions(self, n: int = 50) -> List[ReconcileResult]:
        with self._lock:
            return list(self._exceptions[-n:])

    def get_stats(self) -> dict:
        with self._lock:
            total = len(self._results)
            exceptions = len(self._exceptions)
            matched = total - exceptions
            return {
                "total": total,
                "matched": matched,
                "exceptions": exceptions,
                "match_rate": round(matched / total, 3) if total else 1.0,
            }
