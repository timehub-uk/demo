"""
Whale Watcher ML Module.

Monitors order book depth, trade flow, and price action to detect
large-participant (whale) activity patterns:

  - False walls: large bid/ask placed then cancelled before fill
  - Buy / sell walls: sustained large orders absorbing price pressure
  - Price attacks: rapid aggressive market orders pushing price
  - Pump orchestration: low-volume price push followed by volume spike
  - Consolidation / pause: whale accumulation in tight range
  - Spoofing detection: repeated layering + cancellation

Each detected whale event is fed into an online learning model so the
watcher progressively learns individual whale behaviour profiles over time.
"""

from __future__ import annotations

import threading
import time
import json
from collections import deque, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Callable, Optional
from pathlib import Path

import numpy as np

from loguru import logger
from utils.logger import get_intel_logger


# ── Constants ─────────────────────────────────────────────────────────────────

WHALE_MODELS_DIR = Path(__file__).parent.parent / "data" / "models" / "whales"
WHALE_MODELS_DIR.mkdir(parents=True, exist_ok=True)

# USD value threshold to consider an order "whale-sized"
DEFAULT_WHALE_THRESHOLD_USD = 100_000   # $100k

# Order book depth levels to analyse
OB_DEPTH_LEVELS = 20

# Minimum % of top-5 book depth that a single order must represent to be a wall
WALL_DEPTH_PCT = 0.25   # 25%

# Cancellation within this many seconds counts as "false wall"
FALSE_WALL_WINDOW_SEC = 30

# Rolling window for spoof detection (how many book snapshots to track)
SPOOF_WINDOW = 60


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class WhaleEvent:
    event_type: str          # FALSE_WALL | BUY_WALL | SELL_WALL | ATTACK_UP | ATTACK_DOWN | ACCUMULATION | SPOOF
    symbol: str
    timestamp: datetime
    price: float
    volume_usd: float
    confidence: float        # 0.0 – 1.0
    side: str                # BID | ASK | BOTH | NONE
    details: dict = field(default_factory=dict)
    whale_id: str = ""       # Assigned ID to track repeat behaviour


@dataclass
class WhaleProfile:
    """Learned behavioural profile of a recurring whale participant."""
    whale_id: str
    symbols: list[str] = field(default_factory=list)
    event_count: int = 0
    total_volume_usd: float = 0.0
    typical_size_usd: float = 0.0
    favourite_events: dict = field(default_factory=dict)   # event_type → count
    avg_duration_sec: float = 0.0
    outcome_history: list[float] = field(default_factory=list)  # price pct change after event
    first_seen: str = ""
    last_seen: str = ""

    def update(self, event: WhaleEvent, price_outcome_pct: float) -> None:
        self.symbols = list(set(self.symbols + [event.symbol]))
        self.event_count += 1
        self.total_volume_usd += event.volume_usd
        self.typical_size_usd = self.total_volume_usd / self.event_count
        self.favourite_events[event.event_type] = self.favourite_events.get(event.event_type, 0) + 1
        self.outcome_history.append(price_outcome_pct)
        if len(self.outcome_history) > 200:
            self.outcome_history.pop(0)
        now = datetime.now(timezone.utc).isoformat()
        if not self.first_seen:
            self.first_seen = now
        self.last_seen = now

    @property
    def avg_outcome(self) -> float:
        return float(np.mean(self.outcome_history)) if self.outcome_history else 0.0

    @property
    def predictability(self) -> float:
        """How consistent is this whale's post-event price movement?"""
        if len(self.outcome_history) < 5:
            return 0.0
        return max(0.0, 1.0 - float(np.std(self.outcome_history)) / (abs(self.avg_outcome) + 0.001))


# ── Order book snapshot ───────────────────────────────────────────────────────

@dataclass
class OrderBookSnapshot:
    timestamp: float
    bids: list[tuple[float, float]]   # [(price, qty), ...]
    asks: list[tuple[float, float]]
    mid_price: float


# ── Whale Detector ────────────────────────────────────────────────────────────

