"""
Iceberg Detector ML — Discovers hidden large orders in the Binance order book.

An iceberg order splits a large position into many small visible "slices"
to hide the true size.  Binance raised ICEBERG_PARTS from 50 → 100, meaning
a whale can now hide 100 BTC behind a 1-BTC visible bid that reappears 100 times.

Trading Logic:
  BID Iceberg (buy wall)
    → Hidden floor: price is UNLIKELY to fall below the iceberg level until the
      whale is done.  The whale is defending that price.
    → Action: FLOOR — safe entry, tight stop below iceberg price.
    → Green signal: buy near the floor, target = above where whale stops.

  ASK Iceberg (sell wall)
    → Hidden ceiling: price is UNLIKELY to break ABOVE the iceberg level until
      the full hidden order is consumed.
    → Action: CEILING — do NOT chase a breakout above this level.
    → Red/yellow signal: wait for the wall to be eaten before buying.

Detection Algorithm (polling-based, no WebSocket required):
  Every POLL_INTERVAL_SEC (default 5 s), snapshot the top-N order book levels.
  For each price level, maintain a LevelState:
    slice_qty      : the "base" visible quantity (first clean reading)
    prev_qty       : quantity at last snapshot
    consumed_total : cumulative volume filled at this level
    refill_count   : how many times the qty recovered to ~slice_qty after dropping

  A "refill" is detected when:
    1. prev_qty < slice_qty × 0.90   (at least 10% was consumed)
    2. current_qty >= slice_qty × 0.95  (quantity recovered to ≥95% of base)
    → refill_count += 1, estimated hidden total += slice_qty

Alert Levels:
  WATCH  — 3–9 refills   (iceberg confirmed, moderate size)
  ALERT  — 10–29 refills (significant hidden order)
  STRONG — 30+ refills   (potentially near the 100-part Binance limit)

Iceberg Score:
  score = 0.45 × refill_ratio          (refill_count / MAX_ICEBERG_PARTS)
        + 0.35 × min(1, hidden_usd / 500_000)  (USD size of hidden order)
        + 0.20 × persistence_score     (how long it has been active)

Constants:
  POLL_INTERVAL_SEC = 5
  MAX_ICEBERG_PARTS = 100  (Binance new limit)
  ORDER_BOOK_DEPTH  = 50   (levels to scan per side)
  WATCH_REFILLS     = 3
  ALERT_REFILLS     = 10
  STRONG_REFILLS    = 30
  LEVEL_TTL_SEC     = 300  (forget a level after 5 min of no activity)

Scans HIGH + MEDIUM priority pairs.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import numpy as np
from loguru import logger
from utils.logger import get_intel_logger


# ── Configuration ──────────────────────────────────────────────────────────────
POLL_INTERVAL_SEC = 5       # Order book snapshot every 5 seconds
MAX_ICEBERG_PARTS = 100     # Binance ICEBERG_PARTS limit (raised from 50)
ORDER_BOOK_DEPTH  = 50      # How many price levels to scan per side

WATCH_REFILLS  = 3
ALERT_REFILLS  = 10
STRONG_REFILLS = 30

LEVEL_TTL_SEC       = 300   # Forget inactive levels after 5 min
REFILL_TOLERANCE    = 0.95  # qty must recover to ≥ 95% of slice to count as refill
CONSUME_THRESHOLD   = 0.90  # qty must drop below 90% before we look for refill

SCORE_USD_CAP       = 500_000   # $500K hidden USD → max size score
MIN_SLICE_USD       = 500       # Ignore levels where visible slice < $500


@dataclass
class IcebergSignal:
    """A detected iceberg order at one price level for one symbol."""
    symbol:         str
    side:           str             # "BID" (buy wall / floor) | "ASK" (sell wall / ceiling)
    action:         str             # "FLOOR" | "CEILING"

    price:          float           # Iceberg price level
    slice_qty:      float           # Visible slice size (each refill restores to this)
    refill_count:   int             # Times the slice was refilled
    hidden_total:   float           # Estimated hidden qty: slice_qty × refill_count
    hidden_usd:     float           # Estimated USD value of hidden total
    consumed_total: float           # Total qty confirmed consumed so far

    alert_level:    str             # "WATCH" | "ALERT" | "STRONG"
    iceberg_score:  float           # 0–1 overall confidence score

    age_seconds:    float = 0.0
    last_price:     float = 0.0
    depth_rank:     int   = 0       # How close to best bid/ask (1 = top of book)

    note:           str   = ""
    signal_id:      str   = ""
    detected_at:    str   = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at:     str   = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def side_emoji(self) -> str:
        return "🟢" if self.side == "BID" else "🔴"

    @property
    def action_color(self) -> str:
        return "#00CC66" if self.action == "FLOOR" else "#FF6644"

    @property
    def alert_emoji(self) -> str:
        return {"STRONG": "🚨", "ALERT": "🔶", "WATCH": "👁"}.get(self.alert_level, "·")


class _LevelState:
    """Internal per-(symbol, side, price) state tracking."""
    __slots__ = (
        "price", "side", "slice_qty", "prev_qty",
        "refill_count", "consumed_total", "depth_rank",
        "first_ts", "last_ts", "active", "first_wall_ts",
    )

    def __init__(self, price: float, side: str, qty: float, depth_rank: int) -> None:
        self.price          = price
        self.side           = side
        self.slice_qty      = qty
        self.prev_qty       = qty
        self.refill_count   = 0
        self.consumed_total = 0.0
        self.depth_rank     = depth_rank
        self.first_ts       = time.monotonic()
        self.last_ts        = time.monotonic()
        self.active         = True
        self.first_wall_ts  = datetime.now(timezone.utc).isoformat()


class IcebergDetector:
    """
    ML-powered iceberg order detector.

    Polls the order book for each HIGH+MEDIUM pair every few seconds
    and tracks refill patterns to identify hidden large orders.

    Trading signals:
      BID iceberg → FLOOR  — whale defending this price, safe entry above it
      ASK iceberg → CEILING — whale blocking this price, wait for wall to clear

    Usage::

        detector = IcebergDetector(binance_client=client, pair_scanner=scanner)
        detector.on_alert(my_callback)
        detector.start()
        alerts = detector.get_alerts()
    """

    def __init__(
        self,
        binance_client=None,
        pair_scanner=None,
    ) -> None:
        self._client  = binance_client
        self._pairs   = pair_scanner
        self._intel   = get_intel_logger()
        self._lock    = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Per-symbol per-side per-price level state
        # Key: (symbol, side, price_bucket) → _LevelState
        self._levels: dict[tuple[str, str, float], _LevelState] = {}

        # Current IcebergSignals keyed by signal_id
        self._signals: dict[str, IcebergSignal] = {}

        # Last known price per symbol (for USD conversion)
        self._last_price: dict[str, float] = {}

        # Alert callbacks
        self._alert_callbacks: list[Callable[[list[IcebergSignal]], None]] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_alert(self, cb: Callable[[list[IcebergSignal]], None]) -> None:
        """Register callback — called with list of current IcebergSignals after each scan."""
        self._alert_callbacks.append(cb)

    def get_alerts(self, min_level: str = "WATCH") -> list[IcebergSignal]:
        """Return current alerts at or above min_level, sorted by score descending."""
        order = {"WATCH": 1, "ALERT": 2, "STRONG": 3}
        min_rank = order.get(min_level, 1)
        with self._lock:
            return sorted(
                [s for s in self._signals.values()
                 if order.get(s.alert_level, 0) >= min_rank],
                key=lambda s: -s.iceberg_score,
            )

    def get_all(self) -> list[IcebergSignal]:
        with self._lock:
            return sorted(self._signals.values(), key=lambda s: -s.iceberg_score)

    def get_floors(self) -> list[IcebergSignal]:
        """Return BID icebergs (price floors) sorted by score."""
        with self._lock:
            return sorted(
                [s for s in self._signals.values() if s.side == "BID"],
                key=lambda s: -s.iceberg_score,
            )

    def get_ceilings(self) -> list[IcebergSignal]:
        """Return ASK icebergs (price ceilings) sorted by score."""
        with self._lock:
            return sorted(
                [s for s in self._signals.values() if s.side == "ASK"],
                key=lambda s: -s.iceberg_score,
            )

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="iceberg-detector"
        )
        self._thread.start()
        self._intel.ml(
            "IcebergDetector",
            f"Started — polling order books every {POLL_INTERVAL_SEC}s  "
            f"(Binance ICEBERG_PARTS={MAX_ICEBERG_PARTS})"
        )

    def stop(self) -> None:
        self._running = False

    # ── Background loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(8)   # brief startup delay
        while self._running:
            t0 = time.monotonic()
            try:
                self._scan()
            except Exception as exc:
                logger.warning(f"IcebergDetector scan error: {exc!r}")
            elapsed = time.monotonic() - t0
            time.sleep(max(0.5, POLL_INTERVAL_SEC - elapsed))

    def _scan(self) -> None:
        """Poll order books for all candidates and update level states."""
        candidates = self._get_candidates()
        now = time.monotonic()
        new_signals: dict[str, IcebergSignal] = {}

        for sym in candidates:
            if not self._running:
                break
            try:
                book = self._fetch_order_book(sym, ORDER_BOOK_DEPTH)
                if not book:
                    continue
                bids = book.get("bids", [])
                asks = book.get("asks", [])
                last_px = self._last_price.get(sym, 0.0)
                if not last_px and bids:
                    last_px = float(bids[0][0])
                self._last_price[sym] = last_px

                self._process_side(sym, "BID", bids, last_px, now)
                self._process_side(sym, "ASK", asks, last_px, now)

            except Exception as exc:
                logger.debug(f"IcebergDetector: {sym} failed: {exc!r}")

        # Prune stale levels
        stale_keys = [
            k for k, v in self._levels.items()
            if now - v.last_ts > LEVEL_TTL_SEC
        ]
        for k in stale_keys:
            del self._levels[k]

        # Build current signals from active levels with ≥ WATCH_REFILLS
        for key, state in self._levels.items():
            if state.refill_count < WATCH_REFILLS:
                continue
            sym, side, price = key
            sig = self._build_signal(sym, side, price, state, now)
            if sig:
                new_signals[sig.signal_id] = sig

        with self._lock:
            self._signals = new_signals

        if new_signals:
            floors   = sum(1 for s in new_signals.values() if s.side == "BID")
            ceilings = sum(1 for s in new_signals.values() if s.side == "ASK")
            strong   = sum(1 for s in new_signals.values() if s.alert_level == "STRONG")
            self._intel.ml(
                "IcebergDetector",
                f"Icebergs: {len(new_signals)} total  "
                f"FLOOR={floors}  CEILING={ceilings}  STRONG={strong}",
            )

        # Fire callbacks
        if new_signals:
            ranked = sorted(new_signals.values(), key=lambda s: -s.iceberg_score)
            for cb in self._alert_callbacks:
                try:
                    cb(ranked)
                except Exception as exc:
                    logger.warning(f"IcebergDetector callback error: {exc!r}")

    def _process_side(
        self,
        symbol:    str,
        side:      str,
        levels:    list,
        last_px:   float,
        now:       float,
    ) -> None:
        """Process one side (BID or ASK) of an order book snapshot."""
        active_prices: set[float] = set()

        for rank, entry in enumerate(levels[:ORDER_BOOK_DEPTH], 1):
            try:
                price = float(entry[0])
                qty   = float(entry[1])
            except (IndexError, ValueError):
                continue

            if qty < 1e-12:
                continue

            # USD value filter — skip tiny levels
            slice_usd = qty * (last_px if last_px > 0 else price)
            if slice_usd < MIN_SLICE_USD:
                continue

            price_bucket = round(price, 8)   # stable key
            key = (symbol, side, price_bucket)
            active_prices.add(price_bucket)

            if key not in self._levels:
                # New level — initialise state
                self._levels[key] = _LevelState(price_bucket, side, qty, rank)
            else:
                state = self._levels[key]
                state.last_ts   = now
                state.active    = True
                state.depth_rank = rank

                prev = state.prev_qty

                # Track consumed volume incrementally (decreasing qty)
                if qty < prev:
                    state.consumed_total += (prev - qty)

                # Detect refill: qty was significantly lower last snapshot, now recovered.
                # consumed_total already tracked the drop incrementally — no double-add.
                if (prev < state.slice_qty * CONSUME_THRESHOLD and
                        qty >= state.slice_qty * REFILL_TOLERANCE):
                    state.refill_count += 1

                state.prev_qty = qty

        # Mark levels no longer in the book as inactive
        for k in list(self._levels.keys()):
            sym2, side2, price2 = k
            if sym2 == symbol and side2 == side and price2 not in active_prices:
                self._levels[k].active = False

    def _build_signal(
        self,
        symbol:  str,
        side:    str,
        price:   float,
        state:   _LevelState,
        now:     float,
    ) -> Optional[IcebergSignal]:
        """Convert a LevelState into an IcebergSignal dataclass."""
        last_px = self._last_price.get(symbol, price)
        if last_px < 1e-12:
            last_px = price

        hidden_total = state.slice_qty * state.refill_count
        hidden_usd   = hidden_total * last_px

        if state.refill_count >= STRONG_REFILLS:
            alert_level = "STRONG"
        elif state.refill_count >= ALERT_REFILLS:
            alert_level = "ALERT"
        else:
            alert_level = "WATCH"

        # Score components
        refill_ratio     = min(1.0, state.refill_count / MAX_ICEBERG_PARTS)
        size_sub         = min(1.0, hidden_usd / SCORE_USD_CAP)
        age_secs         = now - state.first_ts
        persistence_sub  = min(1.0, age_secs / 1800)   # max at 30 min
        iceberg_score    = round(
            0.45 * refill_ratio + 0.35 * size_sub + 0.20 * persistence_sub, 4
        )

        action = "FLOOR" if side == "BID" else "CEILING"

        # Direction relative to current price
        if side == "BID":
            pct_from_best = (price - last_px) / last_px * 100.0
            note_dir = f"BID FLOOR @ {price:.6g}  "
            note_dir += f"({pct_from_best:+.2f}% from current)"
        else:
            pct_from_best = (price - last_px) / last_px * 100.0
            note_dir = f"ASK CEILING @ {price:.6g}  "
            note_dir += f"({pct_from_best:+.2f}% from current)"

        note = (
            f"{note_dir}  "
            f"Slice={state.slice_qty:.4g}  "
            f"Refills={state.refill_count}  "
            f"Hidden≈{hidden_total:.4g} (${hidden_usd:,.0f})"
        )

        signal_id = f"{symbol}_{side}_{price:.8f}"

        return IcebergSignal(
            symbol         = symbol,
            side           = side,
            action         = action,
            price          = price,
            slice_qty      = round(state.slice_qty, 8),
            refill_count   = state.refill_count,
            hidden_total   = round(hidden_total, 4),
            hidden_usd     = round(hidden_usd, 2),
            consumed_total = round(state.consumed_total, 4),
            alert_level    = alert_level,
            iceberg_score  = iceberg_score,
            age_seconds    = round(age_secs, 1),
            last_price     = round(last_px, 8),
            depth_rank     = state.depth_rank,
            note           = note,
            signal_id      = signal_id,
            detected_at    = state.first_wall_ts,
            updated_at     = datetime.now(timezone.utc).isoformat(),
        )

    # ── Candidates ─────────────────────────────────────────────────────────────

    def _get_candidates(self) -> list[str]:
        if self._pairs:
            try:
                high = self._pairs.get_pairs_by_priority("HIGH")
                # Limit to top 30 HIGH pairs to avoid hammering the API
                return [p.symbol for p in high[:30]]
            except Exception:
                pass
        return [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
            "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
        ]

    # ── Order book fetch ───────────────────────────────────────────────────────

    def _fetch_order_book(self, symbol: str, limit: int) -> dict:
        if not self._client:
            return self._synthetic_book(symbol, limit)
        try:
            book = self._client.get_order_book(symbol=symbol, limit=limit)
            if isinstance(book, dict) and "bids" in book:
                return book
        except Exception as exc:
            logger.debug(f"IcebergDetector: book fetch {symbol}: {exc!r}")
        return self._synthetic_book(symbol, limit)

    @staticmethod
    def _synthetic_book(symbol: str, limit: int) -> dict:
        """
        Generate a synthetic order book with embedded iceberg patterns for demo/offline mode.

        Every ~20 calls we inject a refill (qty resets) at a specific price level
        to simulate an iceberg being detected.
        """
        rng  = np.random.default_rng(hash(symbol + str(int(time.time() / 5))) % (2 ** 31))
        seed = np.random.default_rng(hash(symbol) % (2 ** 31))

        base_price = {
            "BTCUSDT": 65000.0, "ETHUSDT": 3500.0, "BNBUSDT": 580.0,
            "SOLUSDT": 180.0,   "XRPUSDT": 0.65,  "ADAUSDT": 0.48,
        }.get(symbol, 10.0)

        bids = []
        asks = []
        spread_pct = 0.0002   # 0.02% spread

        # Best bid / ask
        best_bid = base_price * (1 - spread_pct / 2) * (1 + rng.normal(0, 0.0001))
        best_ask = base_price * (1 + spread_pct / 2) * (1 + rng.normal(0, 0.0001))

        # Decide if this symbol has an iceberg level (persistent across calls via seed)
        has_bid_iceberg = bool(seed.integers(0, 2))
        has_ask_iceberg = bool(seed.integers(0, 2))

        # Iceberg levels (fixed relative to base price, changes slowly)
        iceberg_bid_price = round(base_price * seed.uniform(0.985, 0.998), 2)
        iceberg_ask_price = round(base_price * seed.uniform(1.002, 1.015), 2)
        iceberg_slice_qty = round(seed.uniform(0.5, 5.0), 3)

        # Fixed depth index for the iceberg level (repeatable via seed)
        iceberg_bid_rank = int(seed.integers(3, 10))   # depth 3–9 from top
        iceberg_ask_rank = int(seed.integers(3, 10))

        for i in range(limit):
            tick = base_price * 0.0001 * (i + 1)

            bid_px = round(best_bid - tick * (1 + rng.uniform(0, 0.5)), 6)
            ask_px = round(best_ask + tick * (1 + rng.uniform(0, 0.5)), 6)

            # Normal quantities
            bid_qty = round(rng.uniform(0.05, 2.0), 4)
            ask_qty = round(rng.uniform(0.05, 2.0), 4)

            # Inject iceberg at a fixed rank so the price key is stable across calls.
            # Phase 0→1: full slice → partial (consumed), Phase 2: refilled.
            # This reliably triggers refill detection every 3 polls (15 s).
            if has_bid_iceberg and i == iceberg_bid_rank:
                phase = int(time.time() / 5) % 3
                if phase == 1:
                    bid_qty = round(iceberg_slice_qty * 0.3, 4)   # partially filled
                else:
                    bid_qty = round(iceberg_slice_qty, 4)          # full / refilled
                bid_px = iceberg_bid_price                         # fixed price

            if has_ask_iceberg and i == iceberg_ask_rank:
                phase = int(time.time() / 5) % 3
                if phase == 1:
                    ask_qty = round(iceberg_slice_qty * 0.25, 4)  # partially filled
                else:
                    ask_qty = round(iceberg_slice_qty, 4)          # full / refilled
                ask_px = iceberg_ask_price                         # fixed price

            bids.append([str(bid_px), str(bid_qty)])
            asks.append([str(ask_px), str(ask_qty)])

        return {"bids": bids, "asks": asks}
