"""
ML Portfolio Optimiser.

Combines Markowitz mean-variance optimisation with Kelly criterion
per-symbol sizing to produce optimal capital allocations.

Features:
  - Efficient frontier calculation
  - Max Sharpe portfolio
  - Risk-parity portfolio
  - Kelly criterion position sizes
  - Correlation matrix with concentration limits
  - Per-token ML performance weighting
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd

from loguru import logger
from utils.logger import get_intel_logger


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class AllocationResult:
    weights: dict[str, float]          # symbol → weight (sums to 1)
    kelly_sizes: dict[str, float]      # symbol → fraction of capital
    expected_return_pct: float = 0.0
    expected_volatility_pct: float = 0.0
    sharpe_ratio: float = 0.0
    method: str = "max_sharpe"
    rebalance_needed: bool = False
    notes: list[str] = field(default_factory=list)

    def position_usdt(self, total_capital: float) -> dict[str, float]:
        """Convert weights to USDT amounts."""
        return {sym: total_capital * w for sym, w in self.weights.items()}


# ── Optimiser ─────────────────────────────────────────────────────────────────

class PortfolioOptimiser:
    """
    Computes optimal portfolio weights and position sizes.

    Usage:
        opt = PortfolioOptimiser()
        result = opt.optimise(symbols, returns_df, method="max_sharpe")
        sizes = result.position_usdt(portfolio_value)
    """

    MAX_WEIGHT_PER_SYMBOL   = 0.30    # Max 30% in any single token
    MIN_WEIGHT_PER_SYMBOL   = 0.02    # Min 2% if included
    MAX_CORRELATION_ALLOWED = 0.85    # Drop correlated duplicates above this
    RISK_FREE_RATE = 0.05 / 252       # Daily risk-free rate (5% annual)
    N_SIMULATIONS = 2000              # Monte Carlo simulations for frontier

    def __init__(self) -> None:
        self._intel = get_intel_logger()

    def optimise(
        self,
        symbols: list[str],
        returns_df: Optional[pd.DataFrame] = None,
        method: str = "max_sharpe",     # max_sharpe | risk_parity | equal_weight | kelly
        token_win_rates: Optional[dict[str, float]] = None,
    ) -> AllocationResult:
        """
        Main entry point.
        If returns_df is None, loads from CSV store automatically.
        """
        if returns_df is None:
            returns_df = self._load_returns(symbols)

        if returns_df.empty or len(returns_df.columns) < 2:
            return self._equal_weight(symbols)

        # Remove highly-correlated pairs
        clean_syms, corr_notes = self._filter_correlated(returns_df)
        returns_df = returns_df[clean_syms]

        try:
            if method == "max_sharpe":
                result = self._max_sharpe(returns_df)
            elif method == "risk_parity":
                result = self._risk_parity(returns_df)
            elif method == "kelly":
                result = self._kelly_weights(returns_df, token_win_rates or {})
            else:
                result = self._equal_weight(clean_syms)

            result.notes += corr_notes
            self._intel.ml("PortfolioOptimiser",
                f"✅ Optimised {len(result.weights)} symbols | method={method} | "
                f"E[ret]={result.expected_return_pct:.1f}% | vol={result.expected_volatility_pct:.1f}% | "
                f"Sharpe={result.sharpe_ratio:.2f}")
            return result

        except Exception as exc:
            logger.warning(f"PortfolioOptimiser error: {exc}")
            return self._equal_weight(clean_syms)

    def kelly_fraction(self, win_rate: float, avg_win: float, avg_loss: float,
                        max_fraction: float = 0.25) -> float:
        """
        Full Kelly fraction = (win_rate/avg_loss - loss_rate/avg_win) / 1
        Half Kelly is used in practice.
        """
        if avg_loss <= 0 or avg_win <= 0:
            return 0.0
        loss_rate = 1 - win_rate
        kelly = win_rate / avg_loss - loss_rate / avg_win
        half_kelly = kelly * 0.5
        return max(0.0, min(max_fraction, half_kelly))

    def get_rebalance_orders(
        self,
        current_positions: dict[str, float],     # symbol → current USDT value
        target_weights: dict[str, float],         # symbol → target weight
        total_capital: float,
        threshold_pct: float = 0.03,             # Only rebalance if drift > 3%
    ) -> list[dict]:
        """
        Returns a list of rebalance orders: {"symbol", "action", "usdt_amount"}.
        """
        orders = []
        for sym, target_w in target_weights.items():
            current_val = current_positions.get(sym, 0.0)
            current_w = current_val / (total_capital + 1e-9)
            drift = target_w - current_w
            if abs(drift) > threshold_pct:
                action = "BUY" if drift > 0 else "SELL"
                usdt_amount = abs(drift) * total_capital
                orders.append({
                    "symbol": sym, "action": action,
                    "usdt_amount": usdt_amount,
                    "current_pct": current_w * 100,
                    "target_pct": target_w * 100,
                    "drift_pct": drift * 100,
                })
        return sorted(orders, key=lambda x: abs(x["drift_pct"]), reverse=True)

    # ── Optimisation methods ───────────────────────────────────────────

    def _max_sharpe(self, returns_df: pd.DataFrame) -> AllocationResult:
        """Monte Carlo simulation to find max Sharpe portfolio."""
        mu   = returns_df.mean().values
        cov  = returns_df.cov().values
        n    = len(mu)
        syms = list(returns_df.columns)

        best_sharpe = -np.inf
        best_weights = np.ones(n) / n

        rng = np.random.default_rng(42)
        for _ in range(self.N_SIMULATIONS):
            w = rng.random(n)
            w = w / w.sum()
            # Apply max weight constraint
            w = np.clip(w, self.MIN_WEIGHT_PER_SYMBOL, self.MAX_WEIGHT_PER_SYMBOL)
            w = w / w.sum()

            port_ret = np.dot(w, mu) * 252
            port_vol = np.sqrt(w @ cov @ w) * np.sqrt(252)
            sharpe   = (port_ret - self.RISK_FREE_RATE * 252) / (port_vol + 1e-9)
            if sharpe > best_sharpe:
                best_sharpe  = sharpe
                best_weights = w

        weights = {s: float(best_weights[i]) for i, s in enumerate(syms)}
        port_ret = float(np.dot(best_weights, mu) * 252 * 100)
        port_vol = float(np.sqrt(best_weights @ cov @ best_weights) * np.sqrt(252) * 100)

        return AllocationResult(
            weights=weights, kelly_sizes=weights,
            expected_return_pct=port_ret, expected_volatility_pct=port_vol,
            sharpe_ratio=best_sharpe, method="max_sharpe",
        )

    def _risk_parity(self, returns_df: pd.DataFrame) -> AllocationResult:
        """Risk parity: each asset contributes equal risk."""
        cov  = returns_df.cov().values
        syms = list(returns_df.columns)
        n    = len(syms)
        vols = np.sqrt(np.diag(cov))
        inv_vols = 1.0 / (vols + 1e-9)
        w = inv_vols / inv_vols.sum()
        w = np.clip(w, self.MIN_WEIGHT_PER_SYMBOL, self.MAX_WEIGHT_PER_SYMBOL)
        w = w / w.sum()

        mu       = returns_df.mean().values
        port_ret = float(np.dot(w, mu) * 252 * 100)
        port_vol = float(np.sqrt(w @ cov @ w) * np.sqrt(252) * 100)
        sharpe   = (port_ret / 100 - self.RISK_FREE_RATE * 252) / (port_vol / 100 + 1e-9)

        weights = {s: float(w[i]) for i, s in enumerate(syms)}
        return AllocationResult(
            weights=weights, kelly_sizes=weights,
            expected_return_pct=port_ret, expected_volatility_pct=port_vol,
            sharpe_ratio=float(sharpe), method="risk_parity",
        )

    def _kelly_weights(self, returns_df: pd.DataFrame,
                       win_rates: dict[str, float]) -> AllocationResult:
        """Kelly criterion with win-rate weighting per symbol."""
        syms = list(returns_df.columns)
        kelly = {}
        for sym in syms:
            wr = win_rates.get(sym, 0.5)
            pos_rets = returns_df[sym][returns_df[sym] > 0]
            neg_rets = returns_df[sym][returns_df[sym] < 0]
            avg_win  = float(pos_rets.mean()) if len(pos_rets) > 0 else 0.01
            avg_loss = float(abs(neg_rets.mean())) if len(neg_rets) > 0 else 0.01
            kelly[sym] = self.kelly_fraction(wr, avg_win, avg_loss)

        total = sum(kelly.values()) or 1.0
        weights = {s: min(self.MAX_WEIGHT_PER_SYMBOL, v / total) for s, v in kelly.items()}
        w_total = sum(weights.values()) or 1.0
        weights = {s: v / w_total for s, v in weights.items()}

        mu  = returns_df.mean().values
        cov = returns_df.cov().values
        w   = np.array([weights[s] for s in syms])
        port_ret = float(np.dot(w, mu) * 252 * 100)
        port_vol = float(np.sqrt(w @ cov @ w) * np.sqrt(252) * 100)
        sharpe   = (port_ret / 100 - self.RISK_FREE_RATE * 252) / (port_vol / 100 + 1e-9)

        return AllocationResult(
            weights=weights, kelly_sizes=kelly,
            expected_return_pct=port_ret, expected_volatility_pct=port_vol,
            sharpe_ratio=float(sharpe), method="kelly",
        )

    def _equal_weight(self, symbols: list[str]) -> AllocationResult:
        w = 1.0 / max(len(symbols), 1)
        weights = {s: w for s in symbols}
        return AllocationResult(
            weights=weights, kelly_sizes=weights,
            method="equal_weight",
            notes=["Insufficient data – using equal weight allocation"],
        )

    def _filter_correlated(self, returns_df: pd.DataFrame) -> tuple[list[str], list[str]]:
        """Remove symbols that are too correlated with each other."""
        syms = list(returns_df.columns)
        notes = []
        if len(syms) < 2:
            return syms, notes

        corr = returns_df.corr().abs()
        drop = set()
        for i in range(len(syms)):
            for j in range(i + 1, len(syms)):
                if corr.iloc[i, j] > self.MAX_CORRELATION_ALLOWED:
                    # Drop the less-liquid symbol (higher column index = less prominent)
                    drop.add(syms[j])
                    notes.append(f"Removed {syms[j]} (corr={corr.iloc[i,j]:.2f} with {syms[i]})")

        clean = [s for s in syms if s not in drop]
        return clean if len(clean) >= 2 else syms[:max(2, len(syms))], notes

    # ── Data loading ───────────────────────────────────────────────────

    def _load_returns(self, symbols: list[str], interval: str = "1d") -> pd.DataFrame:
        """Load daily close prices and compute log returns."""
        frames = {}
        for sym in symbols[:20]:  # Limit to 20 for performance
            try:
                from ml.data_collector import DataCollector
                df = DataCollector.load_dataframe(sym, interval, limit=365)
                if not df.empty and "close" in df.columns:
                    close = df["close"].astype(float)
                    rets  = np.log(close / close.shift(1)).dropna()
                    frames[sym] = rets
            except Exception:
                continue

        if not frames:
            return pd.DataFrame()

        returns_df = pd.DataFrame(frames).dropna()
        return returns_df
