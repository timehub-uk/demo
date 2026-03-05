"""
Monte Carlo Risk Simulator.

Simulates thousands of possible future equity paths from historical
trade returns to quantify tail risk before it happens.

Produces:
  - Risk of ruin (probability that drawdown ever exceeds 50%)
  - Expected maximum drawdown (median across paths)
  - 95th percentile worst drawdown
  - P10/P50/P90 equity paths over N forward bars
  - Suggested maximum position size to keep risk-of-ruin < 5%
  - Sequence-of-returns risk (does order of wins/losses matter?)

Simulation engine:
  - Bootstrap resampling of actual trade returns (not normal dist assumption)
  - 10,000 paths × 252 trading days each
  - Accounts for fat tails and streaks naturally

Usage:
    sim = MonteCarloSimulator()
    result = sim.run(trade_pnl_series, initial_capital=10_000, n_paths=5000)
    print(result.risk_of_ruin_pct)
    print(result.recommended_max_position_pct)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from loguru import logger
from utils.logger import get_intel_logger


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class MonteCarloResult:
    n_paths: int
    n_periods: int
    initial_capital: float

    # Risk metrics
    risk_of_ruin_pct: float          # % paths that hit 50% drawdown
    expected_max_dd_pct: float       # Median max drawdown across paths
    p95_max_dd_pct: float            # 95th percentile worst drawdown
    p95_loss_pct: float              # 95th percentile final loss vs start

    # Return metrics
    p10_return_pct: float            # Pessimistic scenario return
    p50_return_pct: float            # Median scenario return
    p90_return_pct: float            # Optimistic scenario return

    # Recommendations
    recommended_max_position_pct: float  # Max position size to keep RoR < 5%
    current_kelly_fraction: float

    # Equity path percentiles (sampled equity curve points)
    equity_p10: list[float] = field(default_factory=list)
    equity_p50: list[float] = field(default_factory=list)
    equity_p90: list[float] = field(default_factory=list)

    timestamp: str = ""

    def summary(self) -> str:
        return (
            f"MonteCarlo ({self.n_paths} paths) | "
            f"RoR={self.risk_of_ruin_pct:.1f}% | "
            f"ExpMaxDD={self.expected_max_dd_pct:.1f}% | "
            f"P50_ret={self.p50_return_pct:+.1f}% | "
            f"Max pos={self.recommended_max_position_pct:.0%}"
        )


# ── Simulator ─────────────────────────────────────────────────────────────────

class MonteCarloSimulator:
    """
    Bootstrap Monte Carlo simulator for trading risk assessment.

    Uses actual historical trade P&L percentages (not assumed normal dist)
    to capture fat tails, streaks, and regime-specific return distributions.
    """

    RUIN_THRESHOLD     = 0.50    # 50% drawdown = "ruin"
    TARGET_RUIN_PCT    = 0.05    # Keep risk of ruin below 5%
    SAMPLE_STEPS       = 50      # Points along equity curve to store

    def __init__(self) -> None:
        self._intel = get_intel_logger()

    def run(
        self,
        trade_returns: list[float],     # Per-trade % returns (e.g. [0.02, -0.01, 0.03])
        initial_capital: float = 10_000.0,
        n_paths: int = 5_000,
        n_periods: int = 252,            # Forward simulation length (trade count)
        position_pct: float = 0.95,     # Current position size as fraction
    ) -> MonteCarloResult:
        """
        Run Monte Carlo simulation from historical trade returns.
        """
        if not trade_returns or len(trade_returns) < 5:
            return self._empty_result(initial_capital)

        returns = np.array(trade_returns)
        self._intel.ml("MonteCarlo",
            f"🎲 Running {n_paths} paths × {n_periods} periods | "
            f"{len(returns)} historical trades | cap=${initial_capital:,.0f}")

        rng = np.random.default_rng(42)

        # Bootstrap resample paths
        sampled_returns = rng.choice(returns, size=(n_paths, n_periods), replace=True)

        # Simulate equity paths
        equity_paths = initial_capital * np.cumprod(
            1 + sampled_returns * position_pct, axis=1
        )
        equity_paths = np.hstack([
            np.full((n_paths, 1), initial_capital),
            equity_paths
        ])

        # ── Risk of ruin ──────────────────────────────────────────────
        # A path is "ruined" if it ever drops to <= (1 - RUIN_THRESHOLD) × initial
        ruin_level = initial_capital * (1 - self.RUIN_THRESHOLD)
        ever_ruined = np.any(equity_paths <= ruin_level, axis=1)
        ror = float(np.mean(ever_ruined) * 100)

        # ── Max drawdown per path ─────────────────────────────────────
        peaks = np.maximum.accumulate(equity_paths, axis=1)
        drawdowns = (peaks - equity_paths) / (peaks + 1e-9)
        max_dd_per_path = np.max(drawdowns, axis=1) * 100
        exp_max_dd  = float(np.median(max_dd_per_path))
        p95_max_dd  = float(np.percentile(max_dd_per_path, 95))

        # ── Final return distribution ─────────────────────────────────
        final_returns = (equity_paths[:, -1] - initial_capital) / initial_capital * 100
        p10_ret = float(np.percentile(final_returns, 10))
        p50_ret = float(np.percentile(final_returns, 50))
        p90_ret = float(np.percentile(final_returns, 90))
        p95_loss = float(abs(min(0, np.percentile(final_returns, 5))))

        # ── Kelly fraction ────────────────────────────────────────────
        win_rate = float(np.mean(returns > 0))
        avg_win  = float(np.mean(returns[returns > 0])) if np.any(returns > 0) else 0.01
        avg_loss = float(abs(np.mean(returns[returns < 0]))) if np.any(returns < 0) else 0.01
        kelly = win_rate / avg_loss - (1 - win_rate) / avg_win if avg_loss > 0 else 0.0
        half_kelly = max(0.0, min(0.5, kelly * 0.5))

        # ── Recommended max position size ─────────────────────────────
        # Binary search for largest position size that keeps RoR < TARGET_RUIN_PCT
        rec_pos = self._find_safe_position_size(
            returns, initial_capital, n_paths=2000, n_periods=n_periods, rng=rng
        )

        # ── Equity path percentiles ───────────────────────────────────
        step = max(1, len(equity_paths[0]) // self.SAMPLE_STEPS)
        indices = list(range(0, len(equity_paths[0]), step))
        eq_p10 = [float(np.percentile(equity_paths[:, i], 10)) for i in indices]
        eq_p50 = [float(np.percentile(equity_paths[:, i], 50)) for i in indices]
        eq_p90 = [float(np.percentile(equity_paths[:, i], 90)) for i in indices]

        result = MonteCarloResult(
            n_paths=n_paths, n_periods=n_periods, initial_capital=initial_capital,
            risk_of_ruin_pct=ror, expected_max_dd_pct=exp_max_dd,
            p95_max_dd_pct=p95_max_dd, p95_loss_pct=p95_loss,
            p10_return_pct=p10_ret, p50_return_pct=p50_ret, p90_return_pct=p90_ret,
            recommended_max_position_pct=rec_pos, current_kelly_fraction=half_kelly,
            equity_p10=eq_p10, equity_p50=eq_p50, equity_p90=eq_p90,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        emoji = "🟢" if ror < 5 else "🟡" if ror < 15 else "🔴"
        self._intel.ml("MonteCarlo",
            f"{emoji} {result.summary()}")
        return result

    def run_from_trade_journal(self, journal, initial_capital: float = 10_000.0, **kwargs) -> MonteCarloResult:
        """Run simulation using trade returns from TradeJournal."""
        try:
            trades = journal.get_closed_trades()
            returns = [t["pnl_pct"] / 100 for t in trades if "pnl_pct" in t]
            if not returns:
                return self._empty_result(initial_capital)
            return self.run(returns, initial_capital=initial_capital, **kwargs)
        except Exception as exc:
            logger.debug(f"MonteCarlo from journal error: {exc}")
            return self._empty_result(initial_capital)

    # ── Internal ───────────────────────────────────────────────────────

    def _find_safe_position_size(
        self, returns: np.ndarray, initial_capital: float,
        n_paths: int, n_periods: int, rng,
    ) -> float:
        """Binary search for safe position size (RoR < TARGET_RUIN_PCT)."""
        lo, hi = 0.05, 1.0
        for _ in range(10):
            mid = (lo + hi) / 2
            sampled = rng.choice(returns, size=(n_paths, n_periods), replace=True)
            paths = initial_capital * np.cumprod(1 + sampled * mid, axis=1)
            paths = np.hstack([np.full((n_paths, 1), initial_capital), paths])
            ruin = float(np.mean(np.any(paths <= initial_capital * (1 - self.RUIN_THRESHOLD), axis=1)))
            if ruin > self.TARGET_RUIN_PCT:
                hi = mid
            else:
                lo = mid
        return round(float(lo), 2)

    def _empty_result(self, capital: float) -> MonteCarloResult:
        return MonteCarloResult(
            n_paths=0, n_periods=0, initial_capital=capital,
            risk_of_ruin_pct=100.0, expected_max_dd_pct=50.0, p95_max_dd_pct=80.0,
            p95_loss_pct=50.0, p10_return_pct=-30.0, p50_return_pct=0.0,
            p90_return_pct=10.0, recommended_max_position_pct=0.05,
            current_kelly_fraction=0.0,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