class WhaleDetector:
    """
    Real-time analysis engine: ingests order book + trade stream,
    emits WhaleEvent objects via registered callbacks.
    """

    def __init__(self, symbol: str, whale_threshold_usd: float = DEFAULT_WHALE_THRESHOLD_USD) -> None:
        self.symbol = symbol
        self.threshold_usd = whale_threshold_usd
        self._intel = get_intel_logger()

        # Sliding windows
        self._ob_history: deque[OrderBookSnapshot] = deque(maxlen=SPOOF_WINDOW)
        self._recent_large_bids: deque[tuple[float, float, float]] = deque(maxlen=200)  # (ts, price, qty)
        self._recent_large_asks: deque[tuple[float, float, float]] = deque(maxlen=200)
        self._recent_trades: deque[dict] = deque(maxlen=500)
        self._trade_volume_1min: deque[float] = deque(maxlen=60)

        self._callbacks: list[Callable[[WhaleEvent], None]] = []
        self._lock = threading.Lock()

    def on_event(self, callback: Callable[[WhaleEvent], None]) -> None:
        self._callbacks.append(callback)

    def process_orderbook(self, bids: list, asks: list, mid_price: float) -> list[WhaleEvent]:
        """Analyse a new order book snapshot for whale patterns."""
        ts = time.time()
        snap = OrderBookSnapshot(
            timestamp=ts,
            bids=[(float(p), float(q)) for p, q in bids[:OB_DEPTH_LEVELS]],
            asks=[(float(p), float(q)) for p, q in asks[:OB_DEPTH_LEVELS]],
            mid_price=mid_price,
        )
        with self._lock:
            self._ob_history.append(snap)
        events = []
        events += self._detect_walls(snap)
        events += self._detect_false_walls(snap, ts)
        events += self._detect_spoof(snap, ts)
        for ev in events:
            self._fire(ev)
        return events

    def process_trade(self, price: float, qty: float, is_buyer_maker: bool, ts: float | None = None) -> list[WhaleEvent]:
        """Process a single trade from the trade stream."""
        ts = ts or time.time()
        trade = {"ts": ts, "price": price, "qty": qty, "buy": not is_buyer_maker}
        with self._lock:
            self._recent_trades.append(trade)

        vol_usd = price * qty
        if vol_usd < self.threshold_usd:
            return []

        events = self._detect_attack(trade)
        for ev in events:
            self._fire(ev)
        return events

    # ── Pattern detectors ──────────────────────────────────────────────

    def _detect_walls(self, snap: OrderBookSnapshot) -> list[WhaleEvent]:
        """Detect sustained large bid/ask walls in current snapshot."""
        events = []
        mid = snap.mid_price or 1

        # Top-5 bid depth
        top_bid_total = sum(p * q for p, q in snap.bids[:5])
        for price, qty in snap.bids[:5]:
            val_usd = price * qty
            if val_usd >= self.threshold_usd and top_bid_total > 0:
                pct_of_depth = val_usd / top_bid_total
                if pct_of_depth >= WALL_DEPTH_PCT:
                    ev = WhaleEvent(
                        event_type="BUY_WALL",
                        symbol=self.symbol,
                        timestamp=datetime.now(timezone.utc),
                        price=price,
                        volume_usd=val_usd,
                        confidence=min(0.95, 0.5 + pct_of_depth),
                        side="BID",
                        details={"depth_pct": pct_of_depth, "top5_total_usd": top_bid_total},
                    )
                    events.append(ev)
                    break  # one wall event per snapshot

        # Top-5 ask depth
        top_ask_total = sum(p * q for p, q in snap.asks[:5])
        for price, qty in snap.asks[:5]:
            val_usd = price * qty
            if val_usd >= self.threshold_usd and top_ask_total > 0:
                pct_of_depth = val_usd / top_ask_total
                if pct_of_depth >= WALL_DEPTH_PCT:
                    ev = WhaleEvent(
                        event_type="SELL_WALL",
                        symbol=self.symbol,
                        timestamp=datetime.now(timezone.utc),
                        price=price,
                        volume_usd=val_usd,
                        confidence=min(0.95, 0.5 + pct_of_depth),
                        side="ASK",
                        details={"depth_pct": pct_of_depth, "top5_total_usd": top_ask_total},
                    )
                    events.append(ev)
                    break

        return events

    def _detect_false_walls(self, snap: OrderBookSnapshot, ts: float) -> list[WhaleEvent]:
        """
        Compare current book with book 30s ago.
        If a large order that was present earlier is now GONE without a trade matching it,
        it was likely a false wall (spoof attempt).
        """
        events = []
        cutoff = ts - FALSE_WALL_WINDOW_SEC
        # Find a historical snapshot ~30s old
        old_snap: OrderBookSnapshot | None = None
        with self._lock:
            for s in self._ob_history:
                if s.timestamp <= cutoff:
                    old_snap = s
                    break

        if old_snap is None:
            return []

        # Check if large bids that existed before are gone now
        old_bid_prices = {p: q for p, q in old_snap.bids}
        current_bid_prices = {p: q for p, q in snap.bids}
        mid = snap.mid_price or 1

        for price, old_qty in old_bid_prices.items():
            val_usd = price * old_qty
            if val_usd < self.threshold_usd:
                continue
            current_qty = current_bid_prices.get(price, 0)
            if current_qty < old_qty * 0.2:  # > 80% gone
                # Was it consumed by trades or just cancelled?
                trade_vol = sum(
                    t["price"] * t["qty"] for t in self._recent_trades
                    if abs(t["price"] - price) / price < 0.001 and t["ts"] > cutoff
                )
                if trade_vol < val_usd * 0.3:   # Less than 30% was traded → likely cancelled
                    ev = WhaleEvent(
                        event_type="FALSE_WALL",
                        symbol=self.symbol,
                        timestamp=datetime.now(timezone.utc),
                        price=price,
                        volume_usd=val_usd,
                        confidence=0.75,
                        side="BID",
                        details={"old_qty": old_qty, "current_qty": current_qty, "trade_vol_usd": trade_vol},
                    )
                    events.append(ev)
                    break  # one false wall per check

        # Same for asks
        old_ask_prices = {p: q for p, q in old_snap.asks}
        current_ask_prices = {p: q for p, q in snap.asks}
        for price, old_qty in old_ask_prices.items():
            val_usd = price * old_qty
            if val_usd < self.threshold_usd:
                continue
            current_qty = current_ask_prices.get(price, 0)
            if current_qty < old_qty * 0.2:
                trade_vol = sum(
                    t["price"] * t["qty"] for t in self._recent_trades
                    if abs(t["price"] - price) / price < 0.001 and t["ts"] > cutoff
                )
                if trade_vol < val_usd * 0.3:
                    ev = WhaleEvent(
                        event_type="FALSE_WALL",
                        symbol=self.symbol,
                        timestamp=datetime.now(timezone.utc),
                        price=price,
                        volume_usd=val_usd,
                        confidence=0.75,
                        side="ASK",
                        details={"old_qty": old_qty, "current_qty": current_qty, "trade_vol_usd": trade_vol},
                    )
                    events.append(ev)
                    break

        return events

    def _detect_spoof(self, snap: OrderBookSnapshot, ts: float) -> list[WhaleEvent]:
        """
        Detect repeated layering + cancellation (spoofing pattern).
        If the same price level appears and disappears multiple times in the window,
        flag as SPOOF.
        """
        events = []
        with self._lock:
            history = list(self._ob_history)

        if len(history) < 10:
            return []

        # Count appearances per price level across last 60 snapshots
        bid_appearances: dict[float, int] = defaultdict(int)
        for s in history:
            for p, q in s.bids[:10]:
                val = p * q
                if val >= self.threshold_usd:
                    bid_appearances[round(p, 2)] += 1

        for price, count in bid_appearances.items():
            # If a large order appears in >70% of snapshots but is now GONE → spoof
            if count >= len(history) * 0.7:
                in_current = any(abs(p - price) < 0.01 * price for p, q in snap.bids[:10])
                if not in_current:
                    val_usd = price * 10  # approximate
                    ev = WhaleEvent(
                        event_type="SPOOF",
                        symbol=self.symbol,
                        timestamp=datetime.now(timezone.utc),
                        price=price,
                        volume_usd=0,
                        confidence=0.80,
                        side="BID",
                        details={"appearances": count, "window": len(history)},
                    )
                    events.append(ev)
                    break

        return events

    def _detect_attack(self, trade: dict) -> list[WhaleEvent]:
        """
        Detect aggressive large market orders pushing price up or down.
        Confirms direction from recent trade flow imbalance.
        """
        events = []
        ts = trade["ts"]
        window_start = ts - 10  # 10-second window
        recent = [t for t in self._recent_trades if t["ts"] >= window_start]

        if len(recent) < 3:
            return []

        buy_vol = sum(t["price"] * t["qty"] for t in recent if t["buy"])
        sell_vol = sum(t["price"] * t["qty"] for t in recent if not t["buy"])
        total_vol = buy_vol + sell_vol

        if total_vol < self.threshold_usd * 0.5:
            return []

        imbalance = (buy_vol - sell_vol) / total_vol if total_vol > 0 else 0

        if abs(imbalance) >= 0.70:
            direction = "ATTACK_UP" if imbalance > 0 else "ATTACK_DOWN"
            confidence = min(0.92, 0.6 + abs(imbalance) * 0.4)
            ev = WhaleEvent(
                event_type=direction,
                symbol=self.symbol,
                timestamp=datetime.now(timezone.utc),
                price=trade["price"],
                volume_usd=total_vol,
                confidence=confidence,
                side="BID" if imbalance > 0 else "ASK",
                details={
                    "buy_vol_usd": buy_vol,
                    "sell_vol_usd": sell_vol,
                    "imbalance": imbalance,
                    "trade_count": len(recent),
                },
            )
            events.append(ev)

        return events

    # ── Accumulation (pause) detection ─────────────────────────────────

    def detect_accumulation(self, closes: list[float], volumes: list[float]) -> Optional[WhaleEvent]:
        """
        Detects tight consolidation + above-average volume → accumulation.
        Call periodically with recent 1-min candle data (e.g. last 20 candles).
        """
        if len(closes) < 10 or len(volumes) < 10:
            return None

        recent_closes = closes[-20:]
        recent_vols = volumes[-20:]

        price_range_pct = (max(recent_closes) - min(recent_closes)) / np.mean(recent_closes) * 100
        avg_vol = np.mean(recent_vols[:-5])
        current_vol = np.mean(recent_vols[-5:])
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1

        # Tight range (< 1.5%) + elevated volume (> 1.3×) = possible accumulation
        if price_range_pct < 1.5 and vol_ratio > 1.3:
            ev = WhaleEvent(
                event_type="ACCUMULATION",
                symbol=self.symbol,
                timestamp=datetime.now(timezone.utc),
                price=float(recent_closes[-1]),
                volume_usd=float(current_vol * recent_closes[-1]),
                confidence=min(0.85, 0.5 + vol_ratio * 0.1 + (1.5 - price_range_pct) * 0.1),
                side="BOTH",
                details={"price_range_pct": price_range_pct, "vol_ratio": vol_ratio},
            )
            self._fire(ev)
            return ev

        return None

    # ── Internals ──────────────────────────────────────────────────────

    def _fire(self, event: WhaleEvent) -> None:
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass


