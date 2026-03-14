"""
Forecast Tracker – Record, Evaluate, and Score AI Price Predictions.

Every time the chart's AI Forecast overlay is drawn, a ForecastRecord is
stored here.  A background thread evaluates each record once its horizon
has elapsed by fetching the current price from Redis.

After evaluation the record is marked correct or incorrect and accuracy
statistics are maintained per (symbol, interval, horizon_bars).

Public accuracy question: "For this symbol on this timeframe, how many of
the last 50 forecasts with a 20-bar horizon were correct?"

Horizon reliability guide (from empirical crypto ML literature):
  ≤5  bars  → ~60-68% achievable with strong models
  ≤20 bars  → ~55-62%
  ≤50 bars  → ~52-57%
  ≤100 bars → ~50-54%  (approaches random walk)
  >100 bars → not meaningfully predictable

The tracker stores these bounds as HORIZON_RELIABILITY so the chart can
display expected accuracy as a reference alongside actual measured accuracy.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger
from utils.logger import get_intel_logger

DB_PATH  = Path(__file__).parent.parent / "data" / "forecast_tracker.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Seconds per interval string
INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400, "1w": 604800,
}

# Empirical upper-bound accuracy by horizon (for reference display)
HORIZON_RELIABILITY: dict[int, float] = {
    5:   0.68,
    10:  0.64,
    20:  0.60,
    50:  0.56,
    100: 0.53,
}

# Minimum seconds between recording the same symbol+direction forecast
# (prevents flooding the DB on 5-second chart refreshes)
MIN_RECORD_INTERVAL = 60   # 1 minute


@dataclass
class ForecastRecord:
    forecast_id: str
    symbol: str
    interval: str
    direction: str          # BUY | SELL
    confidence: float
    entry_price: float
    target_price: float
    horizon_bars: int
    interval_sec: int       # seconds per bar
    ts_epoch: float         # Unix time when forecast was made
    eval_at_epoch: float    # Unix time when we should evaluate

    # Filled on evaluation
    evaluated: bool = False
    actual_price: float = 0.0
    correct: bool = False
    actual_pnl_pct: float = 0.0   # actual price move % in forecast direction


class ForecastTracker:
    """
    Records, evaluates, and scores AI price forecasts.

    Thread-safe.  Persists to SQLite.  Background evaluation loop runs
    every 60 seconds and evaluates any records whose horizon has elapsed.
    """

    def __init__(self) -> None:
        self._intel = get_intel_logger()
        self._lock  = threading.Lock()
        # last_recorded[(symbol, interval, direction)] = ts_epoch
        self._last_recorded: dict[tuple, float] = {}
        self._init_db()
        self._start_eval_loop()

    # ── Public API ─────────────────────────────────────────────────────

    def record_forecast(
        self,
        symbol: str,
        interval: str,
        direction: str,
        confidence: float,
        entry_price: float,
        target_price: float,
        horizon_bars: int,
    ) -> Optional[str]:
        """
        Record a new forecast.  Returns the forecast_id or None if throttled.

        Throttling: the same (symbol, interval, direction) is not recorded
        more than once per MIN_RECORD_INTERVAL seconds, so rapid chart
        refreshes do not flood the database.
        """
        key = (symbol, interval, direction)
        now = time.time()
        with self._lock:
            last = self._last_recorded.get(key, 0.0)
            if now - last < MIN_RECORD_INTERVAL:
                return None
            self._last_recorded[key] = now

        interval_sec = INTERVAL_SECONDS.get(interval, 3600)
        eval_at      = now + horizon_bars * interval_sec
        fid          = str(uuid.uuid4())[:12]
        rec = ForecastRecord(
            forecast_id=fid,
            symbol=symbol, interval=interval,
            direction=direction, confidence=confidence,
            entry_price=entry_price, target_price=target_price,
            horizon_bars=horizon_bars, interval_sec=interval_sec,
            ts_epoch=now, eval_at_epoch=eval_at,
        )
        self._db_insert(rec)
        self._intel.ml("ForecastTracker",
            f"📐 Forecast recorded: {direction} {symbol} @ {entry_price:.4f} "
            f"→ {target_price:.4f} | {horizon_bars}-bar horizon "
            f"(eval at {datetime.utcfromtimestamp(eval_at).strftime('%H:%M')} UTC) "
            f"[{fid}]")
        return fid

    def get_accuracy(
        self,
        symbol: str = "",
        interval: str = "",
        horizon_bars: int = 0,
        last_n: int = 50,
    ) -> dict:
        """
        Return accuracy stats for evaluated records matching the filters.
        Any filter left as "" / 0 means "all".

        Returns:
            {
              "total": int,
              "correct": int,
              "rate": float,        # 0-1
              "avg_confidence": float,
              "avg_actual_pnl": float,
              "calibration": float, # rate / avg_confidence  (>1 = underconfident)
              "expected_rate": float,  # HORIZON_RELIABILITY bound for this horizon
            }
        """
        rows = self._db_query_evaluated(symbol, interval, horizon_bars, last_n)
        if not rows:
            return {
                "total": 0, "correct": 0, "rate": 0.0,
                "avg_confidence": 0.0, "avg_actual_pnl": 0.0,
                "calibration": 1.0,
                "expected_rate": _expected_rate(horizon_bars),
            }
        correct  = sum(1 for r in rows if r["correct"])
        total    = len(rows)
        rate     = correct / total
        avg_conf = sum(r["confidence"] for r in rows) / total
        avg_pnl  = sum(r["actual_pnl_pct"] for r in rows) / total
        calib    = rate / avg_conf if avg_conf > 0 else 1.0
        return {
            "total": total,
            "correct": correct,
            "rate": rate,
            "avg_confidence": avg_conf,
            "avg_actual_pnl": avg_pnl,
            "calibration": calib,
            "expected_rate": _expected_rate(horizon_bars),
        }

    def get_horizon_breakdown(self, symbol: str = "", last_n: int = 200) -> list[dict]:
        """
        Return accuracy for each horizon bucket for a given symbol.
        Useful for building the 'accuracy vs horizon' decay chart.
        """
        buckets = [5, 10, 20, 50, 100]
        result  = []
        for h in buckets:
            stats = self.get_accuracy(symbol=symbol, horizon_bars=h, last_n=last_n)
            stats["horizon"] = h
            result.append(stats)
        return result

    def pending_count(self) -> int:
        """Number of forecasts not yet evaluated."""
        try:
            with self._conn() as c:
                row = c.execute(
                    "SELECT COUNT(*) FROM forecasts WHERE evaluated=0"
                ).fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    # ── Evaluation loop ─────────────────────────────────────────────────

    def _start_eval_loop(self) -> None:
        t = threading.Thread(target=self._eval_loop, daemon=True, name="forecast-eval")
        t.start()

    def _eval_loop(self) -> None:
        while True:
            try:
                self._evaluate_pending()
            except Exception as exc:
                logger.debug(f"ForecastTracker eval error: {exc}")
            time.sleep(60)

    def _evaluate_pending(self) -> None:
        now    = time.time()
        due    = self._db_query_due(now)
        if not due:
            return

        prices = self._fetch_current_prices({r["symbol"] for r in due})

        for row in due:
            symbol = row["symbol"]
            price  = prices.get(symbol)
            if price is None:
                continue   # can't evaluate yet, try next cycle

            direction  = row["direction"]
            entry      = row["entry_price"]
            if not entry:
                continue
            move_pct   = (price - entry) / entry * 100.0
            if direction == "SELL":
                move_pct = -move_pct   # positive = correct for SELL too

            correct = move_pct > 0
            self._db_update_evaluated(
                row["forecast_id"], price, correct, move_pct
            )
            emoji = "✅" if correct else "❌"
            self._intel.ml("ForecastTracker",
                f"{emoji} Forecast evaluated [{row['forecast_id']}]: "
                f"{direction} {symbol} entry={entry:.4f} actual={price:.4f} "
                f"move={move_pct:+.2f}% | horizon={row['horizon_bars']}bar")

    def _fetch_current_prices(self, symbols: set[str]) -> dict[str, float]:
        """Get current prices from Redis or DB."""
        prices: dict[str, float] = {}
        try:
            from db.redis_client import RedisClient
            rc = RedisClient()
            for sym in symbols:
                try:
                    d = rc.get_ticker(sym)
                    if d:
                        prices[sym] = float(d.get("price", 0) or d.get("last", 0))
                except Exception:
                    pass
        except Exception:
            pass
        return prices

    # ── SQLite ─────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        try:
            with self._conn() as c:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS forecasts (
                        forecast_id TEXT PRIMARY KEY,
                        symbol TEXT, interval TEXT,
                        direction TEXT, confidence REAL,
                        entry_price REAL, target_price REAL,
                        horizon_bars INTEGER, interval_sec INTEGER,
                        ts_epoch REAL, eval_at_epoch REAL,
                        evaluated INTEGER DEFAULT 0,
                        actual_price REAL DEFAULT 0,
                        correct INTEGER DEFAULT 0,
                        actual_pnl_pct REAL DEFAULT 0
                    )
                """)
                c.execute("CREATE INDEX IF NOT EXISTS idx_sym_eval "
                          "ON forecasts(symbol, evaluated)")
        except Exception as exc:
            logger.debug(f"ForecastTracker DB init: {exc}")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _db_insert(self, rec: ForecastRecord) -> None:
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT OR IGNORE INTO forecasts VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    rec.forecast_id, rec.symbol, rec.interval,
                    rec.direction, rec.confidence,
                    rec.entry_price, rec.target_price,
                    rec.horizon_bars, rec.interval_sec,
                    rec.ts_epoch, rec.eval_at_epoch,
                    int(rec.evaluated), rec.actual_price,
                    int(rec.correct), rec.actual_pnl_pct,
                ))
        except Exception as exc:
            logger.debug(f"ForecastTracker DB insert: {exc}")

    def _db_query_due(self, now: float) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT * FROM forecasts WHERE evaluated=0 AND eval_at_epoch<=?",
                    (now,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def _db_update_evaluated(
        self, forecast_id: str, actual_price: float, correct: bool, pnl_pct: float
    ) -> None:
        try:
            with self._conn() as c:
                c.execute("""
                    UPDATE forecasts
                    SET evaluated=1, actual_price=?, correct=?, actual_pnl_pct=?
                    WHERE forecast_id=?
                """, (actual_price, int(correct), pnl_pct, forecast_id))
        except Exception as exc:
            logger.debug(f"ForecastTracker DB update: {exc}")

    def _db_query_evaluated(
        self, symbol: str, interval: str, horizon_bars: int, last_n: int
    ) -> list[dict]:
        try:
            conditions = ["evaluated=1"]
            params: list = []
            if symbol:
                conditions.append("symbol=?");   params.append(symbol)
            if interval:
                conditions.append("interval=?");  params.append(interval)
            if horizon_bars:
                conditions.append("horizon_bars=?"); params.append(horizon_bars)
            where = " AND ".join(conditions)
            params.append(last_n)
            with self._conn() as c:
                rows = c.execute(
                    f"SELECT * FROM forecasts WHERE {where} "
                    f"ORDER BY ts_epoch DESC LIMIT ?",
                    params,
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []


# ── Helpers ────────────────────────────────────────────────────────────────────

def _expected_rate(horizon_bars: int) -> float:
    """Interpolate the empirical upper-bound accuracy for a given horizon."""
    if horizon_bars <= 0:
        return 0.60
    keys = sorted(HORIZON_RELIABILITY.keys())
    if not keys:
        return 0.55
    if horizon_bars <= keys[0]:
        return HORIZON_RELIABILITY[keys[0]]
    if horizon_bars >= keys[-1]:
        return HORIZON_RELIABILITY[keys[-1]]
    for i in range(len(keys) - 1):
        lo, hi = keys[i], keys[i + 1]
        if lo <= horizon_bars <= hi:
            t = (horizon_bars - lo) / (hi - lo)
            return HORIZON_RELIABILITY[lo] + t * (HORIZON_RELIABILITY[hi] - HORIZON_RELIABILITY[lo])
    return 0.55


# Singleton
_tracker: Optional[ForecastTracker] = None

def get_forecast_tracker() -> ForecastTracker:
    global _tracker
    if _tracker is None:
        _tracker = ForecastTracker()
    return _tracker
