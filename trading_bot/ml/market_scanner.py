"""
Market Scanner – Full ML Stack Evaluation of All Tradable Pairs.

Scans every USDT trading pair on Binance, runs the complete intelligence
stack on each one, and produces two ranked top-5 lists:

  TOP 5 PROFIT CANDIDATES
    Ranked by: ensemble confidence × momentum × MTF agreement × regime mult
    These have the strongest combined signal with all models agreeing.

  TOP 5 RISK:REWARD CHAMPIONS
    Ranked by: expected value = (RR_ratio × win_rate) - (1 - win_rate)
    These offer the best asymmetric payout relative to the stop distance.

Then a FINAL RECOMMENDATION is made – the single trade with the highest
combined score, ready for the AutoTrader to execute.

Scan cycle:
  1. Fetch all USDT pairs with 24h volume > $5M USD
  2. Pre-filter: exclude stablecoins, leveraged tokens, pairs already held
  3. Parallel score (ThreadPoolExecutor) – 8 workers by default
  4. Run ensemble + MTF + council on each surviving pair
  5. Compute profit score and R:R score independently
  6. Merge, rank, select Final Recommendation
  7. Emit results via callbacks → AutoTrader + ScannerWidget
"""

from __future__ import annotations

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import numpy as np

from loguru import logger
from utils.logger import get_intel_logger

# ── Volume / liquidity thresholds ─────────────────────────────────────────────

MIN_VOLUME_USD_24H   = 5_000_000    # $5M min 24h volume
MIN_PRICE_CHANGE_PCT = 0.5          # At least 0.5% price movement
SCAN_WORKERS         = 8            # Parallel scoring threads
MAX_PAIRS_TO_SCORE   = 80           # Cap at 80 after pre-filter
SEQ_LEN              = 30           # Bars to feed into ML models

# Stablecoins and tokens to skip
SKIP_SYMBOLS = {
    "USDCUSDT","BUSDUSDT","TUSDUSDT","USDPUSDT","FDUSDUSDT",
    "DAIUSDT","FRAXUSDT","USTCUSDT","EURUSDT","GBPUSDT",
    # Leveraged tokens
    "BTCUPUSDT","BTCDOWNUSDT","ETHUPUSDT","ETHDOWNUSDT",
}


# ── Per-pair scan result ──────────────────────────────────────────────────────

@dataclass
class PairScore:
    symbol: str
    current_price: float
    volume_24h_usd: float
    price_change_24h_pct: float

    # Profit score components
    ensemble_confidence: float = 0.0
    ensemble_signal: str = "HOLD"         # BUY | SELL | HOLD
    mtf_confluence_score: float = 0.0
    momentum_score: float = 0.0           # 0-1 normalised
    regime_mult: float = 1.0
    volume_spike: float = 1.0             # current vol / avg vol

    # R:R score components
    atr_pct: float = 0.0                  # ATR as % of price
    rr_ratio: float = 0.0                 # Expected target / stop distance
    historical_win_rate: float = 0.5
    expected_value: float = 0.0           # RR × WR - (1-WR)

    # Council deliberation
    council_disagreement: float = 0.5
    council_veto: str = ""                # "" or reason for veto

    # Combined scores
    profit_score: float = 0.0
    rr_score: float = 0.0
    combined_score: float = 0.0

    # Source votes (which models voted and how)
    votes: dict = field(default_factory=dict)

    timestamp: str = ""
    error: str = ""

    @property
    def is_valid(self) -> bool:
        return not self.error and self.ensemble_signal != "HOLD"

    @property
    def direction_emoji(self) -> str:
        return "🟢" if self.ensemble_signal == "BUY" else "🔴" if self.ensemble_signal == "SELL" else "⚪"