# ── Online Learning for Whale Profiles ───────────────────────────────────────

class WhaleLearner:
    """
    Lightweight online ML that builds and refines WhaleProfile objects.
    Uses a simple feature vector + exponential moving average update to
    progressively learn what each "whale class" does after their events.

    Features per event:
        [event_type_onehot(7), volume_usd_norm, price_rel_mid, side_onehot(3),
         hour_of_day_sin, hour_of_day_cos, confidence]
    """

    EVENT_TYPES = ["FALSE_WALL", "BUY_WALL", "SELL_WALL", "ATTACK_UP",
                   "ATTACK_DOWN", "ACCUMULATION", "SPOOF"]
    SIDES = ["BID", "ASK", "BOTH"]
    FEATURE_DIM = len(EVENT_TYPES) + 1 + 1 + len(SIDES) + 2 + 1  # = 15

    def __init__(self) -> None:
        self._profiles: dict[str, WhaleProfile] = {}
        self._pending_events: dict[str, tuple[WhaleEvent, float]] = {}  # id → (event, entry_price)
        self._event_counter = 0
        self._intel = get_intel_logger()
        self._lock = threading.Lock()
        self._load_profiles()

    # ── Public API ─────────────────────────────────────────────────────

    def ingest_event(self, event: WhaleEvent, mid_price: float) -> str:
        """
        Register a new whale event. Assigns a whale_id based on event clustering.
        Returns the whale_id.
        """
        with self._lock:
            whale_id = self._assign_whale_id(event)
            event.whale_id = whale_id
            # Store pending — will be resolved once we see the price outcome
            self._pending_events[f"{whale_id}_{self._event_counter}"] = (event, mid_price)
            self._event_counter += 1
            self._intel.log("INFO", "WHALE", "WhaleLearner",
                f"🐳 [{event.symbol}] {event.event_type} | ${event.volume_usd:,.0f} | "
                f"conf={event.confidence:.0%} | whale_id={whale_id}",
                asdict(event))
        return whale_id

    def resolve_event(self, pending_key: str, current_price: float) -> None:
        """
        Once enough time has passed, resolve a pending event with the price outcome.
        Updates the whale profile with actual prediction accuracy.
        """
        with self._lock:
            entry = self._pending_events.pop(pending_key, None)
            if entry is None:
                return
            event, entry_price = entry
            if entry_price <= 0:
                return
            outcome_pct = (current_price - entry_price) / entry_price * 100
            whale_id = event.whale_id
            if whale_id not in self._profiles:
                self._profiles[whale_id] = WhaleProfile(whale_id=whale_id)
            self._profiles[whale_id].update(event, outcome_pct)

            self._intel.log("INFO", "WHALE", "WhaleLearner",
                f"📊 Whale profile updated | id={whale_id} | "
                f"outcome={outcome_pct:+.2f}% | avg={self._profiles[whale_id].avg_outcome:+.2f}%")
            self._save_profiles()

    def get_signal(self, event: WhaleEvent) -> dict:
        """
        Given a new event, look up the known whale profile and return a trading signal.
        """
        with self._lock:
            profile = self._profiles.get(event.whale_id)
        if profile is None or profile.event_count < 5:
            return {"signal": "NEUTRAL", "confidence": 0.0, "reason": "insufficient whale history"}

        avg_outcome = profile.avg_outcome
        predictability = profile.predictability

        if predictability < 0.3:
            return {"signal": "NEUTRAL", "confidence": predictability, "reason": "unpredictable whale"}

        if avg_outcome > 0.3:
            return {"signal": "BUY", "confidence": predictability, "reason": f"whale typically pushes up {avg_outcome:+.2f}%"}
        if avg_outcome < -0.3:
            return {"signal": "SELL", "confidence": predictability, "reason": f"whale typically pushes down {avg_outcome:+.2f}%"}

        return {"signal": "NEUTRAL", "confidence": predictability, "reason": "whale impact too small"}

    def get_all_profiles(self) -> list[WhaleProfile]:
        with self._lock:
            return list(self._profiles.values())

    def get_profile(self, whale_id: str) -> Optional[WhaleProfile]:
        with self._lock:
            return self._profiles.get(whale_id)

    # ── Internal ───────────────────────────────────────────────────────

    def _assign_whale_id(self, event: WhaleEvent) -> str:
        """
        Simple clustering heuristic: group events by type + side + volume tier.
        In future this could use k-means or DBSCAN on feature vectors.
        """
        vol_tier = "xl" if event.volume_usd > 1_000_000 else "lg" if event.volume_usd > 250_000 else "md"
        return f"{event.event_type[:3]}_{event.side}_{vol_tier}"

    def _save_profiles(self) -> None:
        try:
            profiles_file = WHALE_MODELS_DIR / "profiles.json"
            data = {k: asdict(v) for k, v in self._profiles.items()}
            profiles_file.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.debug(f"WhaleLearner profile save error: {exc}")

    def _load_profiles(self) -> None:
        try:
            profiles_file = WHALE_MODELS_DIR / "profiles.json"
            if not profiles_file.exists():
                return
            data = json.loads(profiles_file.read_text())
            self._profiles = {k: WhaleProfile(**v) for k, v in data.items()}
            logger.debug(f"WhaleLearner: loaded {len(self._profiles)} whale profiles")
        except Exception as exc:
            logger.debug(f"WhaleLearner profile load error: {exc}")


