"""
PnL Attribution Engine  (Layer 9 – Module 66)
==============================================
Explains returns by strategy, asset, venue, signal family, and execution quality.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger


@dataclass
class TradeAttribution:
    trade_id: str
    symbol: str
    side: str
    strategy_id: str
    signal_family: str           # "momentum", "mean_reversion", "basis", etc.
    venue: str
    entry_price: float
    exit_price: float
    qty: float
    gross_pnl: float
    fees: float
    slippage_cost: float
    net_pnl: float
    hold_minutes: float
    regime: str = "unknown"
    timestamp: float = field(default_factory=time.time)


@dataclass
class AttributionSummary:
    period: str                  # "today", "week", "month"
    total_trades: int
    gross_pnl: float
    fees: float
    slippage_cost: float
    net_pnl: float
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    by_strategy: Dict[str, float] = field(default_factory=dict)
    by_signal: Dict[str, float] = field(default_factory=dict)
    by_venue: Dict[str, float] = field(default_factory=dict)
    by_asset: Dict[str, float] = field(default_factory=dict)
    by_regime: Dict[str, float] = field(default_factory=dict)
    execution_alpha: float = 0.0  # excess return from good execution


class PnLAttributionEngine:
    """
    Records every closed trade with full attribution dimensions.
    Generates performance breakdowns for research and governance.
    """

    def __init__(self):
        self._trades: List[TradeAttribution] = []
        self._lock = threading.RLock()

    def record(self, trade: TradeAttribution) -> None:
        with self._lock:
            self._trades.append(trade)
        logger.debug(
            f"[PnL] {trade.strategy_id} {trade.symbol} net={trade.net_pnl:+.2f}"
        )

    def summarise(self, period_hours: float = 24.0) -> AttributionSummary:
        cutoff = time.time() - period_hours * 3600
        with self._lock:
            trades = [t for t in self._trades if t.timestamp >= cutoff]

        if not trades:
            return AttributionSummary(
                period=f"{period_hours}h", total_trades=0,
                gross_pnl=0, fees=0, slippage_cost=0, net_pnl=0,
                win_rate=0, avg_win=0, avg_loss=0, profit_factor=0,
            )

        gross = sum(t.gross_pnl for t in trades)
        fees = sum(t.fees for t in trades)
        slippage = sum(t.slippage_cost for t in trades)
        net = sum(t.net_pnl for t in trades)

        wins = [t.net_pnl for t in trades if t.net_pnl > 0]
        losses = [t.net_pnl for t in trades if t.net_pnl <= 0]

        by_strategy: Dict[str, float] = {}
        by_signal: Dict[str, float] = {}
        by_venue: Dict[str, float] = {}
        by_asset: Dict[str, float] = {}
        by_regime: Dict[str, float] = {}

        for t in trades:
            by_strategy[t.strategy_id] = by_strategy.get(t.strategy_id, 0) + t.net_pnl
            by_signal[t.signal_family] = by_signal.get(t.signal_family, 0) + t.net_pnl
            by_venue[t.venue] = by_venue.get(t.venue, 0) + t.net_pnl
            by_asset[t.symbol] = by_asset.get(t.symbol, 0) + t.net_pnl
            by_regime[t.regime] = by_regime.get(t.regime, 0) + t.net_pnl

        total_win = sum(wins)
        total_loss = abs(sum(losses))
        profit_factor = total_win / total_loss if total_loss > 0 else float("inf")

        return AttributionSummary(
            period=f"{period_hours}h",
            total_trades=len(trades),
            gross_pnl=round(gross, 2),
            fees=round(fees, 2),
            slippage_cost=round(slippage, 2),
            net_pnl=round(net, 2),
            win_rate=round(len(wins) / len(trades), 3),
            avg_win=round(sum(wins) / len(wins), 2) if wins else 0,
            avg_loss=round(sum(losses) / len(losses), 2) if losses else 0,
            profit_factor=round(profit_factor, 2),
            by_strategy=by_strategy,
            by_signal=by_signal,
            by_venue=by_venue,
            by_asset=by_asset,
            by_regime=by_regime,
        )

    def get_trades(self, strategy_id: Optional[str] = None,
                   hours: float = 24.0) -> List[TradeAttribution]:
        cutoff = time.time() - hours * 3600
        with self._lock:
            trades = [t for t in self._trades if t.timestamp >= cutoff]
        if strategy_id:
            trades = [t for t in trades if t.strategy_id == strategy_id]
        return trades

    def get_total_count(self) -> int:
        with self._lock:
            return len(self._trades)


# Singleton
_pnl: Optional[PnLAttributionEngine] = None


def get_pnl_attribution() -> PnLAttributionEngine:
    global _pnl
    if _pnl is None:
        _pnl = PnLAttributionEngine()
    return _pnl