@dataclass
class ScanSummary:
    total_scanned: int
    total_valid: int
    scan_duration_sec: float

    top_profit: list[PairScore] = field(default_factory=list)       # Top 5 by profit_score
    top_rr: list[PairScore] = field(default_factory=list)           # Top 5 by rr_score
    recommendation: Optional[PairScore] = None                      # The ONE trade to take
    all_scores: list[PairScore] = field(default_factory=list)
    timestamp: str = ""

    def summary(self) -> str:
        rec = self.recommendation
        if rec:
            return (
                f"Scan: {self.total_scanned} pairs | {self.total_valid} valid | "
                f"{self.scan_duration_sec:.0f}s | "
                f"RECOMMENDATION: {rec.direction_emoji} {rec.ensemble_signal} "
                f"{rec.symbol} conf={rec.ensemble_confidence:.0%} "
                f"R:R={rec.rr_ratio:.1f}:1 EV={rec.expected_value:.2f}"
            )
        return f"Scan: {self.total_scanned} pairs | {self.total_valid} valid | no recommendation"


# ── Market scanner ────────────────────────────────────────────────────────────

class MarketScanner:
    """
    Scans all USDT pairs through the full ML intelligence stack.

    Usage:
        scanner = MarketScanner(binance_client, regime_detector, mtf_filter,
                                signal_council, ensemble, token_ml, dynamic_risk)
        scanner.on_scan_complete(my_callback)
        scanner.start(interval_sec=300)  # scan every 5 min
        # or single shot:
        summary = scanner.scan_now()
    """

    def __init__(
        self,
        binance_client=None,
        regime_detector=None,
        mtf_filter=None,
        signal_council=None,
        ensemble=None,
        token_ml=None,
        dynamic_risk=None,
        predictor=None,
        trade_journal=None,
    ) -> None:
        self._client   = binance_client
        self._regime   = regime_detector
        self._mtf      = mtf_filter
        self._council  = signal_council
        self._ensemble = ensemble
        self._token_ml = token_ml
        self._drm      = dynamic_risk
        self._predictor = predictor
        self._journal  = trade_journal
        self._intel    = get_intel_logger()

        self._callbacks: list[Callable[[ScanSummary], None]] = []
        self._running  = False
        self._thread: Optional[threading.Thread] = None
        self._last_summary: Optional[ScanSummary] = None
        self._scan_lock = threading.Lock()
        self._excluded_symbols: set[str] = set()   # Symbols with open positions

    # ── Lifecycle ──────────────────────────────────────────────────────

    def on_scan_complete(self, cb: Callable[[ScanSummary], None]) -> None:
        self._callbacks.append(cb)

    def start(self, interval_sec: int = 300) -> None:
        self._running = True
        def _loop():
            while self._running:
                try:
                    self.scan_now()
                except Exception as exc:
                    logger.debug(f"MarketScanner loop error: {exc}")
                time.sleep(interval_sec)
        self._thread = threading.Thread(target=_loop, daemon=True, name="market-scanner")
        self._thread.start()
        self._intel.ml("MarketScanner",
            f"🔭 Market scanner started (interval={interval_sec}s, workers={SCAN_WORKERS})")

    def stop(self) -> None:
        self._running = False

    def set_excluded(self, symbols: set[str]) -> None:
        """Symbols to skip (currently in open positions)."""
        self._excluded_symbols = symbols

    @property
    def last_summary(self) -> Optional[ScanSummary]:
        return self._last_summary

    # ── Main scan ──────────────────────────────────────────────────────

    def scan_now(self, progress_cb: Callable | None = None) -> ScanSummary:
        """
        Run a full market scan. Blocking. Returns ScanSummary.
        Fires on_scan_complete callbacks when done.
        """
        if not self._scan_lock.acquire(blocking=False):
            self._intel.ml("MarketScanner", "⏳ Scan already in progress – skipping")
            return self._last_summary or ScanSummary(0, 0, 0)

        t0 = time.time()
        try:
            self._intel.ml("MarketScanner", "🔭 Starting full market scan…")

            # 1. Get all USDT pairs + 24h ticker
            candidates = self._get_candidates()
            total_candidates = len(candidates)
            self._intel.ml("MarketScanner",
                f"   {total_candidates} pairs after pre-filter | scoring in parallel…")

            if progress_cb:
                progress_cb({"pct": 5, "msg": f"Pre-filtered to {total_candidates} pairs"})

            # 2. Score in parallel
            results: list[PairScore] = []
            completed = 0
            with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
                futures = {pool.submit(self._score_pair, c): c for c in candidates}
                for fut in as_completed(futures):
                    try:
                        score = fut.result(timeout=30)
                        results.append(score)
                    except Exception as exc:
                        sym = futures[fut].get("symbol", "?")
                        results.append(PairScore(
                            symbol=sym, current_price=0, volume_24h_usd=0,
                            price_change_24h_pct=0, error=str(exc),
                        ))
                    completed += 1
                    if progress_cb:
                        pct = 5 + int(completed / total_candidates * 85)
                        progress_cb({"pct": pct, "msg": f"Scored {completed}/{total_candidates}"})

            # 3. Rank
            valid = [r for r in results if r.is_valid]
            valid_buy  = [r for r in valid if r.ensemble_signal == "BUY"]
            valid_sell = [r for r in valid if r.ensemble_signal == "SELL"]
            all_valid  = valid_buy + valid_sell

            top_profit = sorted(all_valid, key=lambda x: -x.profit_score)[:5]
            top_rr     = sorted(all_valid, key=lambda x: -x.rr_score)[:5]

            # 4. Final recommendation: highest combined score from union of top 10
            candidates_final = sorted(all_valid, key=lambda x: -x.combined_score)
            recommendation = candidates_final[0] if candidates_final else None

            duration = time.time() - t0
            summary = ScanSummary(
                total_scanned=total_candidates,
                total_valid=len(all_valid),
                scan_duration_sec=duration,
                top_profit=top_profit,
                top_rr=top_rr,
                recommendation=recommendation,
                all_scores=sorted(all_valid, key=lambda x: -x.combined_score),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._last_summary = summary
            self._intel.ml("MarketScanner", f"✅ {summary.summary()}")

            if progress_cb:
                progress_cb({"pct": 100, "msg": summary.summary()})

            for cb in self._callbacks:
                try:
                    cb(summary)
                except Exception:
                    pass

            return summary

        finally:
            self._scan_lock.release()

    # ── Pair scoring ───────────────────────────────────────────────────

    def _score_pair(self, ticker: dict) -> PairScore:
        """Score a single pair through the full ML stack."""
        symbol = ticker["symbol"]
        price  = float(ticker.get("lastPrice", 0) or ticker.get("price", 0))
        vol    = float(ticker.get("quoteVolume", 0))
        chg    = float(ticker.get("priceChangePercent", 0))

        score = PairScore(
            symbol=symbol, current_price=price,
            volume_24h_usd=vol, price_change_24h_pct=chg,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Load OHLCV data
        df = self._load_candles(symbol, "1h", limit=60)
        if df is None or len(df) < SEQ_LEN + 5:
            score.error = "insufficient data"
            return score

        # ── Momentum score ─────────────────────────────────────────────
        score.momentum_score = self._compute_momentum(df)

        # ── Volume spike ───────────────────────────────────────────────
        try:
            vols = df["volume"].astype(float).values
            score.volume_spike = float(vols[-1] / (np.mean(vols[-20:]) + 1e-9))
        except Exception:
            score.volume_spike = 1.0

        # ── ATR (for R:R) ──────────────────────────────────────────────
        score.atr_pct = self._compute_atr_pct(df, price)

        # ── Regime multiplier ──────────────────────────────────────────
        if self._regime:
            snap = self._regime.current
            from ml.regime_detector import REGIME_PARAMS
            reg = snap.regime
            score.regime_mult = REGIME_PARAMS.get(reg, {}).get("position_size_mult", 0.75)
        else:
            score.regime_mult = 0.75

        # ── Primary ML signal (per-token or universal) ─────────────────
        raw_signal = self._get_ml_signal(symbol, df)
        action     = raw_signal.get("signal") or raw_signal.get("action", "HOLD")
        confidence = float(raw_signal.get("confidence", 0.5))

        if action == "HOLD" or confidence < 0.50:
            score.error = "HOLD signal or low confidence"
            return score

        # ── MTF confluence ─────────────────────────────────────────────
        mtf_score = 0.5
        if self._mtf:
            try:
                confluence = self._mtf.check(symbol, action, confidence)
                if not confluence.passes_filter:
                    score.error = f"MTF conflict: {confluence.reject_reason}"
                    return score
                mtf_score = max(0.0, confluence.confluence_pct)
                score.mtf_confluence_score = mtf_score
            except Exception:
                score.mtf_confluence_score = 0.5
                mtf_score = 0.5
        else:
            score.mtf_confluence_score = 0.5

        # ── Signal council deliberation ────────────────────────────────
        if self._council:
            try:
                sources = {
                    "lstm_predictor": {"signal": action, "confidence": confidence},
                }
                # Add sentiment if available
                regime_str = ""
                if self._regime:
                    snap = self._regime.current
                    regime_str = snap.regime.value

                decision = self._council.deliberate(sources, symbol=symbol, regime=regime_str)
                score.council_disagreement = decision.disagreement_score
                score.council_veto = decision.vetoed_by

                if decision.final_signal == "HOLD" or decision.vetoed_by:
                    score.error = f"Council: {decision.vetoed_by or 'HOLD'}"
                    return score
                action     = decision.final_signal
                confidence = decision.final_confidence
                score.votes = {m.name: {"signal": m.signal, "conf": m.final_confidence}
                               for m in decision.members}
            except Exception:
                pass

        score.ensemble_signal     = action
        score.ensemble_confidence = confidence

        # ── Historical win rate: blend live journal edge + TokenML profile ─
        profile_wr = 0.5
        if self._token_ml:
            try:
                task = self._token_ml.get_task(symbol)
                if task:
                    profile_wr = getattr(task.profile, "live_win_rate", 0.5) or 0.5
            except Exception:
                pass
        live_wr = self._get_symbol_edge(symbol)
        # 70% weight to actual trade outcomes, 30% to model profile when journal has data
        if live_wr is not None:
            score.historical_win_rate = 0.70 * live_wr + 0.30 * profile_wr
        else:
            score.historical_win_rate = profile_wr

        # ── R:R ratio from ATR ─────────────────────────────────────────
        if score.atr_pct > 0:
            atr_mult_tp = 2.0   # 2× ATR target (1:2 minimum R:R)
            atr_mult_sl = 1.0   # 1× ATR stop
            if self._regime:
                atr_mult_sl = self._regime.atr_stop_multiplier()
            score.rr_ratio = atr_mult_tp / atr_mult_sl
        else:
            score.rr_ratio = 2.0

        # ── Expected value ─────────────────────────────────────────────
        wr = score.historical_win_rate
        score.expected_value = (score.rr_ratio * wr) - (1 - wr)

        # ── Compute composite scores ───────────────────────────────────
        # Profit score: strong signal + momentum + MTF agreement + regime + volume
        score.profit_score = (
            confidence *
            (0.5 + score.momentum_score * 0.5) *
            (0.5 + mtf_score * 0.5) *
            score.regime_mult *
            min(2.0, score.volume_spike) / 2.0
        )

        # R:R score: best asymmetric payout, small stops, positive EV
        if score.atr_pct > 0 and score.expected_value > 0:
            score.rr_score = (
                score.expected_value *
                (1 / (score.atr_pct * 100 + 1e-9)) *   # Prefer smaller stops
                confidence *
                score.regime_mult
            )
        else:
            score.rr_score = 0.0

        # Combined: 55% profit signal quality, 45% R:R
        score.combined_score = 0.55 * score.profit_score + 0.45 * score.rr_score

        return score

    # ── Data fetching ──────────────────────────────────────────────────

    def _get_candidates(self) -> list[dict]:
        """Fetch all USDT pairs, apply pre-filter, return list of ticker dicts."""
        tickers = []
        try:
            if self._client:
                raw = self._client.get_ticker_24h()
                if raw:
                    tickers = raw if isinstance(raw, list) else [raw]
        except Exception as exc:
            logger.debug(f"MarketScanner ticker fetch error: {exc}")
            return []

        filtered = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            if sym in SKIP_SYMBOLS or sym in self._excluded_symbols:
                continue
            # Skip leveraged tokens (contain "UP", "DOWN", "BEAR", "BULL" after stripping USDT)
            base = sym.replace("USDT", "")
            if any(x in base for x in ["UP", "DOWN", "BEAR", "BULL", "3L", "3S"]):
                continue
            vol  = float(t.get("quoteVolume", 0))
            chg  = abs(float(t.get("priceChangePercent", 0)))
            if vol < MIN_VOLUME_USD_24H:
                continue
            if chg < MIN_PRICE_CHANGE_PCT:
                continue
            filtered.append(t)

        # Sort by volume descending, take top N
        filtered.sort(key=lambda x: -float(x.get("quoteVolume", 0)))
        return filtered[:MAX_PAIRS_TO_SCORE]

    def _load_candles(self, symbol: str, interval: str, limit: int = 60):
        """Load OHLCV candles for a symbol."""
        # Try Redis cache first
        try:
            from db.redis_client import RedisClient
            cached = RedisClient().get_candles(symbol, interval)
            if cached and len(cached) >= SEQ_LEN:
                import pandas as pd
                df = pd.DataFrame(cached)
                for col in ("open","high","low","close","volume"):
                    if col in df.columns:
                        df[col] = df[col].astype(float)
                return df.tail(limit)
        except Exception:
            pass
        # Try DataCollector
        try:
            from ml.data_collector import DataCollector
            df = DataCollector.load_dataframe(symbol, interval, limit=limit)
            if not df.empty:
                return df
        except Exception:
            pass
        return None

    def _get_ml_signal(self, symbol: str, df) -> dict:
        """Get best available ML signal for this symbol."""
        # Per-token model first
        if self._token_ml:
            try:
                task = self._token_ml.get_task(symbol)
                if task and task.is_trained:
                    return task.predict(df.tail(SEQ_LEN + 5))
            except Exception:
                pass
        # Universal predictor
        if self._predictor:
            try:
                result = self._predictor.predict(symbol, df=df)
                if result:
                    return result
            except Exception:
                pass
        return {"signal": "HOLD", "confidence": 0.5}

    def _get_symbol_edge(self, symbol: str) -> Optional[float]:
        """
        Compute actual win rate for this symbol from the last 30 closed trades
        in the trade journal. Returns None if fewer than 5 trades exist (not enough data).
        """
        if not self._journal:
            return None
        try:
            closed = self._journal.get_closed_trades(limit=500)
            sym_trades = [t for t in closed if t.get("symbol") == symbol][-30:]
            if len(sym_trades) < 5:
                return None
            wins = sum(1 for t in sym_trades if (t.get("pnl") or 0) > 0)
            return wins / len(sym_trades)
        except Exception:
            return None

    def _compute_momentum(self, df) -> float:
        """Return normalised momentum score 0-1."""
        try:
            closes = df["close"].astype(float).values
            if len(closes) < 20:
                return 0.5
            ema20 = np.mean(closes[-20:])
            price = closes[-1]
            roc = (price - closes[-10]) / (closes[-10] + 1e-9)
            above_ema = 1.0 if price > ema20 else 0.0
            # Combine: above EMA + positive ROC
            return float(0.5 * above_ema + 0.5 * min(1.0, max(0.0, 0.5 + roc * 10)))
        except Exception:
            return 0.5

    def _compute_atr_pct(self, df, price: float) -> float:
        """ATR as % of current price."""
        try:
            h = df["high"].astype(float).values
            l = df["low"].astype(float).values
            c = df["close"].astype(float).values
            tr = np.maximum(h[1:]-l[1:], np.maximum(abs(h[1:]-c[:-1]), abs(l[1:]-c[:-1])))
            atr = float(np.mean(tr[-14:]))
            return atr / (price + 1e-9)
        except Exception:
            return 0.02   # Default 2% ATR
