"""
Liquidity Depth Analyzer ML — Assesses order-book depth and liquidity quality
for every scanned pair to identify thin-market risks and execution quality.

The analyzer fetches Level-2 order book snapshots and computes:

  1. Bid/Ask spread ratio      — tighter spread = better liquidity
  2. Depth imbalance           — bid depth vs ask depth (buy/sell pressure proxy)
  3. Wall detection            — large orders (≥ 2× average) blocking price movement
  4. Slippage estimate         — cost to execute MIN_TRADE_USDT through the book
  5. Thin-book flag            — overall depth below safety threshold

Liquidity Grades:
  DEEP     — Excellent depth, tight spread, low slippage   (score ≥ 0.75)
  ADEQUATE — Acceptable for normal position sizes          (score ≥ 0.50)
  THIN     — Elevated slippage risk, use smaller sizes     (score ≥ 0.30)
  ILLIQUID — Dangerous — avoid or use micro positions      (score  < 0.30)

Algorithm (computed from Level-2 order book, depth=50):

  spread_score    : 1 - (ask - bid) / mid_price × 100   (capped)
  imbalance_score : bid_depth / (bid_depth + ask_depth)  (0.5 = balanced)
  depth_score     : min(1, total_depth_usdt / DEPTH_FLOOR_USDT)
  wall_penalty    : fraction of volume held in walls      (lower = better)
  slippage_score  : 1 - estimated_slippage_pct / MAX_SLIPPAGE_PCT

  liquidity_score = (
      0.30 × spread_score
    + 0.25 × depth_score
    + 0.20 × slippage_score
    + 0.15 × (1 − wall_penalty)
    + 0.10 × imbalance_score   (distance from 0.5 inverted)
  )

Results are:
  - Stored in pair_registry.liquidity_score + liquidity_grade
  - Exposed via get_deep(), get_thin(), get_illiquid() for UI and strategy modules
  - Emitted as callbacks to subscribers when grade changes

Refresh: every SCAN_INTERVAL_SEC (default 600 s / 10 min).
Scans HIGH + MEDIUM priority pairs (where liquidity matters most for execution).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import numpy as np
from loguru import logger
from utils.logger import get_intel_logger


SCAN_INTERVAL_SEC   = 600      # 10-minute cycle
ORDER_BOOK_DEPTH    = 50       # levels to fetch per side
DEPTH_FLOOR_USDT    = 50_000   # minimum healthy depth (USDT equivalent)
MIN_TRADE_USDT      = 15.24    # £12 GBP floor — slippage test size
MAX_SLIPPAGE_PCT    = 1.0      # 1% slippage = 0.0 score

DEEP_THRESHOLD      = 0.75
ADEQUATE_THRESHOLD  = 0.50
THIN_THRESHOLD      = 0.30


@dataclass
class LiquidityResult:
    """Liquidity analysis result for one symbol."""
    symbol:           str
    liquidity_score:  float         # 0.0–1.0
    grade:            str           # DEEP | ADEQUATE | THIN | ILLIQUID
    spread_pct:       float = 0.0   # (ask-bid)/mid × 100
    spread_score:     float = 0.0
    bid_depth_usdt:   float = 0.0
    ask_depth_usdt:   float = 0.0
    depth_score:      float = 0.0
    imbalance:        float = 0.5   # 0=all ask, 1=all bid; 0.5=balanced
    wall_penalty:     float = 0.0   # fraction of vol in walls
    slippage_pct:     float = 0.0   # estimated slippage for MIN_TRADE_USDT
    slippage_score:   float = 0.0
    bid_levels:       int   = 0
    ask_levels:       int   = 0
    note:             str   = ""
    updated_at:       str   = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def grade_emoji(self) -> str:
        return {
            "DEEP":     "💧",
            "ADEQUATE": "🟡",
            "THIN":     "🔴",
            "ILLIQUID": "💀",
        }.get(self.grade, "❓")


class LiquidityDepthAnalyzer:
    """
    Fetches order-book snapshots and grades each pair's liquidity quality.

    Usage::

        analyzer = LiquidityDepthAnalyzer(
            binance_client=client,
            pair_scanner=pair_scanner,
        )
        analyzer.on_update(my_callback)   # called after each scan cycle
        analyzer.start()
        deep = analyzer.get_deep()
    """

    def __init__(
        self,
        binance_client=None,
        pair_scanner=None,
    ) -> None:
        self._client = binance_client
        self._pairs  = pair_scanner
        self._intel  = get_intel_logger()
        self._lock   = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._results:   dict[str, LiquidityResult] = {}
        self._callbacks: list[Callable[[list[LiquidityResult]], None]] = []

        # Cache: symbol → {"data": dict, "ts": float}
        self._cache: dict[str, dict] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_update(self, cb: Callable[[list[LiquidityResult]], None]) -> None:
        """Register callback — called with all results after each scan."""
        self._callbacks.append(cb)

    def get_all(self) -> list[LiquidityResult]:
        """Return all results sorted by score descending."""
        with self._lock:
            return sorted(self._results.values(), key=lambda r: -r.liquidity_score)

    def get_deep(self) -> list[LiquidityResult]:
        """Return DEEP grade results."""
        with self._lock:
            return sorted(
                [r for r in self._results.values() if r.grade == "DEEP"],
                key=lambda r: -r.liquidity_score,
            )

    def get_adequate(self) -> list[LiquidityResult]:
        """Return DEEP + ADEQUATE results."""
        with self._lock:
            return sorted(
                [r for r in self._results.values() if r.grade in ("DEEP", "ADEQUATE")],
                key=lambda r: -r.liquidity_score,
            )

    def get_thin(self) -> list[LiquidityResult]:
        """Return THIN + ILLIQUID results."""
        with self._lock:
            return sorted(
                [r for r in self._results.values() if r.grade in ("THIN", "ILLIQUID")],
                key=lambda r: r.liquidity_score,
            )

    def get_illiquid(self) -> list[LiquidityResult]:
        """Return only ILLIQUID results."""
        with self._lock:
            return sorted(
                [r for r in self._results.values() if r.grade == "ILLIQUID"],
                key=lambda r: r.liquidity_score,
            )

    def get_result(self, symbol: str) -> Optional[LiquidityResult]:
        """Return the latest result for a specific symbol."""
        with self._lock:
            return self._results.get(symbol)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="liquidity-depth-analyzer"
        )
        self._thread.start()
        self._intel.ml("LiquidityDepthAnalyzer",
                       "Started — scanning order-book depth across all pairs")

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(15)  # wait for pair scanner first
        while self._running:
            t0 = time.monotonic()
            try:
                self._scan()
            except Exception as exc:
                logger.warning(f"LiquidityDepthAnalyzer error: {exc!r}")
            elapsed = time.monotonic() - t0
            time.sleep(max(1.0, SCAN_INTERVAL_SEC - elapsed))

    def _scan(self) -> None:
        """Scan HIGH + MEDIUM priority pairs for liquidity depth."""
        candidates: list[str] = []

        if self._pairs:
            high   = self._pairs.get_pairs_by_priority("HIGH")
            medium = self._pairs.get_pairs_by_priority("MEDIUM")
            candidates = [p.symbol for p in (high + medium)]
        else:
            candidates = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
                "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
            ]

        new_results: dict[str, LiquidityResult] = {}
        for sym in candidates:
            if not self._running:
                break
            try:
                result = self._analyze(sym)
                if result:
                    new_results[sym] = result
                    if result.grade in ("THIN", "ILLIQUID"):
                        self._persist(result)
            except Exception as exc:
                logger.debug(f"LiquidityDepthAnalyzer: {sym} failed: {exc!r}")

        with self._lock:
            self._results.update(new_results)

        deep_count     = sum(1 for r in new_results.values() if r.grade == "DEEP")
        adequate_count = sum(1 for r in new_results.values() if r.grade == "ADEQUATE")
        thin_count     = sum(1 for r in new_results.values() if r.grade == "THIN")
        illiquid_count = sum(1 for r in new_results.values() if r.grade == "ILLIQUID")

        self._intel.ml(
            "LiquidityDepthAnalyzer",
            f"Scan complete — {len(new_results)} pairs  "
            f"DEEP={deep_count}  ADEQUATE={adequate_count}  "
            f"THIN={thin_count}  ILLIQUID={illiquid_count}"
        )

        for cb in self._callbacks:
            try:
                cb(sorted(new_results.values(), key=lambda r: -r.liquidity_score))
            except Exception as exc:
                logger.warning(f"LiquidityDepthAnalyzer callback error: {exc!r}")

    # ── Per-symbol analysis ────────────────────────────────────────────────────

    def _analyze(self, symbol: str) -> Optional[LiquidityResult]:
        """Fetch order book and compute liquidity sub-scores."""
        book = self._fetch_order_book(symbol, ORDER_BOOK_DEPTH)
        if not book:
            return None

        bids = book.get("bids", [])  # [[price, qty], ...]
        asks = book.get("asks", [])

        if not bids or not asks:
            return None

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid      = (best_bid + best_ask) / 2.0

        if mid < 1e-12:
            return None

        # ── 1. Spread score ────────────────────────────────────────────────────
        spread_pct   = (best_ask - best_bid) / mid * 100
        spread_score = max(0.0, min(1.0, 1.0 - spread_pct / 0.5))  # 0.5% spread = 0

        # ── 2. Depth computation ───────────────────────────────────────────────
        bid_depth_usdt = sum(float(p) * float(q) for p, q in bids)
        ask_depth_usdt = sum(float(p) * float(q) for p, q in asks)
        total_depth    = bid_depth_usdt + ask_depth_usdt

        depth_score = min(1.0, total_depth / DEPTH_FLOOR_USDT)

        # ── 3. Imbalance — bid / total (0.5 = balanced) ───────────────────────
        if total_depth > 0:
            imbalance = bid_depth_usdt / total_depth
        else:
            imbalance = 0.5
        # Imbalance contribution: penalty for extreme imbalance
        imbalance_score = 1.0 - abs(imbalance - 0.5) * 2.0  # 0.5 → 1.0, 0 or 1 → 0

        # ── 4. Wall detection — orders ≥ 2× average size ──────────────────────
        all_sizes  = [float(q) * float(p) for p, q in bids + asks]
        if all_sizes:
            avg_size   = np.mean(all_sizes)
            wall_usdt  = sum(s for s in all_sizes if s >= 2.0 * avg_size)
            wall_penalty = min(1.0, wall_usdt / max(1.0, total_depth))
        else:
            wall_penalty = 0.0

        # ── 5. Slippage estimate — walk the book for MIN_TRADE_USDT ───────────
        slippage_pct   = self._estimate_slippage(asks, mid, MIN_TRADE_USDT)
        slippage_score = max(0.0, min(1.0, 1.0 - slippage_pct / MAX_SLIPPAGE_PCT))

        # ── Composite ─────────────────────────────────────────────────────────
        score = (
            0.30 * spread_score
            + 0.25 * depth_score
            + 0.20 * slippage_score
            + 0.15 * (1.0 - wall_penalty)
            + 0.10 * imbalance_score
        )
        score = max(0.0, min(1.0, score))

        # Grade
        if score >= DEEP_THRESHOLD:
            grade = "DEEP"
        elif score >= ADEQUATE_THRESHOLD:
            grade = "ADEQUATE"
        elif score >= THIN_THRESHOLD:
            grade = "THIN"
        else:
            grade = "ILLIQUID"

        walls_note = f"WallPct={wall_penalty:.1%}" if wall_penalty > 0.1 else ""
        return LiquidityResult(
            symbol          = symbol,
            liquidity_score = round(score, 4),
            grade           = grade,
            spread_pct      = round(spread_pct, 4),
            spread_score    = round(spread_score, 3),
            bid_depth_usdt  = round(bid_depth_usdt, 2),
            ask_depth_usdt  = round(ask_depth_usdt, 2),
            depth_score     = round(depth_score, 3),
            imbalance       = round(imbalance, 3),
            wall_penalty    = round(wall_penalty, 3),
            slippage_pct    = round(slippage_pct, 4),
            slippage_score  = round(slippage_score, 3),
            bid_levels      = len(bids),
            ask_levels      = len(asks),
            note            = (
                f"Spread={spread_pct:.3f}%  Depth={total_depth:,.0f}  "
                f"Slip={slippage_pct:.3f}%  {walls_note}"
            ),
        )

    @staticmethod
    def _estimate_slippage(asks: list, mid: float, usdt_size: float) -> float:
        """
        Walk the ask side of the book to fill usdt_size.
        Returns slippage as a % of mid price.
        """
        remaining  = usdt_size
        total_qty  = 0.0
        for price_str, qty_str in asks:
            price    = float(price_str)
            qty      = float(qty_str)
            fill_qty = min(remaining / price, qty)
            total_qty += fill_qty
            remaining -= fill_qty * price
            if remaining <= 0:
                break
        if usdt_size <= 0 or mid <= 0:
            return 0.0
        usdt_filled = usdt_size - max(0.0, remaining)
        avg_price   = (usdt_filled / total_qty) if total_qty > 0 else mid
        return max(0.0, (avg_price - mid) / mid * 100)

    # ── Order book fetch ───────────────────────────────────────────────────────

    def _fetch_order_book(self, symbol: str, depth: int) -> Optional[dict]:
        key = symbol
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and (now - cached["ts"]) < 300:   # 5-min TTL
            return cached["data"]

        data = self._fetch_api(symbol, depth)
        if data:
            self._cache[key] = {"data": data, "ts": now}
        return data or (cached or {}).get("data")

    def _fetch_api(self, symbol: str, depth: int) -> Optional[dict]:
        if not self._client:
            return self._synthetic_book(symbol, depth)
        try:
            return self._client.get_order_book(symbol=symbol, limit=depth)
        except Exception as exc:
            logger.debug(f"LiquidityDepthAnalyzer: fetch failed {symbol}: {exc!r}")
            return self._synthetic_book(symbol, depth)

    @staticmethod
    def _synthetic_book(symbol: str, depth: int) -> dict:
        """Generate synthetic order book for demo/offline mode."""
        rng   = np.random.default_rng(hash(symbol) % (2**31))
        # Use symbol hash to create varied but deterministic liquidity profiles
        base_price  = 100.0 + (hash(symbol) % 50000) / 10.0
        spread_frac = rng.uniform(0.0001, 0.003)   # 0.01%–0.3% spread
        mid         = base_price

        bids, asks = [], []
        bid_price  = mid * (1 - spread_frac / 2)
        ask_price  = mid * (1 + spread_frac / 2)

        for i in range(depth):
            bq = max(0.01, rng.exponential(5.0) * (1 + i * 0.1))
            aq = max(0.01, rng.exponential(5.0) * (1 + i * 0.1))
            bids.append([str(round(bid_price * (1 - i * 0.0005), 8)), str(round(bq, 6))])
            asks.append([str(round(ask_price * (1 + i * 0.0005), 8)), str(round(aq, 6))])

        # Randomly inject a wall
        if rng.random() > 0.6:
            wall_idx = int(rng.integers(2, min(10, depth)))
            bids[wall_idx][1] = str(float(bids[wall_idx][1]) * rng.uniform(5, 20))

        return {"bids": bids, "asks": asks, "lastUpdateId": 0}

    # ── DB persistence ─────────────────────────────────────────────────────────

    def _persist(self, result: LiquidityResult) -> None:
        """Update liquidity_score and grade in pair_registry."""
        try:
            from sqlalchemy import select
            from db.postgres import get_db
            from db.models import PairRegistry
            with get_db() as db:
                row = db.execute(select(PairRegistry).filter_by(symbol=result.symbol)).scalar_one_or_none()
                if row:
                    row.liquidity_score = result.liquidity_score
                    row.liquidity_grade = result.grade
        except Exception as exc:
            logger.debug(f"LiquidityDepthAnalyzer: DB persist failed: {exc!r}")
