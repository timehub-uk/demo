"""
Execution Algorithm Engine  (Layer 7 – Module 56)
==================================================
Implements TWAP, VWAP, POV, iceberg, sniper, passive maker,
and urgency-based execution strategies.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from loguru import logger


class ExecAlgo(Enum):
    MARKET = "market"
    LIMIT = "limit"
    TWAP = "twap"
    VWAP = "vwap"
    POV = "pov"            # Participation of Volume
    ICEBERG = "iceberg"
    SNIPER = "sniper"
    PASSIVE_MAKER = "passive_maker"


@dataclass
class ExecParams:
    algo: ExecAlgo
    symbol: str
    side: str
    total_qty: float
    # TWAP/VWAP
    duration_minutes: int = 30
    num_slices: int = 10
    # POV
    participation_rate: float = 0.10    # 10% of market volume
    # Iceberg
    show_qty: float = 0.0               # visible quantity
    # Sniper
    limit_price: Optional[float] = None
    # Common
    max_slippage_pct: float = 0.5
    urgency: str = "normal"


@dataclass
class ExecSlice:
    algo: str
    symbol: str
    side: str
    qty: float
    order_type: str
    limit_price: Optional[float]
    scheduled_at: float
    notes: str = ""


class ExecutionAlgoEngine:
    """
    Breaks large orders into child slices based on the chosen algorithm.

    Feature flag: 'auto_trader'
    """

    def __init__(self, order_placer: Optional[Callable] = None):
        self._order_placer = order_placer
        self._active_algos: Dict[str, dict] = {}
        self._lock = threading.RLock()

    def plan(self, params: ExecParams) -> List[ExecSlice]:
        """Generate execution schedule without placing orders."""
        if params.algo == ExecAlgo.MARKET:
            return self._market_slices(params)
        elif params.algo == ExecAlgo.TWAP:
            return self._twap_slices(params)
        elif params.algo == ExecAlgo.VWAP:
            return self._vwap_slices(params)
        elif params.algo == ExecAlgo.ICEBERG:
            return self._iceberg_slices(params)
        elif params.algo == ExecAlgo.SNIPER:
            return self._sniper_slices(params)
        elif params.algo == ExecAlgo.PASSIVE_MAKER:
            return self._passive_maker_slices(params)
        else:
            return self._market_slices(params)

    def execute(self, params: ExecParams, exec_id: str = "") -> str:
        """Generate slices and schedule execution in background thread."""
        slices = self.plan(params)
        exec_id = exec_id or f"exec_{int(time.time())}"
        t = threading.Thread(
            target=self._run_schedule,
            args=(exec_id, slices),
            daemon=True,
        )
        t.start()
        with self._lock:
            self._active_algos[exec_id] = {
                "params": params, "slices": slices, "thread": t,
                "completed": 0, "started_at": time.time()
            }
        logger.info(
            f"[ExecAlgo] {exec_id} started: {params.algo.value} "
            f"{params.side} {params.total_qty} {params.symbol} in {len(slices)} slices"
        )
        return exec_id

    def cancel(self, exec_id: str) -> bool:
        with self._lock:
            algo = self._active_algos.pop(exec_id, None)
        if algo:
            logger.info(f"[ExecAlgo] {exec_id} cancelled")
            return True
        return False

    def get_status(self, exec_id: str) -> Optional[dict]:
        with self._lock:
            return self._active_algos.get(exec_id)

    # ── Slice generators ──────────────────────────────────────────────────────

    def _market_slices(self, p: ExecParams) -> List[ExecSlice]:
        return [ExecSlice(
            algo="market", symbol=p.symbol, side=p.side, qty=p.total_qty,
            order_type="MARKET", limit_price=None, scheduled_at=time.time()
        )]

    def _twap_slices(self, p: ExecParams) -> List[ExecSlice]:
        slice_qty = p.total_qty / p.num_slices
        interval = (p.duration_minutes * 60) / p.num_slices
        now = time.time()
        return [
            ExecSlice(
                algo="twap", symbol=p.symbol, side=p.side, qty=slice_qty,
                order_type="LIMIT", limit_price=None,
                scheduled_at=now + i * interval,
                notes=f"slice {i+1}/{p.num_slices}",
            )
            for i in range(p.num_slices)
        ]

    def _vwap_slices(self, p: ExecParams) -> List[ExecSlice]:
        # Simplified: use U-shape volume distribution
        n = p.num_slices
        weights = [1.0 + 0.5 * (abs(i - n // 2) / (n // 2)) for i in range(n)]
        total_w = sum(weights)
        interval = (p.duration_minutes * 60) / n
        now = time.time()
        return [
            ExecSlice(
                algo="vwap", symbol=p.symbol, side=p.side,
                qty=p.total_qty * (weights[i] / total_w),
                order_type="LIMIT", limit_price=None,
                scheduled_at=now + i * interval,
                notes=f"vwap slice {i+1}/{n} weight={weights[i]:.2f}",
            )
            for i in range(n)
        ]

    def _iceberg_slices(self, p: ExecParams) -> List[ExecSlice]:
        show = p.show_qty or p.total_qty * 0.1
        slices = []
        remaining = p.total_qty
        now = time.time()
        i = 0
        while remaining > 0:
            qty = min(show, remaining)
            slices.append(ExecSlice(
                algo="iceberg", symbol=p.symbol, side=p.side, qty=qty,
                order_type="LIMIT", limit_price=p.limit_price,
                scheduled_at=now + i * 5,
                notes=f"iceberg chunk {i+1}",
            ))
            remaining -= qty
            i += 1
        return slices

    def _sniper_slices(self, p: ExecParams) -> List[ExecSlice]:
        return [ExecSlice(
            algo="sniper", symbol=p.symbol, side=p.side, qty=p.total_qty,
            order_type="LIMIT", limit_price=p.limit_price,
            scheduled_at=time.time(), notes="sniper – wait for dip",
        )]

    def _passive_maker_slices(self, p: ExecParams) -> List[ExecSlice]:
        return [ExecSlice(
            algo="passive_maker", symbol=p.symbol, side=p.side, qty=p.total_qty,
            order_type="LIMIT", limit_price=p.limit_price,
            scheduled_at=time.time(), notes="post-only limit order",
        )]

    # ── Runner ────────────────────────────────────────────────────────────────

    def _run_schedule(self, exec_id: str, slices: List[ExecSlice]) -> None:
        for sl in slices:
            wait = sl.scheduled_at - time.time()
            if wait > 0:
                time.sleep(wait)
            with self._lock:
                if exec_id not in self._active_algos:
                    return  # cancelled
            if self._order_placer:
                try:
                    self._order_placer(sl)
                except Exception as exc:
                    logger.error(f"[ExecAlgo] {exec_id} slice error: {exc}")
            with self._lock:
                if exec_id in self._active_algos:
                    self._active_algos[exec_id]["completed"] += 1
        logger.info(f"[ExecAlgo] {exec_id} completed all slices")
