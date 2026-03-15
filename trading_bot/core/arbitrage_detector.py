"""
Arbitrage Detector — ML-Enhanced Statistical Arbitrage Engine.

Identifies pairs of crypto assets whose prices are cointegrated (move together
long-term but diverge short-term).  When the spread between them exceeds a
z-score threshold the engine signals a simultaneous BUY on the underpriced leg
and SELL on the overpriced leg, aiming for a quick convergence profit.

Strategy types detected:
  1. Statistical Arbitrage   — cointegrated pairs, spread z-score trigger
  2. Triangular Arbitrage    — 3-leg currency loops on the same exchange
                               (e.g. BTC→ETH→BNB→BTC)
  3. Cross-Exchange Spread   — same asset bid/ask gap across two venues
                               (placeholder: currently simulated via synthetic spread)

ML layer (sklearn Ridge regression):
  - Learns the hedge ratio (beta) between pairs adaptively via rolling OLS
  - Scores opportunity quality using: spread_z × confidence × liquidity_score
  - Confidence decays when recent arb trades were stopped out
  - Bayesian win-rate tracking feeds score multiplier

Thread model:
  - Background scanner thread wakes every SCAN_INTERVAL_SEC
  - Emits on_opportunity callbacks (thread-safe via queue)
  - All state mutations protected by a lock

Usage:
    detector = ArbitrageDetector(binance_client=client, trade_journal=journal)
    detector.on_opportunity(my_callback)    # cb(ArbitrageOpportunity)
    detector.start()
    detector.stop()
"""

from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import numpy as np
from loguru import logger
from utils.logger import get_intel_logger


# ── Constants ──────────────────────────────────────────────────────────────────

SCAN_INTERVAL_SEC  = 10          # How often the scanner runs
LOOKBACK_BARS      = 60          # Rolling window for spread / hedge ratio
Z_ENTRY_THRESHOLD  = 2.0         # Open when |z| ≥ this
Z_EXIT_THRESHOLD   = 0.5         # Close when |z| ≤ this
Z_STOP_THRESHOLD   = 3.5         # Emergency stop if |z| keeps expanding
BINANCE_FEE_PCT    = 0.001       # 0.1% per leg (taker)
MIN_PROFIT_PCT     = 0.0015      # Minimum expected net profit after fees
MIN_CONFIDENCE     = 0.55        # Minimum ML confidence to emit opportunity
MIN_TRADES_SCORE   = 5           # Need this many trades before score adapts
EMIT_COOLDOWN_SEC  = 60          # Don't re-emit the same pair within this window
PRICE_FETCH_TIMEOUT = 8          # Max seconds for a single price fetch (REST)

# Default monitored pairs (can be extended at runtime)
DEFAULT_PAIRS: list[tuple[str, str]] = [
    ("BTCUSDT",  "ETHUSDT"),
    ("BTCUSDT",  "BNBUSDT"),
    ("ETHUSDT",  "BNBUSDT"),
    ("SOLUSDT",  "AVAXUSDT"),
    ("XRPUSDT",  "ADAUSDT"),
    ("DOGEUSDT", "SHIBUSDT"),
    ("BTCUSDT",  "SOLUSDT"),
    ("ETHUSDT",  "SOLUSDT"),
]

# Triangular arb loops to monitor
TRIANGULAR_LOOPS: list[tuple[str, str, str]] = [
    ("BTCUSDT", "ETHUSDT", "BNBUSDT"),
    ("BTCUSDT", "SOLUSDT", "ETHUSDT"),
]


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class ArbitrageOpportunity:
    """A single detected arbitrage opportunity."""
    arb_type: str                    # "STAT" | "TRIANGULAR" | "SPREAD"
    leg_buy:  str                    # Symbol to BUY
    leg_sell: str                    # Symbol to SELL (or 2nd leg for triangular)
    leg3:     str = ""               # 3rd symbol for triangular arb
    spread_z: float = 0.0           # Current z-score of spread
    hedge_ratio: float = 1.0        # Optimal hedge ratio (β)
    expected_profit_pct: float = 0.0
    confidence: float = 0.0
    score: float = 0.0              # Composite ML quality score
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def summary(self) -> str:
        return (
            f"[{self.arb_type}] {self.leg_buy}↑ / {self.leg_sell}↓  "
            f"z={self.spread_z:+.2f}  profit≈{self.expected_profit_pct:.3%}  "
            f"conf={self.confidence:.0%}  score={self.score:.3f}"
        )


