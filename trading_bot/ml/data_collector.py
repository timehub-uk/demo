"""
Historical market data collector.
Downloads OHLCV + computed indicators for top-N tokens and stores in PostgreSQL.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Callable, Optional

import numpy as np
import pandas as pd
import pandas_ta as ta
from loguru import logger
from sqlalchemy.dialects.postgresql import insert

from config import get_settings
from db.postgres import get_db
from db.models import TokenMetrics


INTERVALS = {
    "1m":  60,
    "5m":  300,
    "15m": 900,
    "1h":  3600,
    "4h":  14400,
    "1d":  86400,
}

# Max candles per Binance API call
KLINE_LIMIT = 1000


class DataCollector:
    """
    Downloads historical klines for multiple symbols and intervals,
    computes technical indicators, and upserts to PostgreSQL.

    Progress is reported via :meth:`on_progress` callbacks.
    """

    def __init__(self, binance_client=None) -> None:
        self._client = binance_client
        self._settings = get_settings()
        self._progress_callbacks: list[Callable] = []
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def on_progress(self, callback: Callable) -> None:
        self._progress_callbacks.append(callback)

    def stop(self) -> None:
        self._stop_event.set()

    # ── Main entry ─────────────────────────────────────────────────────
    def collect_top_tokens(
        self,
        symbols: list[str],
        intervals: list[str] | None = None,
        days_back: int = 365,
    ) -> dict[str, int]:
        """
        Download data for all symbols × intervals.
        Returns dict of {symbol: total_rows_inserted}.
        """
        intervals = intervals or ["1m", "5m", "15m", "1h", "4h", "1d"]
        totals: dict[str, int] = {}
        total_tasks = len(symbols) * len(intervals)
        done = 0

        for symbol in symbols:
            if self._stop_event.is_set():
                break
            totals[symbol] = 0
            for interval in intervals:
                if self._stop_event.is_set():
                    break
                try:
                    rows = self._download_and_store(symbol, interval, days_back)
                    totals[symbol] += rows
                    done += 1
                    self._report_progress(done, total_tasks, symbol, interval, rows)
                except Exception as exc:
                    logger.error(f"Data collection failed [{symbol}/{interval}]: {exc}")
                time.sleep(0.12)   # Binance rate-limit safety
        return totals

    # ── Core download ──────────────────────────────────────────────────
    def _download_and_store(self, symbol: str, interval: str, days_back: int) -> int:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - (days_back * 86400 * 1000)
        rows_inserted = 0

        while start_ms < now_ms and not self._stop_event.is_set():
            raw = self._fetch_klines(symbol, interval, start_ms, now_ms)
            if not raw:
                break
            df = self._to_dataframe(raw)
            df = self._add_indicators(df)
            rows = self._upsert(symbol, interval, df)
            rows_inserted += rows
            last_ts = int(raw[-1][0])
            if last_ts <= start_ms:
                break
            start_ms = last_ts + 1
            time.sleep(0.05)

        return rows_inserted

    def _fetch_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
        if self._client:
            try:
                return self._client.get_klines(
                    symbol=symbol, interval=interval,
                    limit=KLINE_LIMIT,
                    start_time=start_ms, end_time=end_ms,
                )
            except Exception as exc:
                logger.warning(f"Kline fetch error [{symbol}]: {exc}")
                return []
        # Simulation mode – return synthetic data
        return self._generate_synthetic(symbol, interval, start_ms, end_ms)

    # ── DataFrame processing ───────────────────────────────────────────
    @staticmethod
    def _to_dataframe(raw: list) -> pd.DataFrame:
        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades_count",
            "taker_buy_volume", "taker_buy_quote_volume", "ignore",
        ])
        for col in ["open", "high", "low", "close", "volume",
                    "quote_volume", "taker_buy_volume", "taker_buy_quote_volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["trades_count"] = df["trades_count"].astype(int)
        return df.drop(columns=["close_time", "ignore"])

    @staticmethod
    def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < 10:
            return df
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        df["rsi"] = ta.rsi(close, length=14)
        macd = ta.macd(close)
        if macd is not None and not macd.empty:
            df["macd"] = macd.get("MACD_12_26_9")
            df["macd_signal"] = macd.get("MACDs_12_26_9")
        bb = ta.bbands(close, length=20)
        if bb is not None and not bb.empty:
            df["bb_upper"] = bb.get("BBU_20_2.0")
            df["bb_lower"] = bb.get("BBL_20_2.0")
        df["ema_20"] = ta.ema(close, length=20)
        df["ema_50"] = ta.ema(close, length=50)
        df["ema_200"] = ta.ema(close, length=200)
        df["atr"] = ta.atr(high, low, close, length=14)
        df["obv"] = ta.obv(close, volume)
        df["adx"] = ta.adx(high, low, close, length=14).get("ADX_14")

        # VWAP (rolling)
        df["vwap"] = (close * volume).cumsum() / volume.cumsum()
        return df

    # ── Database upsert ────────────────────────────────────────────────
    @staticmethod
    def _upsert(symbol: str, interval: str, df: pd.DataFrame) -> int:
        records = []
        for _, row in df.iterrows():
            rec = {
                "symbol": symbol,
                "interval": interval,
                "open_time": row["open_time"].to_pydatetime(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "quote_volume": float(row.get("quote_volume", 0) or 0),
                "trades_count": int(row.get("trades_count", 0) or 0),
                "taker_buy_volume": float(row.get("taker_buy_volume", 0) or 0),
                "taker_buy_quote_volume": float(row.get("taker_buy_quote_volume", 0) or 0),
            }
            for ind in ["rsi","macd","macd_signal","bb_upper","bb_lower",
                        "ema_20","ema_50","ema_200","atr","obv","vwap","adx"]:
                v = row.get(ind)
                rec[ind] = float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else None
            records.append(rec)

        if not records:
            return 0

        try:
            with get_db() as db:
                stmt = insert(TokenMetrics).values(records)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["symbol", "interval", "open_time"],
                    set_={
                        col: stmt.excluded[col]
                        for col in ["open","high","low","close","volume",
                                    "rsi","macd","macd_signal","bb_upper","bb_lower",
                                    "ema_20","ema_50","ema_200","atr","obv","vwap","adx"]
                    }
                )
                db.execute(stmt)
            return len(records)
        except Exception as exc:
            logger.error(f"Upsert error [{symbol}/{interval}]: {exc}")
            return 0

    # ── Progress reporting ─────────────────────────────────────────────
    def _report_progress(self, done: int, total: int, symbol: str, interval: str, rows: int) -> None:
        pct = done / total * 100
        data = {
            "done": done, "total": total, "pct": pct,
            "symbol": symbol, "interval": interval, "rows": rows,
        }
        for cb in self._progress_callbacks:
            try:
                cb(data)
            except Exception:
                pass

    # ── Synthetic data (simulation) ────────────────────────────────────
    @staticmethod
    def _generate_synthetic(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
        """Generate realistic synthetic OHLCV for demo/offline mode."""
        interval_sec = INTERVALS.get(interval, 60)
        rows = []
        price = 100.0 + (hash(symbol) % 900)
        t = start_ms
        while t < end_ms and len(rows) < KLINE_LIMIT:
            move = np.random.normal(0, price * 0.005)
            o = price
            c = max(price + move, 0.01)
            h = max(o, c) * (1 + abs(np.random.normal(0, 0.003)))
            l = min(o, c) * (1 - abs(np.random.normal(0, 0.003)))
            vol = abs(np.random.normal(1e6, 2e5))
            rows.append([
                t, f"{o:.8f}", f"{h:.8f}", f"{l:.8f}", f"{c:.8f}",
                f"{vol:.2f}", t + interval_sec * 1000 - 1,
                f"{vol * c:.2f}", 1000, f"{vol*0.6:.2f}", f"{vol*0.6*c:.2f}", "0"
            ])
            price = c
            t += interval_sec * 1000
        return rows

    # ── Query helpers ──────────────────────────────────────────────────
    @staticmethod
    def load_dataframe(symbol: str, interval: str, limit: int = 2000) -> pd.DataFrame:
        """
        Load stored klines for ML training.

        Priority order:
          1. Flat CSV at  data/csv/{symbol}/{interval}/{symbol}-{interval}-FULL.csv
             (fastest – no DB round-trip, contains full year from archive)
          2. PostgreSQL token_metrics table   (fallback / live data)
          3. Empty DataFrame                 (if neither source has data)
        """
        # 1. Try flat archive CSV first
        from pathlib import Path
        csv_root = Path(__file__).parent.parent / "data" / "csv"
        full_csv = csv_root / symbol / interval / f"{symbol}-{interval}-FULL.csv"
        if full_csv.exists() and full_csv.stat().st_size > 1000:
            try:
                df = pd.read_csv(full_csv, parse_dates=["open_time"])
                df = df.sort_values("open_time").reset_index(drop=True)
                for col in df.select_dtypes(include="object").columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                if limit and len(df) > limit:
                    df = df.tail(limit).reset_index(drop=True)
                return df
            except Exception as exc:
                logger.warning(f"CSV load failed [{symbol}/{interval}]: {exc}")

        # 2. Fallback: PostgreSQL
        try:
            with get_db() as db:
                from sqlalchemy import text
                result = db.execute(text("""
                    SELECT open_time, open, high, low, close, volume,
                           rsi, macd, macd_signal, bb_upper, bb_lower,
                           ema_20, ema_50, ema_200, atr, obv, vwap, adx
                    FROM token_metrics
                    WHERE symbol = :sym AND interval = :intv
                    ORDER BY open_time DESC
                    LIMIT :lim
                """), {"sym": symbol, "intv": interval, "lim": limit})
                rows = result.fetchall()

            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(rows, columns=[
                "open_time","open","high","low","close","volume",
                "rsi","macd","macd_signal","bb_upper","bb_lower",
                "ema_20","ema_50","ema_200","atr","obv","vwap","adx"
            ])
            df = df.sort_values("open_time").reset_index(drop=True)
            for col in df.columns[1:]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception as exc:
            logger.warning(f"DB load failed [{symbol}/{interval}]: {exc}")

        return pd.DataFrame()

    @staticmethod
    def csv_row_count(symbol: str, interval: str) -> int:
        """Return number of rows in the flat CSV for (symbol, interval)."""
        from pathlib import Path
        csv_root = Path(__file__).parent.parent / "data" / "csv"
        full_csv = csv_root / symbol / interval / f"{symbol}-{interval}-FULL.csv"
        if not full_csv.exists():
            return 0
        try:
            with open(full_csv) as f:
                return sum(1 for _ in f) - 1   # minus header
        except Exception:
            return 0
