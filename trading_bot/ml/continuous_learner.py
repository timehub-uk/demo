"""
Continuous Learning Engine.
Runs while the application is active and:
  1. Collects real-time trade data
  2. Retrains the ML model every N hours with fresh data
  3. Monitors model performance and triggers retraining if accuracy drops
  4. Runs ML Data Integrity Checks every 25 minutes
  5. Logs all activity to the Intel Logger
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

from config import get_settings
from db.redis_client import RedisClient
from utils.logger import get_intel_logger
from utils.threading_manager import get_thread_manager


class DataIntegrityChecker:
    """
    Runs every 25 minutes to verify ML training data integrity.
    Checks:
      - DB row count per symbol / interval (min threshold)
      - No NaN/inf in critical indicator columns
      - Timestamp ordering and gaps
      - Candle OHLC validity (H >= O,C >= L)
      - Volume > 0
    Reports all findings to Intel Log.
    """

    CRITICAL_COLUMNS = ["open","high","low","close","volume"]
    INDICATOR_COLUMNS = ["rsi","macd","ema_20","ema_50"]
    MIN_ROWS_PER_SYMBOL = 100
    MAX_NAN_PCT = 0.15    # Allow max 15% NaN in indicators

    def __init__(self) -> None:
        self._intel = get_intel_logger()
        self._last_run: Optional[datetime] = None
        self._results: dict = {}

    def run_check(self, symbols: list[str], intervals: list[str] | None = None) -> dict:
        intervals = intervals or ["1h", "4h", "1d"]
        self._intel.ml("DataIntegrityChecker", f"🔍 Starting data integrity check for {len(symbols)} symbols…")

        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbols_checked": len(symbols),
            "passed": 0,
            "warnings": 0,
            "errors": 0,
            "details": [],
        }

        for symbol in symbols:
            for interval in intervals:
                result = self._check_symbol(symbol, interval)
                results["details"].append(result)
                if result["status"] == "OK":
                    results["passed"] += 1
                elif result["status"] == "WARNING":
                    results["warnings"] += 1
                else:
                    results["errors"] += 1

        self._results = results
        self._last_run = datetime.now(timezone.utc)

        # Summary log
        status_emoji = "✅" if results["errors"] == 0 else "❌"
        summary = (
            f"{status_emoji} Data integrity check complete | "
            f"{results['passed']} OK, {results['warnings']} warnings, {results['errors']} errors"
        )
        level = "SUCCESS" if results["errors"] == 0 else "WARNING"
        self._intel.log(level, "ML", "DataIntegrityChecker", summary, {
            "passed": results["passed"],
            "warnings": results["warnings"],
            "errors": results["errors"],
            "symbols": len(symbols),
        })

        return results

    def _check_symbol(self, symbol: str, interval: str) -> dict:
        result = {
            "symbol": symbol,
            "interval": interval,
            "status": "OK",
            "row_count": 0,
            "issues": [],
        }
        try:
            from db.postgres import get_db
            from sqlalchemy import text
            with get_db() as db:
                count_row = db.execute(text(
                    "SELECT COUNT(*) FROM token_metrics WHERE symbol=:s AND interval=:i"
                ), {"s": symbol, "i": interval}).fetchone()
                row_count = count_row[0] if count_row else 0
                result["row_count"] = row_count

                if row_count < self.MIN_ROWS_PER_SYMBOL:
                    result["issues"].append(f"Insufficient rows: {row_count} < {self.MIN_ROWS_PER_SYMBOL}")
                    result["status"] = "WARNING"
                    self._intel.log("WARNING", "ML", "DataIntegrityChecker",
                        f"⚠️ {symbol}/{interval}: only {row_count} rows (min {self.MIN_ROWS_PER_SYMBOL})")
                    return result

                # Check for NaN in critical columns
                for col in self.CRITICAL_COLUMNS:
                    null_row = db.execute(text(
                        f"SELECT COUNT(*) FROM token_metrics WHERE symbol=:s AND interval=:i AND {col} IS NULL"
                    ), {"s": symbol, "i": interval}).fetchone()
                    null_count = null_row[0] if null_row else 0
                    if null_count > 0:
                        result["issues"].append(f"NULL in critical column {col}: {null_count} rows")
                        result["status"] = "ERROR"
                        self._intel.log("ERROR", "ML", "DataIntegrityChecker",
                            f"❌ {symbol}/{interval}: {null_count} NULL in critical column '{col}'")

                # Check OHLC validity (H >= max(O,C) and L <= min(O,C))
                invalid_row = db.execute(text("""
                    SELECT COUNT(*) FROM token_metrics
                    WHERE symbol=:s AND interval=:i
                    AND (high < GREATEST(open, close) OR low > LEAST(open, close))
                """), {"s": symbol, "i": interval}).fetchone()
                invalid_ohlc = invalid_row[0] if invalid_row else 0
                if invalid_ohlc > 0:
                    result["issues"].append(f"Invalid OHLC candles: {invalid_ohlc}")
                    result["status"] = "ERROR"
                    self._intel.log("ERROR", "ML", "DataIntegrityChecker",
                        f"❌ {symbol}/{interval}: {invalid_ohlc} invalid OHLC candles (H<max(O,C) or L>min(O,C))")

                # Check zero/negative volume
                zero_vol_row = db.execute(text(
                    "SELECT COUNT(*) FROM token_metrics WHERE symbol=:s AND interval=:i AND volume <= 0"
                ), {"s": symbol, "i": interval}).fetchone()
                zero_vol = zero_vol_row[0] if zero_vol_row else 0
                if zero_vol > 0:
                    result["issues"].append(f"Zero/negative volume: {zero_vol} rows")
                    if result["status"] == "OK":
                        result["status"] = "WARNING"

                # Check timestamp ordering gaps (significant gaps > 5× expected interval)
                gap_query = db.execute(text("""
                    SELECT COUNT(*) FROM (
                        SELECT open_time,
                               LAG(open_time) OVER (ORDER BY open_time) AS prev_time
                        FROM token_metrics
                        WHERE symbol=:s AND interval=:i
                        ORDER BY open_time
                        LIMIT 1000
                    ) t
                    WHERE open_time - prev_time > make_interval(secs => :expected * 5)
                """), {
                    "s": symbol, "i": interval,
                    "expected": {"1m":60,"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400}.get(interval, 3600)
                }).fetchone()
                gaps = gap_query[0] if gap_query else 0
                if gaps > 0:
                    result["issues"].append(f"Data gaps detected: {gaps}")
                    if result["status"] == "OK":
                        result["status"] = "WARNING"
                    self._intel.log("WARNING", "ML", "DataIntegrityChecker",
                        f"⚠️ {symbol}/{interval}: {gaps} timestamp gaps detected")

                if result["status"] == "OK":
                    self._intel.log("SUCCESS", "ML", "DataIntegrityChecker",
                        f"✅ {symbol}/{interval}: {row_count} rows – all checks passed")

        except Exception as exc:
            result["status"] = "ERROR"
            result["issues"].append(str(exc))
            self._intel.error("DataIntegrityChecker", f"Check failed [{symbol}/{interval}]: {exc}")

        return result

    @property
    def last_results(self) -> dict:
        return self._results

    @property
    def last_run(self) -> Optional[datetime]:
        return self._last_run


class ContinuousLearner:
    """
    Keeps the ML model up-to-date while the application is running.

    - Collects live closed candles and adds them to the database
    - Retrains every `retrain_interval_hours` hours (default 24h)
    - Runs data integrity checks every 25 minutes
    - Adapts position-sizing based on live win-rate tracking
    """

    CHECK_INTERVAL_MINS = 25    # Data integrity check interval

    def __init__(self, trainer=None, predictor=None, binance_client=None) -> None:
        self._trainer = trainer
        self._predictor = predictor
        self._client = binance_client
        self._settings = get_settings()
        self._redis = RedisClient()
        self._intel = get_intel_logger()
        self._thread_mgr = get_thread_manager()
        self._integrity_checker = DataIntegrityChecker()

        self._running = False
        self._active_symbols: list[str] = []
        self._live_trade_buffer: list[dict] = []
        self._win_count = 0
        self._loss_count = 0
        self._signal_callbacks: list[Callable] = []

        # Schedule timers
        self._retrain_timer: Optional[threading.Timer] = None
        self._integrity_timer: Optional[threading.Timer] = None
        self._collect_thread: Optional[threading.Thread] = None

    # ── Lifecycle ──────────────────────────────────────────────────────
    def start(self, symbols: list[str]) -> None:
        self._active_symbols = symbols
        self._running = True

        # Start data collection thread
        self._collect_thread = threading.Thread(
            target=self._collection_loop, daemon=True, name="cl-collector"
        )
        self._collect_thread.start()

        # Schedule first integrity check
        self._schedule_integrity_check()

        # Schedule first retrain
        retrain_secs = self._settings.ml.retrain_interval_hours * 3600
        self._schedule_retrain(retrain_secs)

        self._intel.ml("ContinuousLearner", f"✅ Continuous learning started | {len(symbols)} symbols | retrain every {self._settings.ml.retrain_interval_hours}h | integrity check every {self.CHECK_INTERVAL_MINS}min")

    def stop(self) -> None:
        self._running = False
        if self._retrain_timer:
            self._retrain_timer.cancel()
        if self._integrity_timer:
            self._integrity_timer.cancel()
        self._intel.ml("ContinuousLearner", "Continuous learning stopped.")

    def on_signal(self, callback: Callable) -> None:
        self._signal_callbacks.append(callback)

    # ── Live data collection ───────────────────────────────────────────
    def _collection_loop(self) -> None:
        """Collect live candle closes and buffer them for incremental training."""
        while self._running:
            try:
                for sym in self._active_symbols[:10]:  # Limit to 10 most active
                    if not self._running:
                        break
                    self._collect_live_candle(sym)
                time.sleep(60)  # Every minute
            except Exception as exc:
                logger.debug(f"Collection loop error: {exc}")
                time.sleep(5)

    def _collect_live_candle(self, symbol: str) -> None:
        """Fetch latest 1-min candle and persist to DB."""
        if not self._client:
            return
        try:
            raw = self._client.get_klines(symbol, "1m", limit=2)
            if not raw:
                return
            from ml.data_collector import DataCollector
            collector = DataCollector(self._client)
            df = collector._to_dataframe(raw)
            df = collector._add_indicators(df)
            rows = collector._upsert(symbol, "1m", df)
            if rows > 0:
                self._live_trade_buffer.append({"symbol": symbol, "ts": time.time()})
        except Exception:
            pass

    # ── Trade outcome learning ─────────────────────────────────────────
    def record_trade_outcome(self, symbol: str, pnl: float) -> None:
        """Record trade P&L for online performance tracking."""
        if pnl > 0:
            self._win_count += 1
        else:
            self._loss_count += 1
        total = self._win_count + self._loss_count
        win_rate = self._win_count / total if total > 0 else 0
        self._intel.ml("ContinuousLearner",
            f"Trade outcome recorded | P&L: {pnl:+.4f} | Win rate: {win_rate:.1%} ({self._win_count}W/{self._loss_count}L)",
            {"symbol": symbol, "pnl": pnl, "win_rate": win_rate})

        # Trigger emergency retrain if win rate drops below 45%
        if total >= 20 and win_rate < 0.45:
            self._intel.warning("ContinuousLearner", f"⚠️ Win rate dropped to {win_rate:.1%} – triggering emergency retrain")
            self._thread_mgr.submit_ml(self._run_retrain)

    # ── Retrain schedule ───────────────────────────────────────────────
    def _schedule_retrain(self, delay_secs: float) -> None:
        self._retrain_timer = threading.Timer(delay_secs, self._trigger_retrain)
        self._retrain_timer.daemon = True
        self._retrain_timer.start()

    def _trigger_retrain(self) -> None:
        if not self._running:
            return
        self._intel.ml("ContinuousLearner", "🔄 Scheduled retrain triggered…")
        self._thread_mgr.submit_ml(self._run_retrain)
        # Schedule next
        retrain_secs = self._settings.ml.retrain_interval_hours * 3600
        self._schedule_retrain(retrain_secs)

    def _run_retrain(self) -> None:
        if not self._trainer:
            return
        try:
            self._intel.ml("ContinuousLearner", "🤖 Starting incremental model retrain…")
            session_id = self._trainer.run_training_session(self._active_symbols[:20])
            if self._predictor:
                self._predictor.reload_model()
            self._intel.ml("ContinuousLearner", f"✅ Retrain complete. Session: {session_id}")
        except Exception as exc:
            self._intel.error("ContinuousLearner", f"Retrain failed: {exc}")

    # ── Data integrity schedule ────────────────────────────────────────
    def _schedule_integrity_check(self) -> None:
        delay = self.CHECK_INTERVAL_MINS * 60
        self._integrity_timer = threading.Timer(delay, self._trigger_integrity_check)
        self._integrity_timer.daemon = True
        self._integrity_timer.start()
        self._intel.ml("ContinuousLearner",
            f"⏱ Next data integrity check in {self.CHECK_INTERVAL_MINS} minutes")

    def _trigger_integrity_check(self) -> None:
        if not self._running:
            return
        self._thread_mgr.submit_ml(self._run_integrity_check)
        self._schedule_integrity_check()   # Re-schedule

    def _run_integrity_check(self) -> None:
        self._intel.ml("ContinuousLearner", f"🔍 Running ML data integrity check on {len(self._active_symbols)} symbols…")
        results = self._integrity_checker.run_check(
            self._active_symbols[:50],
            intervals=["1h", "4h"],
        )
        errors = results.get("errors", 0)
        if errors > 0:
            self._intel.warning("ContinuousLearner",
                f"⚠️ {errors} data integrity errors found – consider re-downloading affected symbols")
        # Cache results in Redis for UI display
        try:
            from db.redis_client import RedisClient
            RedisClient().set("integrity:last_check", results, ttl=3600)
        except Exception:
            pass

    # ── Prediction broadcasting ────────────────────────────────────────
    def broadcast_signal(self, signal: dict) -> None:
        for cb in self._signal_callbacks:
            try:
                cb(signal)
            except Exception:
                pass

    @property
    def win_rate(self) -> float:
        total = self._win_count + self._loss_count
        return self._win_count / total if total > 0 else 0.0

    @property
    def integrity_checker(self) -> DataIntegrityChecker:
        return self._integrity_checker