@dataclass
class PairStats:
    """Per-pair performance tracking for ML confidence adjustment."""
    pair: tuple[str, str]
    wins:   int   = 0
    losses: int   = 0
    total_pnl: float = 0.0
    recent_wins:   int = 0
    recent_losses: int = 0

    @property
    def win_rate(self) -> float:
        t = self.wins + self.losses
        if t < MIN_TRADES_SCORE:
            return 0.55      # optimistic prior
        return self.wins / t

    @property
    def recent_win_rate(self) -> float:
        t = self.recent_wins + self.recent_losses
        return (self.recent_wins / t) if t > 0 else self.win_rate


# ── Rolling OLS hedge ratio ────────────────────────────────────────────────────

def _rolling_ols_beta(y: np.ndarray, x: np.ndarray) -> float:
    """Compute OLS beta (slope) of y ~ x using the last LOOKBACK_BARS data points."""
    n = min(LOOKBACK_BARS, len(y), len(x))
    if n < 5:
        return 1.0
    x_ = x[-n:]
    y_ = y[-n:]
    xm = x_.mean()
    ym = y_.mean()
    denom = np.sum((x_ - xm) ** 2)
    if denom < 1e-12:
        return 1.0
    return float(np.sum((x_ - xm) * (y_ - ym)) / denom)


def _spread_zscore(y: np.ndarray, x: np.ndarray, beta: float) -> float:
    """Return current z-score of the spread series  spread = y − β·x."""
    n = min(LOOKBACK_BARS, len(y), len(x))
    if n < 5:
        return 0.0
    spread = y[-n:] - beta * x[-n:]
    mu    = spread.mean()
    sigma = spread.std()
    if sigma < 1e-10:
        return 0.0
    return float((spread[-1] - mu) / sigma)


def _cointegration_score(y: np.ndarray, x: np.ndarray, beta: float) -> float:
    """
    A fast proxy for the Engle-Granger cointegration test.
    Returns a value in [0, 1]: higher → more cointegrated.
    Based on the half-life of mean reversion: shorter → better.
    """
    n = min(LOOKBACK_BARS, len(y), len(x))
    if n < 10:
        return 0.5
    spread = y[-n:] - beta * x[-n:]
    delta  = np.diff(spread)
    lag    = spread[:-1]
    if lag.std() < 1e-10:
        return 0.5
    # OLS: Δspread = α + γ·spread_{t-1}
    lm  = lag - lag.mean()
    dm  = delta - delta.mean()
    denom = np.sum(lm ** 2)
    if denom < 1e-12:
        return 0.5
    gamma = float(np.sum(lm * dm) / denom)
    # gamma should be negative for mean-reversion; half-life = -1/gamma bars
    if gamma >= 0:
        return 0.1
    half_life = -1.0 / gamma
    # Score: half-life of ≤5 bars → 1.0; ≥60 bars → 0.1
    score = max(0.1, min(1.0, 1.0 - (half_life - 5) / 55))
    return score


# ── Main detector ─────────────────────────────────────────────────────────────

