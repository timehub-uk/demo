"""
Exposure Engine  (Layer 6 – Module 49)
========================================
Measures directional, sector, chain, exchange, and factor exposure
across the entire portfolio in real time.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from loguru import logger


@dataclass
class ExposureSnapshot:
    total_long_usd: float = 0.0
    total_short_usd: float = 0.0
    net_usd: float = 0.0
    gross_usd: float = 0.0
    net_pct_nav: float = 0.0         # net as % of NAV
    gross_pct_nav: float = 0.0
    by_asset: Dict[str, float] = field(default_factory=dict)
    by_sector: Dict[str, float] = field(default_factory=dict)
    by_chain: Dict[str, float] = field(default_factory=dict)
    by_exchange: Dict[str, float] = field(default_factory=dict)
    by_strategy: Dict[str, float] = field(default_factory=dict)
    concentration_top5_pct: float = 0.0


# Sector classification (simplified)
_SECTOR_MAP = {
    "BTC": "store_of_value",
    "ETH": "smart_contract_platform",
    "SOL": "smart_contract_platform",
    "BNB": "exchange_token",
    "ADA": "smart_contract_platform",
    "AVAX": "smart_contract_platform",
    "MATIC": "l2_scaling",
    "LINK": "oracle",
    "UNI": "dex",
    "AAVE": "defi_lending",
    "CRV": "defi_amm",
    "MKR": "defi_lending",
}


class ExposureEngine:
    """
    Real-time exposure calculator for the consolidated portfolio.

    Inputs: positions dict { symbol → (side, notional_usd, exchange, chain, strategy_id) }
    """

    def __init__(self, nav: float = 100_000.0):
        self._nav = nav
        self._positions: Dict[str, Tuple[str, float, str, str, str]] = {}
        self._lock = threading.RLock()
        self._limits: Dict[str, float] = {
            "max_single_pct": 20.0,    # max % NAV in single asset
            "max_sector_pct": 40.0,    # max % NAV in single sector
            "max_exchange_pct": 60.0,  # max % NAV on single exchange
            "max_gross_pct": 150.0,    # max gross exposure % NAV
        }
        self._breach_callbacks = []

    # ── Position updates ──────────────────────────────────────────────────────

    def update_nav(self, nav: float) -> None:
        with self._lock:
            self._nav = nav

    def set_position(self, symbol: str, side: str, notional_usd: float,
                     exchange: str = "binance", chain: str = "cex",
                     strategy_id: str = "default") -> None:
        with self._lock:
            if notional_usd == 0.0:
                self._positions.pop(symbol, None)
            else:
                self._positions[symbol] = (side, notional_usd, exchange, chain, strategy_id)

    def clear_positions(self) -> None:
        with self._lock:
            self._positions.clear()

    def configure(self, **kwargs) -> None:
        with self._lock:
            self._limits.update(kwargs)

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> ExposureSnapshot:
        with self._lock:
            positions = dict(self._positions)
            nav = self._nav

        snap = ExposureSnapshot()

        for sym, (side, notional, exchange, chain, strategy) in positions.items():
            signed = notional if side == "long" else -notional
            snap.by_asset[sym] = snap.by_asset.get(sym, 0.0) + signed

            # Sector
            base = sym.replace("USDT", "").replace("BUSD", "")
            sector = _SECTOR_MAP.get(base, "other")
            snap.by_sector[sector] = snap.by_sector.get(sector, 0.0) + abs(notional)

            # Chain / Exchange / Strategy
            snap.by_chain[chain] = snap.by_chain.get(chain, 0.0) + abs(notional)
            snap.by_exchange[exchange] = snap.by_exchange.get(exchange, 0.0) + abs(notional)
            snap.by_strategy[strategy] = snap.by_strategy.get(strategy, 0.0) + signed

            if side == "long":
                snap.total_long_usd += notional
            else:
                snap.total_short_usd += notional

        snap.net_usd = snap.total_long_usd - snap.total_short_usd
        snap.gross_usd = snap.total_long_usd + snap.total_short_usd
        if nav > 0:
            snap.net_pct_nav = snap.net_usd / nav * 100
            snap.gross_pct_nav = snap.gross_usd / nav * 100

        # Concentration
        if snap.by_asset:
            sorted_abs = sorted(abs(v) for v in snap.by_asset.values())
            top5 = sum(sorted_abs[-5:])
            snap.concentration_top5_pct = top5 / nav * 100 if nav else 0.0

        self._check_limits(snap)
        return snap

    def on_breach(self, callback) -> None:
        self._breach_callbacks.append(callback)

    def _check_limits(self, snap: ExposureSnapshot) -> None:
        nav = self._nav
        if nav <= 0:
            return
        for sym, val in snap.by_asset.items():
            if abs(val) / nav * 100 > self._limits["max_single_pct"]:
                self._fire_breach("single_asset", sym, abs(val) / nav * 100)
        for sector, val in snap.by_sector.items():
            if val / nav * 100 > self._limits["max_sector_pct"]:
                self._fire_breach("sector", sector, val / nav * 100)
        for exchange, val in snap.by_exchange.items():
            if val / nav * 100 > self._limits["max_exchange_pct"]:
                self._fire_breach("exchange", exchange, val / nav * 100)
        if snap.gross_pct_nav > self._limits["max_gross_pct"]:
            self._fire_breach("gross_exposure", "portfolio", snap.gross_pct_nav)

    def _fire_breach(self, breach_type: str, entity: str, pct: float) -> None:
        logger.warning(f"[ExposureEngine] Breach: {breach_type} {entity} = {pct:.1f}% NAV")
        for cb in self._breach_callbacks:
            try:
                cb(breach_type, entity, pct)
            except Exception:
                pass
