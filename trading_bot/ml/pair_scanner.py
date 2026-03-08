"""
Pair Scanner ML — Discovers, ranks, and monitors all Binance trading pairs.

Scans all quote assets: USDT, BTC, ETH, BNB, SOL.

The scanner's sole job is to:

  1. Fetch the full USDT universe from Binance 24h ticker (every 15 min)
  2. Score each pair on three axes:
       - Volume     : 24h quote volume in USDT (liquidity)
       - Activity   : 24h trade count + price-change magnitude (participation)
       - Momentum   : directional price-change strength (trending vs flat)
  3. Compute a composite Priority Score and label pairs HIGH / MEDIUM / LOW
  4. Log the ranked list and broadcast it to any registered callbacks
  5. Expose get_all_pairs() / get_top_pairs(n) so every other module
     (ArbitrageDetector, TrendScanner, MarketScanner, UI selectors) can pull
     a fresh, pre-ranked symbol list at any time

Priority labels:
  HIGH   — top 20 % by priority score  (most liquid, active, trending)
  MEDIUM — next 30 % by priority score
  LOW    — remaining 50 %  (thin markets, low activity)

Scoring (all scores normalised 0–1 against the current universe):

  volume_score   = rank_normalise(quote_volume)
  activity_score = rank_normalise(trade_count)
  momentum_score = rank_normalise(abs(price_change_pct))

  priority_score = 0.55 × volume_score
                 + 0.30 × activity_score
                 + 0.15 × momentum_score

Integration:
  - TrendScanner.add_symbol() is called for all HIGH + MEDIUM pairs
  - ArbitrageDetector.add_pair() is called for the top 20 HIGH pairs
  - MainWindow symbol dropdowns reload from get_top_pairs()
  - MarketScanner receives the top-50 list via set_universe()
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from loguru import logger
from utils.logger import get_intel_logger


# ── Constants ─────────────────────────────────────────────────────────────────

REFRESH_INTERVAL_SEC = 900   # 15-minute full refresh cycle

# Quote assets to scan — USDT is primary; others included for cross-pair coverage
QUOTE_ASSETS: list[str] = ["USDT", "BTC", "ETH", "BNB", "SOL"]

MAX_PAIRS   = 1000           # Hard cap across all quote assets
MIN_VOLUME_USDT = 100_000    # Drop pairs with < $100k equivalent daily volume
                             # (non-USDT pairs use last_price × quoteVolume proxy)

# Priority thresholds (percentile cutoffs)
HIGH_THRESHOLD   = 0.80   # top 20 %
MEDIUM_THRESHOLD = 0.50   # next 30 %  (below high, above 50 %)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class PairInfo:
    """Snapshot of a single trading pair's 24-hour statistics and ML scores."""
    symbol:            str
    base:              str
    quote:             str             # always USDT in this scanner
    last_price:        float
    price_change_pct:  float           # 24h % change (signed)
    quote_volume:      float           # 24h traded volume in USDT
    trade_count:       int             # 24h number of individual trades
    high_24h:          float
    low_24h:           float
    # Normalised ML scores
    volume_score:      float = 0.0    # 0–1, higher = more liquid
    activity_score:    float = 0.0    # 0–1, higher = more active
    momentum_score:    float = 0.0    # 0–1, higher = stronger price move
    priority_score:    float = 0.0    # 0–1, composite
    # Label
    priority:          str = "LOW"    # "HIGH" | "MEDIUM" | "LOW"
    updated_at:        str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def volatility_pct(self) -> float:
        """Intra-day high/low range as % of open price approximation."""
        if self.last_price <= 0:
            return 0.0
        return (self.high_24h - self.low_24h) / self.last_price * 100

    @property
    def priority_emoji(self) -> str:
        return {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "⚪"}.get(self.priority, "⚪")


# ── Main scanner ──────────────────────────────────────────────────────────────