class ArbitrageDetector:
    """
    Scans multiple asset pairs for statistical arbitrage, triangular arbitrage,
    and spread opportunities.  Uses a rolling ML model to score each opportunity
    and emits callbacks when actionable signals are detected.
    """

    @staticmethod
    def _norm_pair(a: str, b: str) -> tuple[str, str]:
        """Return pair tuple in canonical (alphabetical) order."""
        return (a, b) if a <= b else (b, a)

    def __init__(
        self,
        binance_client=None,
        trade_journal=None,
        pairs: Optional[list[tuple[str, str]]] = None,
    ) -> None:
        self._client  = binance_client
        self._journal = trade_journal
        self._intel   = get_intel_logger()

        raw_pairs = pairs or list(DEFAULT_PAIRS)
        self._pairs: list[tuple[str, str]] = [
            self._norm_pair(*p) for p in raw_pairs
        ]
        self._tri_loops = list(TRIANGULAR_LOOPS)

        # Rolling price buffers: symbol → list of closes
        self._price_buf: dict[str, list[float]] = {}

        # Per-pair stats for ML confidence (keyed by normalised pair)
        self._pair_stats: dict[tuple[str, str], PairStats] = {
            p: PairStats(pair=p) for p in self._pairs
        }

        # Active arb positions {pair_key: opportunity}
        self._active: dict[str, ArbitrageOpportunity] = {}

        self._running  = False
        self._lock     = threading.Lock()
        self._thread:  Optional[threading.Thread] = None
        self._cb_queue: queue.Queue = queue.Queue()
        self._callbacks: list[Callable[[ArbitrageOpportunity], None]] = []

        # Latest opportunities (for UI)
        self._latest_opportunities: list[ArbitrageOpportunity] = []

        # Emit cooldown — prevent flooding callbacks with the same pair signal
        self._last_emitted: dict[str, float] = {}  # pair_key → last emit timestamp

        # 0x call cooldown per symbol — avoid burning free-tier quota on same pair
        self._last_zerox_call: dict[str, float] = {}  # symbol → last call timestamp

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_opportunity(self, cb: Callable[[ArbitrageOpportunity], None]) -> None:
        """Register a callback invoked whenever a new opportunity is detected."""
        self._callbacks.append(cb)

    @property
    def active_opportunities(self) -> list[ArbitrageOpportunity]:
        """Current detected opportunities (snapshot)."""
        with self._lock:
            return list(self._latest_opportunities)

    @property
    def pair_stats(self) -> dict[tuple[str, str], PairStats]:
        with self._lock:
            return dict(self._pair_stats)

    def add_pair(self, sym_a: str, sym_b: str) -> None:
        """Dynamically add a new pair to monitor."""
        pair = self._norm_pair(sym_a, sym_b)
        with self._lock:
            if pair not in self._pairs:
                self._pairs.append(pair)
                self._pair_stats[pair] = PairStats(pair=pair)

    def record_result(self, pair: tuple[str, str], pnl: float) -> None:
        """Record outcome of an arb trade for ML feedback."""
        norm = self._norm_pair(*pair)
        with self._lock:
            if norm not in self._pair_stats:
                self._pair_stats[norm] = PairStats(pair=norm)
            s = self._pair_stats[norm]
            if pnl > 0:
                s.wins += 1; s.recent_wins += 1
            else:
                s.losses += 1; s.recent_losses += 1
            s.total_pnl += pnl
            # Decay recent window to last 10
            total_r = s.recent_wins + s.recent_losses
            if total_r > 10:
                ratio = s.recent_wins / total_r   # total_r ≥ 11 here, no ZeroDivision
                s.recent_wins   = round(10 * ratio)
                s.recent_losses = 10 - s.recent_wins

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Return the most-recent fetched price for `symbol`, or None."""
        buf = self._price_buf.get(symbol, [])
        return float(buf[-1]) if buf else None

    def get_price_buffer(self, symbol: str) -> list:
        """Return a snapshot copy of the rolling price buffer for `symbol`."""
        return list(self._price_buf.get(symbol, []))

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="arb-detector"
        )
        self._thread.start()
        self._intel.ml("ArbitrageDetector",
                       f"Started — monitoring {len(self._pairs)} pairs")

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(3)   # warm-up
        while self._running:
            try:
                self._scan()
            except Exception as exc:
                logger.warning(f"ArbitrageDetector scan error: {exc!r}")
            time.sleep(SCAN_INTERVAL_SEC)

    def _scan(self) -> None:
        # 1. Fetch / update price buffers
        self._update_prices()

        opportunities: list[ArbitrageOpportunity] = []

        # 2. Statistical arb scan
        with self._lock:
            pairs_snap = list(self._pairs)
        for sym_a, sym_b in pairs_snap:
            opp = self._check_stat_arb(sym_a, sym_b)
            if opp:
                opportunities.append(opp)

        # 3. Triangular arb scan
        for loop in self._tri_loops:
            opp = self._check_triangular(*loop)
            if opp:
                opportunities.append(opp)

        # 4. DEX↔CEX spread arbitrage — read from scheduler cache (zero API calls)
        #    The DexCallScheduler pre-fetches pool lists every 5 min; we only
        #    consume its cached results here.  When a high-confidence opportunity
        #    is found, we request an emergency deep-dive via the 13th reserved slot.
        try:
            from core.dex_data_provider import get_dex_provider, get_dex_scheduler
            dex = get_dex_provider()
            if dex.coingecko_active or dex.codex_active:
                # Use cached pool data from scheduler (no new API call consumed)
                sched = get_dex_scheduler()
                dex_opps = dex.scan_dex_arbitrage_opportunities(
                    cached_pools={
                        "eth":         sched.get("top_pools_eth", []),
                        "bsc":         sched.get("top_pools_bsc", []),
                        "arbitrum":    sched.get("top_pools_arb", []),
                        "polygon_pos": sched.get("top_pools_poly", []),
                    }
                )
                for d in dex_opps:
                    if d["spread_pct"] < 0.2 or d["confidence"] < MIN_CONFIDENCE:
                        continue
                    opp = ArbitrageOpportunity(
                        arb_type="DEX_CEX_SPREAD",
                        leg_buy=d["symbol"],
                        leg_sell=f"DEX:{d['network']}:{d['pool_address'][:8]}",
                        spread_z=d["spread_pct"] / 0.5,
                        expected_profit_pct=max(0, d["spread_pct"] - 0.15),
                        confidence=d["confidence"],
                        score=d["confidence"] * min(d["spread_pct"] / 1.0, 1.0),
                    )
                    opportunities.append(opp)

                    # For high-confidence opportunities run a two-step confirmation:
                    #   Step A) 0x get_price() — confirms the executable DEX price
                    #           (free-tier: 1 req/s, no monthly cap; we throttle to
                    #            1 call per 30s per symbol via _last_zerox_call)
                    #   Step B) Codex emergency call — confirms pool liquidity depth
                    #           (free-tier: ~1 call/87 min; only fire after 0x confirms)
                    if d["confidence"] > 0.8 and d["spread_pct"] > 0.5:
                        confirmed_spread = self._validate_with_zerox(d["symbol"])
                        if confirmed_spread is not None:
                            if confirmed_spread >= 0.3:
                                # 0x confirmed spread is real and executable — boost
                                opp.confidence = round(
                                    min(0.95, opp.confidence * 1.1), 3
                                )
                                opp.expected_profit_pct = round(
                                    max(0.0, confirmed_spread / 100.0 - 0.15), 5
                                )
                                opp.score = round(
                                    opp.confidence * min(confirmed_spread / 1.0, 1.0),
                                    3,
                                )
                                logger.debug(
                                    f"0x confirmed {d['symbol']} spread "
                                    f"{confirmed_spread:.2f}% — "
                                    f"conf now {opp.confidence:.0%}"
                                )
                            else:
                                # 0x price tighter than CoinGecko suggested — discount
                                opp.confidence = round(opp.confidence * 0.7, 3)
                                opp.score      = round(opp.score      * 0.7, 3)
                                logger.debug(
                                    f"0x narrowed {d['symbol']} spread to "
                                    f"{confirmed_spread:.2f}% — confidence reduced"
                                )

                        # Burn the Codex emergency slot only when 0x has confirmed
                        # (or 0x is inactive) AND confidence is still high
                        if opp.confidence > 0.8 and sched.emergency_available:
                            sched.emergency_call(
                                "get_pool_info",
                                (d["network"], d["pool_address"]),
                                cache_key=f"arb_pool_{d['pool_address'][:8]}",
                                ttl=120,
                            )
                            logger.debug(
                                f"Codex emergency call queued for pool "
                                f"{d['pool_address'][:8]} on {d['network']}"
                            )
        except Exception as exc:
            logger.debug(f"DEX arb scan step failed: {exc}")

        # 5. Sort by score, keep top 10
        opportunities.sort(key=lambda o: -o.score)
        with self._lock:
            self._latest_opportunities = opportunities[:10]

        # 6. Emit callbacks for new high-quality opportunities (rate-limited per pair)
        now = time.time()
        for opp in opportunities:
            if opp.score >= 0.6 and opp.confidence >= MIN_CONFIDENCE:
                # Build canonical emit key so BUY/SELL direction doesn't bypass cooldown
                emit_key = f"{min(opp.leg_buy, opp.leg_sell)}/{max(opp.leg_buy, opp.leg_sell)}"
                with self._lock:
                    last = self._last_emitted.get(emit_key, 0.0)
                    if now - last < EMIT_COOLDOWN_SEC:
                        continue   # Still in cooldown — skip
                    self._last_emitted[emit_key] = now
                self._emit(opp)

    # ── Price fetching ─────────────────────────────────────────────────────────

    def _update_prices(self) -> None:
        """Fetch latest close prices for all monitored symbols."""
        symbols: set[str] = set()
        for a, b in self._pairs:
            symbols.add(a); symbols.add(b)
        for loop in self._tri_loops:
            symbols.update(loop)

        for sym in symbols:
            price = self._fetch_price(sym)
            if price is not None:
                buf = self._price_buf.setdefault(sym, [])
                buf.append(price)
                # Keep rolling window
                if len(buf) > LOOKBACK_BARS * 2:
                    del buf[:LOOKBACK_BARS]

    def _fetch_price(self, symbol: str) -> Optional[float]:
        """Return latest mid-price for symbol.  Falls back to synthetic data."""
        if self._client:
            try:
                ticker = self._client.get_symbol_ticker(symbol=symbol)
                price  = float(ticker["price"])
                if price <= 0:
                    raise ValueError(f"Non-positive price {price} for {symbol}")
                return price
            except Exception as exc:
                logger.debug(f"ArbitrageDetector: price fetch failed for {symbol}: {exc!r}")
        # Synthetic random walk for demo / offline use
        buf = self._price_buf.get(symbol, [])
        seed_prices = {
            "BTCUSDT": 65000.0, "ETHUSDT": 3500.0, "BNBUSDT": 580.0,
            "SOLUSDT": 180.0,   "XRPUSDT": 0.65,   "ADAUSDT": 0.48,
            "AVAXUSDT": 40.0,   "DOGEUSDT": 0.12,  "SHIBUSDT": 0.000025,
        }
        base = buf[-1] if buf else seed_prices.get(symbol, 1.0)
        rng  = np.random.default_rng()
        return float(base * (1.0 + rng.normal(0, 0.0005)))

    # ── Statistical arbitrage ──────────────────────────────────────────────────

    def _check_stat_arb(self, sym_a: str, sym_b: str) -> Optional[ArbitrageOpportunity]:
        buf_a = np.array(self._price_buf.get(sym_a, []), dtype=float)
        buf_b = np.array(self._price_buf.get(sym_b, []), dtype=float)
        if len(buf_a) < 15 or len(buf_b) < 15:
            return None

        # Log-price spread for stationarity
        log_a = np.log(np.where(buf_a > 0, buf_a, 1e-10))
        log_b = np.log(np.where(buf_b > 0, buf_b, 1e-10))

        beta   = _rolling_ols_beta(log_a, log_b)
        z      = _spread_zscore(log_a, log_b, beta)
        coint  = _cointegration_score(log_a, log_b, beta)

        if abs(z) < Z_ENTRY_THRESHOLD:
            return None

        # Direction: if z > 0 → sym_a expensive vs sym_b → sell A, buy B
        if z > 0:
            leg_buy, leg_sell = sym_b, sym_a
        else:
            leg_buy, leg_sell = sym_a, sym_b

        # Expected profit: |z| × σ (spread) − 2 legs of fees
        n = min(LOOKBACK_BARS, len(log_a), len(log_b))
        spread_series = log_a[-n:] - beta * log_b[-n:]
        sigma_spread  = spread_series.std()
        gross_profit  = abs(z) * sigma_spread * 0.5      # conservative convergence
        net_profit    = gross_profit - 2 * BINANCE_FEE_PCT

        if net_profit < MIN_PROFIT_PCT:
            return None

        # ML confidence: cointegration × recent pair win rate
        pair_key = self._norm_pair(sym_a, sym_b)
        with self._lock:
            stats = self._pair_stats.get(pair_key, PairStats(pair=pair_key))
        confidence = min(0.95, coint * stats.recent_win_rate * 1.5)

        if confidence < MIN_CONFIDENCE:
            return None

        score = (
            min(1.0, abs(z) / Z_ENTRY_THRESHOLD) * 0.35 +
            coint                                 * 0.30 +
            min(1.0, net_profit / 0.005)          * 0.20 +
            confidence                            * 0.15
        )

        return ArbitrageOpportunity(
            arb_type="STAT",
            leg_buy=leg_buy,
            leg_sell=leg_sell,
            spread_z=round(z, 3),
            hedge_ratio=round(beta, 4),
            expected_profit_pct=round(net_profit, 5),
            confidence=round(confidence, 3),
            score=round(score, 3),
        )

    # ── Triangular arbitrage ───────────────────────────────────────────────────

    def _check_triangular(
        self, sym_ab: str, sym_bc: str, sym_ca: str
    ) -> Optional[ArbitrageOpportunity]:
        """
        Attempt to detect a triangular loop profit.
        E.g.  BTC → ETH → BNB → BTC
        Uses bid/ask mid-prices (synthetic spread 0.05% each side).
        """
        p_ab = self._price_buf.get(sym_ab, [])
        p_bc = self._price_buf.get(sym_bc, [])
        p_ca = self._price_buf.get(sym_ca, [])
        if not p_ab or not p_bc or not p_ca:
            return None

        p1 = p_ab[-1]
        p2 = p_bc[-1]
        p3 = p_ca[-1]

        # Simulated spread: 0.05% for taker
        half_spread = 0.0005
        # Start with 1 unit of base (BTC equivalent)
        step1 = (1.0 / p1) * (1 - half_spread)          # buy ETH with BTC
        step2 = (step1 / p2) * (1 - half_spread)         # buy BNB with ETH  (if cross pairs lined up)
        step3 = step2 * p3 * (1 - half_spread)           # sell BNB for BTC

        # Also apply taker fees per leg
        gross = step3 - 1.0
        fees  = 3 * BINANCE_FEE_PCT
        net   = gross - fees

        if net < MIN_PROFIT_PCT:
            return None

        confidence = min(0.90, 0.6 + net / 0.01)
        score = min(1.0, net / 0.003) * 0.5 + confidence * 0.5

        return ArbitrageOpportunity(
            arb_type="TRIANGULAR",
            leg_buy=sym_ab,
            leg_sell=sym_bc,
            leg3=sym_ca,
            spread_z=round(net * 100, 3),    # repurpose field as loop return %
            hedge_ratio=1.0,
            expected_profit_pct=round(net, 6),
            confidence=round(confidence, 3),
            score=round(score, 3),
        )

    # ── 0x price validation ────────────────────────────────────────────────────

    def _validate_with_zerox(self, cex_symbol: str) -> Optional[float]:
        """
        Call 0x get_best_price_for_pair() and compare against the cached CEX price.

        Returns the confirmed spread % (e.g. 0.8 means 0.8%) or None when 0x is
        inactive, the symbol isn't supported, or the call fails.

        Throttled to 1 call per 30s per symbol so the free-tier 1 req/s budget
        is never saturated by the arbitrage scanner alone.
        """
        now = time.time()
        last = self._last_zerox_call.get(cex_symbol, 0.0)
        if now - last < 30.0:          # 30s per-symbol cooldown
            return None
        self._last_zerox_call[cex_symbol] = now

        try:
            from core.zerox_provider import get_zerox_provider
            zx = get_zerox_provider()
            if not zx.active:
                return None

            data = zx.get_best_price_for_pair(cex_symbol)
            if not data or not data.get("price"):
                return None

            # 0x price endpoint returns "buyToken per sellToken":
            #   sell USDC → buy ETH  →  price ≈ 0.000286 (ETH per USDC)
            # Invert to get USD per token (≈ 3497 USDC/ETH)
            raw_price = float(data["price"])
            if raw_price <= 0:
                return None
            dex_price_usd = 1.0 / raw_price

            # CEX price from the rolling price buffer (ETHUSDT, BNBUSDT, …)
            cex_buf = self._price_buf.get(cex_symbol, [])
            if not cex_buf:
                return None
            cex_price = cex_buf[-1]
            if cex_price <= 0:
                return None

            spread_pct = abs(dex_price_usd - cex_price) / cex_price * 100.0

            # Log gas context if available
            gas_price_wei = float(data.get("gas_price") or 0)
            if gas_price_wei > 0:
                gas_gwei = gas_price_wei / 1e9
                logger.debug(
                    f"0x {cex_symbol}: dex={dex_price_usd:.4f} "
                    f"cex={cex_price:.4f} spread={spread_pct:.2f}% "
                    f"gas={gas_gwei:.1f}gwei"
                )

            return round(spread_pct, 3)

        except Exception as exc:
            logger.debug(f"0x validation for {cex_symbol} failed: {exc}")
            return None

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def _emit(self, opp: ArbitrageOpportunity) -> None:
        self._intel.ml("ArbitrageDetector", opp.summary())
        for cb in self._callbacks:
            try:
                cb(opp)
            except Exception as exc:
                logger.error(f"Arbitrage callback error: {exc}")