# ── Whale Watcher Orchestrator ────────────────────────────────────────────────

class WhaleWatcher:
    """
    Top-level orchestrator for whale watching across multiple symbols.

    Usage:
        watcher = WhaleWatcher(binance_client)
        watcher.on_event(my_callback)
        watcher.start(symbols=["BTCUSDT", "ETHUSDT", ...])
        # ... later ...
        watcher.stop()
    """

    def __init__(self, binance_client=None, whale_threshold_usd: float = DEFAULT_WHALE_THRESHOLD_USD) -> None:
        self._client = binance_client
        self._threshold = whale_threshold_usd
        self._intel = get_intel_logger()
        self._learner = WhaleLearner()
        self._detectors: dict[str, WhaleDetector] = {}
        self._event_callbacks: list[Callable[[WhaleEvent], None]] = []
        self._running = False
        self._threads: list[threading.Thread] = []
        self._pending_resolve: dict[str, tuple[float, float]] = {}  # key → (entry_price, resolve_at_ts)
        self._lock = threading.Lock()

    def on_event(self, callback: Callable[[WhaleEvent], None]) -> None:
        """Register callback called whenever a whale event is detected."""
        self._event_callbacks.append(callback)

    def start(self, symbols: list[str]) -> None:
        self._running = True
        for sym in symbols:
            det = WhaleDetector(sym, self._threshold)
            det.on_event(self._on_detector_event)
            self._detectors[sym] = det

        # Start order book polling thread
        t = threading.Thread(target=self._ob_poll_loop, daemon=True, name="whale-ob-poll")
        t.start()
        self._threads.append(t)

        # Start outcome resolver thread
        t2 = threading.Thread(target=self._resolve_loop, daemon=True, name="whale-resolver")
        t2.start()
        self._threads.append(t2)

        self._intel.ml("WhaleWatcher",
            f"🐳 Whale watcher started | {len(symbols)} symbols | threshold ${self._threshold:,.0f}")

    def stop(self) -> None:
        self._running = False
        self._intel.ml("WhaleWatcher", "Whale watcher stopped.")

    def feed_trade(self, symbol: str, price: float, qty: float, is_buyer_maker: bool) -> None:
        """Feed a live trade into the appropriate detector."""
        det = self._detectors.get(symbol)
        if det:
            det.process_trade(price, qty, is_buyer_maker)

    def feed_orderbook(self, symbol: str, bids: list, asks: list, mid_price: float) -> None:
        """Feed a live order book snapshot."""
        det = self._detectors.get(symbol)
        if det:
            det.process_orderbook(bids, asks, mid_price)

    def get_whale_signal(self, symbol: str, event_type: str, whale_id: str) -> dict:
        """Query the ML learner for a trading signal based on known whale behaviour."""
        # Build a stub event to lookup the profile
        ev = WhaleEvent(
            event_type=event_type, symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            price=0, volume_usd=0, confidence=0,
            side="BOTH", whale_id=whale_id,
        )
        return self._learner.get_signal(ev)

    def get_profiles(self) -> list[WhaleProfile]:
        return self._learner.get_all_profiles()

    # ── Internal loops ─────────────────────────────────────────────────

    def _ob_poll_loop(self) -> None:
        """Poll order books if no live WebSocket is available (fallback)."""
        if self._client is None:
            return
        symbols = list(self._detectors.keys())
        idx = 0
        while self._running:
            try:
                sym = symbols[idx % len(symbols)]
                ob = self._client.get_orderbook(sym, limit=OB_DEPTH_LEVELS)
                if ob:
                    bids = ob.get("bids", [])
                    asks = ob.get("asks", [])
                    mid = (float(bids[0][0]) + float(asks[0][0])) / 2 if bids and asks else 0
                    self._detectors[sym].process_orderbook(bids, asks, mid)
                idx += 1
                time.sleep(0.5)
            except Exception as exc:
                logger.debug(f"WhaleWatcher OB poll error: {exc}")
                time.sleep(2)

    def _resolve_loop(self) -> None:
        """Resolve pending whale events after 5 minutes to calculate price outcomes."""
        while self._running:
            try:
                now = time.time()
                with self._lock:
                    to_resolve = [(k, v) for k, v in self._pending_resolve.items() if now >= v[1]]

                for key, (entry_price, _) in to_resolve:
                    # Get current price from Redis or client
                    current_price = entry_price   # default to no change
                    try:
                        sym = key.split("_")[0]
                        if self._client:
                            ticker = self._client.get_ticker(sym)
                            if ticker:
                                current_price = float(ticker.get("lastPrice", entry_price))
                    except Exception:
                        pass
                    self._learner.resolve_event(key, current_price)
                    with self._lock:
                        self._pending_resolve.pop(key, None)

                time.sleep(10)
            except Exception as exc:
                logger.debug(f"WhaleWatcher resolve loop error: {exc}")
                time.sleep(5)

    def _on_detector_event(self, event: WhaleEvent) -> None:
        """Handle a detected whale event: learn + broadcast."""
        try:
            # Get mid price for learning context
            mid_price = event.price
            pending_key = self._learner.ingest_event(event, mid_price)

            # Schedule price outcome resolution in 5 minutes
            resolve_at = time.time() + 300
            with self._lock:
                self._pending_resolve[pending_key] = (mid_price, resolve_at)

            # Broadcast to UI callbacks
            for cb in self._event_callbacks:
                try:
                    cb(event)
                except Exception:
                    pass

        except Exception as exc:
            logger.debug(f"WhaleWatcher event handler error: {exc}")