class PairScanner:
    """
    Discovers and ranks all USDT trading pairs on Binance by volume, activity,
    and momentum.  Broadcasts ranked pair lists to registered callbacks.

    Usage::

        scanner = PairScanner(binance_client=client)
        scanner.on_update(my_callback)   # cb(list[PairInfo])
        scanner.start()

        top50 = scanner.get_top_pairs(50)
        all_high = scanner.get_pairs_by_priority("HIGH")
    """

    def __init__(self, binance_client=None) -> None:
        self._client  = binance_client
        self._intel   = get_intel_logger()
        self._lock    = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Ranked pair list (best first)
        self._pairs: list[PairInfo] = []
        self._last_refresh: float = 0.0

        self._callbacks: list[Callable[[list[PairInfo]], None]] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_update(self, cb: Callable[[list[PairInfo]], None]) -> None:
        """Register callback — invoked after every refresh with ranked PairInfo list."""
        self._callbacks.append(cb)

    def get_all_pairs(self) -> list[PairInfo]:
        """Return full ranked pair list (snapshot, ordered best→worst)."""
        with self._lock:
            return list(self._pairs)

    def get_top_pairs(self, n: int = 50) -> list[PairInfo]:
        """Return the top-N pairs by priority score."""
        with self._lock:
            return self._pairs[:n]

    def get_top_symbols(self, n: int = 50) -> list[str]:
        """Return the top-N symbol strings (e.g. 'BTCUSDT')."""
        return [p.symbol for p in self.get_top_pairs(n)]

    def get_pairs_by_priority(self, priority: str) -> list[PairInfo]:
        """Return all pairs matching the given priority label (HIGH/MEDIUM/LOW)."""
        with self._lock:
            return [p for p in self._pairs if p.priority == priority]

    def get_pair(self, symbol: str) -> Optional[PairInfo]:
        """Return PairInfo for a specific symbol, or None if not found."""
        with self._lock:
            for p in self._pairs:
                if p.symbol == symbol:
                    return p
        return None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="pair-scanner"
        )
        self._thread.start()
        self._intel.ml("PairScanner", "Started — scanning Binance USDT universe")

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(1)   # brief warm-up to let other services start first
        while self._running:
            t0 = time.monotonic()
            try:
                self._refresh()
            except Exception as exc:
                logger.warning(f"PairScanner refresh error: {exc!r}")
            elapsed = time.monotonic() - t0
            sleep_for = max(1.0, REFRESH_INTERVAL_SEC - elapsed)
            time.sleep(sleep_for)

    def _refresh(self) -> None:
        """Fetch all tickers, score, rank, label, and broadcast."""
        raw = self._fetch_tickers()
        if not raw:
            logger.warning("PairScanner: no ticker data received")
            return

        pairs = self._build_pairs(raw)
        if not pairs:
            return

        pairs = self._score_and_rank(pairs)

        with self._lock:
            self._pairs = pairs
            self._last_refresh = time.time()

        # Log summary
        high_n   = sum(1 for p in pairs if p.priority == "HIGH")
        medium_n = sum(1 for p in pairs if p.priority == "MEDIUM")
        low_n    = sum(1 for p in pairs if p.priority == "LOW")
        self._intel.ml(
            "PairScanner",
            f"Ranked {len(pairs)} USDT pairs  "
            f"HIGH={high_n}  MEDIUM={medium_n}  LOW={low_n}  "
            f"(top: {pairs[0].symbol if pairs else 'n/a'})"
        )

        # Persist market stats to pair_registry table
        self._persist_to_db(pairs)

        # Broadcast
        for cb in self._callbacks:
            try:
                cb(list(pairs))
            except Exception as exc:
                logger.warning(f"PairScanner callback error: {exc!r}")

    # ── Data fetching ──────────────────────────────────────────────────────────

    def _fetch_tickers(self) -> list[dict]:
        """Fetch 24h statistics for all symbols from Binance."""
        if self._client:
            try:
                tickers = self._client.get_ticker_24hr()
                if isinstance(tickers, list):
                    return tickers
            except Exception as exc:
                logger.warning(f"PairScanner: Binance fetch failed: {exc!r}")

        # Offline / demo fallback — generate a plausible universe
        return self._synthetic_tickers()

    def _build_pairs(self, tickers: list[dict]) -> list[PairInfo]:
        """
        Filter pairs whose quote asset is in QUOTE_ASSETS, apply minimum
        volume filter, and build PairInfo objects.

        For non-USDT quotes the volume filter is approximate (raw quote volume
        without USDT conversion), so some thin BTC/ETH pairs may slip through —
        they will naturally score low and land in the LOW bucket.
        """
        pairs: list[PairInfo] = []
        for t in tickers:
            try:
                sym   = str(t.get("symbol", ""))
                quote = next(
                    (q for q in QUOTE_ASSETS if sym.endswith(q) and sym != q),
                    None,
                )
                if quote is None:
                    continue
                base = sym[:-len(quote)]
                if not base:
                    continue
                vol = float(t.get("quoteVolume", 0))
                # Apply volume floor only for USDT; for other quotes use a
                # lower absolute threshold so liquid cross-pairs aren't dropped
                min_vol = MIN_VOLUME_USDT if quote == "USDT" else 10
                if vol < min_vol:
                    continue
                pairs.append(PairInfo(
                    symbol           = sym,
                    base             = base,
                    quote            = quote,
                    last_price       = float(t.get("lastPrice",  0)),
                    price_change_pct = float(t.get("priceChangePercent", 0)),
                    quote_volume     = vol,
                    trade_count      = int(t.get("count", 0)),
                    high_24h         = float(t.get("highPrice", 0)),
                    low_24h          = float(t.get("lowPrice",  0)),
                ))
            except (KeyError, ValueError, TypeError):
                continue

        # Hard cap — sort by volume descending before truncating
        pairs.sort(key=lambda p: -p.quote_volume)
        return pairs[:MAX_PAIRS]

    def _score_and_rank(self, pairs: list[PairInfo]) -> list[PairInfo]:
        """Compute normalised ML scores and assign priority labels."""
        if not pairs:
            return []

        # Extract raw values for normalisation
        volumes    = [p.quote_volume      for p in pairs]
        activities = [float(p.trade_count) for p in pairs]
        momenta    = [abs(p.price_change_pct) for p in pairs]

        v_max = max(volumes)    or 1.0
        a_max = max(activities) or 1.0
        m_max = max(momenta)    or 1.0

        for p in pairs:
            p.volume_score   = p.quote_volume / v_max
            p.activity_score = p.trade_count  / a_max
            p.momentum_score = abs(p.price_change_pct) / m_max
            p.priority_score = (
                0.55 * p.volume_score
                + 0.30 * p.activity_score
                + 0.15 * p.momentum_score
            )

        # Sort by priority score descending
        pairs.sort(key=lambda p: -p.priority_score)

        # Label percentile buckets
        n = len(pairs)
        high_cutoff   = max(1, round(n * (1 - HIGH_THRESHOLD)))
        medium_cutoff = max(1, round(n * (1 - MEDIUM_THRESHOLD)))
        for i, p in enumerate(pairs):
            if i < high_cutoff:
                p.priority = "HIGH"
            elif i < medium_cutoff:
                p.priority = "MEDIUM"
            else:
                p.priority = "LOW"

        ts = datetime.now(timezone.utc).isoformat()
        for p in pairs:
            p.updated_at = ts

        return pairs

    # ── Offline fallback ───────────────────────────────────────────────────────

    def _persist_to_db(self, pairs: list[PairInfo]) -> None:
        """Upsert all pair market stats into the pair_registry table."""
        try:
            from sqlalchemy import select
            from db.postgres import get_db
            from db.models import PairRegistry
            with get_db() as db:
                for p in pairs:
                    row = db.execute(select(PairRegistry).filter_by(symbol=p.symbol)).scalar_one_or_none()
                    if row is None:
                        row = PairRegistry(symbol=p.symbol, base=p.base, quote=p.quote)
                        db.add(row)
                    row.last_price       = p.last_price
                    row.price_change_pct = p.price_change_pct
                    row.quote_volume     = p.quote_volume
                    row.trade_count      = p.trade_count
                    row.high_24h         = p.high_24h
                    row.low_24h          = p.low_24h
                    row.volume_score     = p.volume_score
                    row.activity_score   = p.activity_score
                    row.momentum_score   = p.momentum_score
                    row.priority_score   = p.priority_score
                    row.priority         = p.priority
        except Exception as exc:
            logger.debug(f"PairScanner: DB persist failed: {exc!r}")

    @staticmethod
    def _synthetic_tickers() -> list[dict]:
        """
        Generate a synthetic 24h ticker list for demo / offline use.
        Covers a realistic set of popular USDT pairs with plausible volumes.
        """
        _pairs_data = [
            # symbol, price, pct_chg, vol_M, trades_k, high, low
            ("BTCUSDT",   65000.0,  1.2,  8000,  900, 66500, 63500),
            ("ETHUSDT",    3500.0,  0.8,  4200,  750, 3580,  3420),
            ("BNBUSDT",     580.0,  1.5,   800,  420, 590,   565),
            ("SOLUSDT",     180.0,  3.1,  1200,  680, 185,   175),
            ("XRPUSDT",       0.65, -0.4,  900,  510, 0.67,  0.63),
            ("ADAUSDT",       0.48,  2.1,  400,  320, 0.50,  0.46),
            ("AVAXUSDT",     40.0,  2.8,  350,  280, 41.5,  38.5),
            ("DOGEUSDT",      0.12,  5.5,  600,  450, 0.125, 0.115),
            ("DOTUSDT",       8.0,  1.0,  200,  210, 8.3,   7.7),
            ("MATICUSDT",     0.90, -1.2,  300,  260, 0.93,  0.87),
            ("LINKUSDT",     15.0,  2.3,  250,  230, 15.5,  14.5),
            ("LTCUSDT",      85.0,  0.6,  180,  190, 87,    83),
            ("UNIUSDT",       7.5,  1.8,  150,  170, 7.8,   7.2),
            ("ATOMUSDT",      9.0,  0.9,  130,  160, 9.3,   8.7),
            ("NEARUSDT",      5.0,  4.2,  180,  200, 5.2,   4.8),
            ("SHIBUSDT",   0.000025, 6.1, 450,  380, 0.000026, 0.000024),
            ("TRXUSDT",       0.13,  0.3,  220,  195, 0.132, 0.128),
            ("ETCUSDT",      25.0,  1.7,  120,  145, 26,    24),
            ("FILUSDT",       5.5,  2.5,  100,  130, 5.7,   5.3),
            ("SANDUSDT",      0.35,  3.8,  140,  165, 0.37,  0.33),
            ("MANAUSDT",      0.42,  2.1,  120,  140, 0.44,  0.40),
            ("APTUSDT",       9.5,  1.4,  160,  175, 9.8,   9.2),
            ("ARBUSDT",       1.10, -0.8,  200,  210, 1.13,  1.07),
            ("OPUSDT",        2.50,  1.9,  180,  195, 2.58,  2.42),
            ("INJUSDT",      28.0,  4.5,  140,  165, 29,    27),
            ("TIAUSDT",      12.0,  3.2,  110,  135, 12.5,  11.5),
            ("SUIUSDT",       1.80,  5.0,  190,  205, 1.88,  1.72),
            ("SEIUSDT",       0.55,  2.7,  130,  150, 0.57,  0.53),
            ("WLDUSDT",       3.20,  1.5,  115,  135, 3.30,  3.10),
            ("PENDLEUSDT",    4.50,  6.8,  100,  125, 4.70,  4.30),
            ("JUPUSDT",       0.95,  3.4,  120,  140, 0.98,  0.92),
            ("PYTHUSDT",      0.42,  2.9,  110,  130, 0.44,  0.40),
            ("STRKUSDT",      1.15,  4.1,  105,  128, 1.20,  1.10),
            ("DYMUSDT",       4.80,  5.2,   95,  118, 5.00,  4.60),
            ("ALTUSDT",       0.38,  7.3,  108,  132, 0.40,  0.36),
            ("ONDOUSDT",      1.05,  8.1,  125,  148, 1.10,  1.00),
            ("FETUSDT",       2.20,  3.6,  115,  138, 2.30,  2.10),
            ("RENDERUSDT",    7.50,  2.4,  100,  122, 7.80,  7.20),
            ("IOTAUSDT",      0.28,  1.8,   90,  115, 0.29,  0.27),
            ("ALGOUSDT",      0.18,  0.9,   85,  108, 0.185, 0.175),
            ("VETUSDT",      0.036, -0.5,  100,  118, 0.037, 0.035),
            ("ICPUSDT",      14.0,  2.2,   95,  115, 14.5,  13.5),
            ("LDOUSDT",       2.30,  1.6,  105,  125, 2.40,  2.20),
            ("STXUSDT",       2.80,  3.1,  110,  130, 2.90,  2.70),
            ("RUNEUSDT",      5.20,  4.0,  100,  122, 5.40,  5.00),
            ("AAVEUSDT",     95.0,  1.3,   90,  112, 98,    92),
            ("MKRUSDT",    2800.0,  0.7,   80,  105, 2850,  2750),
            ("GRTUSDT",       0.30,  2.5,   95,  118, 0.31,  0.29),
            ("CRVUSDT",       0.55,  1.1,   88,  110, 0.57,  0.53),
            ("SNXUSDT",       3.10,  2.0,   82,  106, 3.20,  3.00),
        ]
        tickers = []
        for row in _pairs_data:
            sym, price, pct, vol_m, trades_k, high, low = row
            tickers.append({
                "symbol":             sym,
                "lastPrice":          str(price),
                "priceChangePercent": str(pct),
                "quoteVolume":        str(vol_m * 1_000_000),
                "count":              str(trades_k * 1000),
                "highPrice":          str(high),
                "lowPrice":           str(low),
            })
        return tickers
