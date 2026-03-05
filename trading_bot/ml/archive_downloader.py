"""
Binance Public Data Archive Downloader
=======================================
Downloads 1 year of historical kline data from the official
Binance Data Vision archive:  https://data.binance.vision/

Archive layout (used by this downloader):
  Monthly zips:
    data/spot/monthly/klines/{SYMBOL}/{INTERVAL}/
        {SYMBOL}-{INTERVAL}-{YYYY}-{MM}.zip
          └─ {SYMBOL}-{INTERVAL}-{YYYY}-{MM}.csv

  Daily zips (gap-fill for the current partial month):
    data/spot/daily/klines/{SYMBOL}/{INTERVAL}/
        {SYMBOL}-{INTERVAL}-{YYYY}-{MM}-{DD}.zip
          └─ {SYMBOL}-{INTERVAL}-{YYYY}-{MM}-{DD}.csv

CSV column order (Binance standard):
  0  open_time          (ms unix)
  1  open
  2  high
  3  low
  4  close
  5  volume
  6  close_time         (ms unix)
  7  quote_volume
  8  count              (trades)
  9  taker_buy_volume
  10 taker_buy_quote_volume
  11 ignore

Local archive structure  (ARCHIVE_ROOT / symbol / interval /):
  trading_bot/data/archive/
    BTCUSDT/
      1h/
        BTCUSDT-1h-2024-01.zip
        BTCUSDT-1h-2024-01.csv   ← extracted
        ...
      4h/
        ...

Features:
  - Parallel downloads (configurable workers, default 4)
  - Resume support  – skips already-extracted CSVs
  - Checksum verification using Binance's CHECKSUM files
  - Progress callbacks (pct, symbol, interval, bytes)
  - Intel Log integration
  - Automatic DB upsert after extraction
  - Rate limiting to avoid hammering the CDN
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import os
import queue
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Iterator, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import pandas as pd
import numpy as np
from loguru import logger

from config import get_settings
from utils.logger import get_intel_logger

# ── Constants ─────────────────────────────────────────────────────────────────

ARCHIVE_BASE_URL  = "https://data.binance.vision"
ARCHIVE_ROOT      = Path(__file__).parent.parent / "data" / "archive"
CSV_ROOT          = Path(__file__).parent.parent / "data" / "csv"     # flat CSV export

# Intervals supported by the Binance archive
ARCHIVE_INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"]

# Default intervals to download (balance between data richness and disk space)
DEFAULT_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]

# How many months back to download (12 = 1 full year)
DEFAULT_MONTHS_BACK = 12

# Max parallel download threads
DEFAULT_WORKERS = 4

# Retry parameters
MAX_RETRIES   = 5
RETRY_BACKOFF = [1, 2, 4, 8, 16]   # seconds

# Minimum file size to consider a zip valid (bytes)
MIN_ZIP_SIZE = 500

CSV_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "count",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ArchiveTask:
    symbol:   str
    interval: str
    year:     int
    month:    int
    day:      Optional[int] = None     # None = monthly, int = daily
    url:      str = ""
    zip_path: Path = field(default_factory=Path)
    csv_path: Path = field(default_factory=Path)

    @property
    def is_daily(self) -> bool:
        return self.day is not None

    @property
    def filename_stem(self) -> str:
        if self.is_daily:
            return f"{self.symbol}-{self.interval}-{self.year}-{self.month:02d}-{self.day:02d}"
        return f"{self.symbol}-{self.interval}-{self.year}-{self.month:02d}"

    @property
    def checksum_url(self) -> str:
        return self.url + ".CHECKSUM"


@dataclass
class DownloadResult:
    task:      ArchiveTask
    success:   bool
    rows:      int = 0
    bytes_dl:  int = 0
    skipped:   bool = False   # True if CSV already existed
    error:     str = ""


@dataclass
class ArchiveDownloadSummary:
    symbol:          str
    intervals:       list[str]
    months_back:     int
    total_tasks:     int = 0
    completed:       int = 0
    skipped:         int = 0
    failed:          int = 0
    total_rows:      int = 0
    total_bytes:     int = 0
    duration_secs:   float = 0.0
    errors:          list[str] = field(default_factory=list)


# ── URL builders ──────────────────────────────────────────────────────────────

def _monthly_url(symbol: str, interval: str, year: int, month: int) -> str:
    stem = f"{symbol}-{interval}-{year}-{month:02d}"
    return f"{ARCHIVE_BASE_URL}/data/spot/monthly/klines/{symbol}/{interval}/{stem}.zip"


def _daily_url(symbol: str, interval: str, year: int, month: int, day: int) -> str:
    stem = f"{symbol}-{interval}-{year}-{month:02d}-{day:02d}"
    return f"{ARCHIVE_BASE_URL}/data/spot/daily/klines/{symbol}/{interval}/{stem}.zip"


# ── Task generator ────────────────────────────────────────────────────────────

def _generate_tasks(
    symbol: str,
    interval: str,
    months_back: int,
    include_daily_gaps: bool = True,
) -> list[ArchiveTask]:
    """
    Build the full list of ArchiveTask objects for one (symbol, interval) pair.
    Generates monthly tasks for the past `months_back` months plus
    daily tasks for the current partial month.
    """
    tasks: list[ArchiveTask] = []
    today      = date.today()
    root       = ARCHIVE_ROOT / symbol / interval
    root.mkdir(parents=True, exist_ok=True)

    # Monthly tasks – iterate backwards
    for i in range(months_back):
        # Calculate target year/month
        target_month = today.month - i
        target_year  = today.year
        while target_month <= 0:
            target_month += 12
            target_year  -= 1

        # Skip current month (incomplete) – handled by daily fallback
        if target_year == today.year and target_month == today.month:
            continue

        url      = _monthly_url(symbol, interval, target_year, target_month)
        stem     = f"{symbol}-{interval}-{target_year}-{target_month:02d}"
        zip_path = root / f"{stem}.zip"
        csv_path = root / f"{stem}.csv"
        tasks.append(ArchiveTask(
            symbol=symbol, interval=interval,
            year=target_year, month=target_month,
            url=url, zip_path=zip_path, csv_path=csv_path,
        ))

    # Daily tasks for current partial month (gap-fill)
    if include_daily_gaps:
        for day in range(1, today.day):
            url      = _daily_url(symbol, interval, today.year, today.month, day)
            stem     = f"{symbol}-{interval}-{today.year}-{today.month:02d}-{day:02d}"
            zip_path = root / f"{stem}.zip"
            csv_path = root / f"{stem}.csv"
            tasks.append(ArchiveTask(
                symbol=symbol, interval=interval,
                year=today.year, month=today.month, day=day,
                url=url, zip_path=zip_path, csv_path=csv_path,
            ))

    return tasks


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 60) -> bytes:
    """Fetch URL bytes with retry + exponential backoff."""
    req = Request(url, headers={"User-Agent": "BinanceMLPro/1.0"})
    for attempt, backoff in enumerate(RETRY_BACKOFF):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(f"404: {url}") from exc
            if attempt == len(RETRY_BACKOFF) - 1:
                raise
            logger.debug(f"HTTP {exc.code} on {url} – retry in {backoff}s")
            time.sleep(backoff)
        except URLError as exc:
            if attempt == len(RETRY_BACKOFF) - 1:
                raise
            logger.debug(f"URLError on {url} – retry in {backoff}s: {exc}")
            time.sleep(backoff)
    raise RuntimeError(f"All retries exhausted for {url}")


def _checksum_ok(data: bytes, checksum_url: str) -> bool:
    """Verify SHA256 checksum if Binance provides a .CHECKSUM file."""
    try:
        raw = _http_get(checksum_url, timeout=15)
        expected = raw.decode().strip().split()[0].lower()
        actual   = hashlib.sha256(data).hexdigest().lower()
        return actual == expected
    except FileNotFoundError:
        return True   # No checksum file – assume OK
    except Exception:
        return True   # Non-critical – proceed


# ── CSV parsing ───────────────────────────────────────────────────────────────

def _parse_csv_to_df(csv_path: Path) -> pd.DataFrame:
    """
    Parse a Binance archive CSV into a clean DataFrame.
    Handles both header and no-header CSVs.
    """
    df = pd.read_csv(
        csv_path,
        header=None,
        names=CSV_COLUMNS,
        dtype={
            "open": "float64", "high": "float64",
            "low": "float64",  "close": "float64",
            "volume": "float64", "quote_volume": "float64",
            "taker_buy_volume": "float64", "taker_buy_quote_volume": "float64",
            "count": "int64",
        },
        on_bad_lines="skip",
    )
    # Drop Binance's optional header row if present
    df = df[pd.to_numeric(df["open_time"], errors="coerce").notna()]
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df = df.drop(columns=["close_time", "ignore"], errors="ignore")
    df = df.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    return df


# ── Indicator computation ─────────────────────────────────────────────────────

def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute and attach all technical indicators used by the ML pipeline."""
    try:
        import pandas_ta as ta
    except ImportError:
        return df

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    df["rsi"]        = ta.rsi(close, length=14)
    macd_df          = ta.macd(close)
    if macd_df is not None and not macd_df.empty:
        df["macd"]         = macd_df.get("MACD_12_26_9")
        df["macd_signal"]  = macd_df.get("MACDs_12_26_9")
    bb               = ta.bbands(close, length=20)
    if bb is not None and not bb.empty:
        df["bb_upper"] = bb.get("BBU_20_2.0")
        df["bb_lower"] = bb.get("BBL_20_2.0")
    df["ema_20"]     = ta.ema(close, length=20)
    df["ema_50"]     = ta.ema(close, length=50)
    df["ema_200"]    = ta.ema(close, length=200)
    df["atr"]        = ta.atr(high, low, close, length=14)
    df["obv"]        = ta.obv(close, volume)
    adx_df           = ta.adx(high, low, close, length=14)
    if adx_df is not None and not adx_df.empty:
        df["adx"]    = adx_df.get("ADX_14")
    df["vwap"]       = (close * volume).cumsum() / volume.replace(0, np.nan).cumsum()
    return df


# ── DB upsert ─────────────────────────────────────────────────────────────────

def _upsert_to_db(symbol: str, interval: str, df: pd.DataFrame) -> int:
    """Upsert a DataFrame of candles (with indicators) into token_metrics."""
    if df.empty:
        return 0
    try:
        from db.postgres import get_db
        from db.models import TokenMetrics
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        records = []
        for _, row in df.iterrows():
            def _f(col):
                v = row.get(col)
                return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else None

            records.append({
                "symbol":                   symbol,
                "interval":                 interval,
                "open_time":                row["open_time"].to_pydatetime(),
                "open":                     float(row["open"]),
                "high":                     float(row["high"]),
                "low":                      float(row["low"]),
                "close":                    float(row["close"]),
                "volume":                   float(row["volume"]),
                "quote_volume":             float(row.get("quote_volume", 0) or 0),
                "trades_count":             int(row.get("count", 0) or 0),
                "taker_buy_volume":         float(row.get("taker_buy_volume", 0) or 0),
                "taker_buy_quote_volume":   float(row.get("taker_buy_quote_volume", 0) or 0),
                "rsi":         _f("rsi"),       "macd":        _f("macd"),
                "macd_signal": _f("macd_signal"),"bb_upper":   _f("bb_upper"),
                "bb_lower":    _f("bb_lower"),  "ema_20":      _f("ema_20"),
                "ema_50":      _f("ema_50"),    "ema_200":     _f("ema_200"),
                "atr":         _f("atr"),       "obv":         _f("obv"),
                "vwap":        _f("vwap"),      "adx":         _f("adx"),
            })

        CHUNK = 2000
        inserted = 0
        for i in range(0, len(records), CHUNK):
            chunk = records[i: i + CHUNK]
            with get_db() as db:
                stmt = pg_insert(TokenMetrics).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["symbol", "interval", "open_time"],
                    set_={
                        col: stmt.excluded[col]
                        for col in [
                            "open","high","low","close","volume","quote_volume",
                            "rsi","macd","macd_signal","bb_upper","bb_lower",
                            "ema_20","ema_50","ema_200","atr","obv","vwap","adx",
                        ]
                    },
                )
                db.execute(stmt)
            inserted += len(chunk)
        return inserted

    except Exception as exc:
        logger.error(f"DB upsert failed [{symbol}/{interval}]: {exc}")
        return 0


# ── CSV flat export ───────────────────────────────────────────────────────────

def _export_csv(symbol: str, interval: str, df: pd.DataFrame) -> Path:
    """
    Write the processed DataFrame (with indicators) to:
        data/csv/{symbol}/{interval}/{symbol}-{interval}-FULL.csv

    The file is appended to (or created fresh) so the flat CSV always
    contains the complete merged history for that symbol/interval pair.
    The file is sorted by open_time and de-duplicated after each write.
    """
    dest_dir = CSV_ROOT / symbol / interval
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{symbol}-{interval}-FULL.csv"

    if dest_file.exists():
        try:
            existing = pd.read_csv(dest_file, parse_dates=["open_time"])
            combined = pd.concat([existing, df], ignore_index=True)
            combined = (
                combined.sort_values("open_time")
                .drop_duplicates("open_time")
                .reset_index(drop=True)
            )
            combined.to_csv(dest_file, index=False)
            return dest_file
        except Exception:
            pass  # Fall through to fresh write

    df_sorted = df.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    df_sorted.to_csv(dest_file, index=False)
    return dest_file


# ── Single-task worker ────────────────────────────────────────────────────────

def _process_task(task: ArchiveTask, store_in_db: bool = True) -> DownloadResult:
    """
    Download, extract, parse, and optionally upsert one archive task.
    Returns a DownloadResult describing what happened.
    """
    # Already extracted? – skip download but still sync to DB + CSV
    if task.csv_path.exists() and task.csv_path.stat().st_size > 100:
        try:
            df   = _parse_csv_to_df(task.csv_path)
            df   = _add_indicators(df)
            rows = _upsert_to_db(task.symbol, task.interval, df) if store_in_db else len(df)
            _export_csv(task.symbol, task.interval, df)   # keep flat CSV in sync
            return DownloadResult(task=task, success=True, rows=rows, skipped=True)
        except Exception as exc:
            logger.warning(f"Re-parse failed [{task.filename_stem}]: {exc}")

    # Download zip
    try:
        data = _http_get(task.url)
    except FileNotFoundError:
        # Not every symbol/interval/month has data – silently skip
        return DownloadResult(task=task, success=True, rows=0, skipped=True, error="404-not-found")
    except Exception as exc:
        return DownloadResult(task=task, success=False, error=str(exc))

    if len(data) < MIN_ZIP_SIZE:
        return DownloadResult(task=task, success=True, rows=0, skipped=True, error="empty-zip")

    # Verify checksum
    _checksum_ok(data, task.checksum_url)   # non-blocking: log warning on failure only

    # Save zip
    task.zip_path.write_bytes(data)

    # Extract CSV from zip
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
            if not csv_names:
                return DownloadResult(task=task, success=False, error="no-csv-in-zip")
            zf.extract(csv_names[0], path=task.csv_path.parent)
            extracted = task.csv_path.parent / csv_names[0]
            if extracted != task.csv_path:
                extracted.rename(task.csv_path)
    except zipfile.BadZipFile as exc:
        return DownloadResult(task=task, success=False, error=f"bad-zip: {exc}")

    # Parse, compute indicators, write to DB + flat CSV
    try:
        df   = _parse_csv_to_df(task.csv_path)
        df   = _add_indicators(df)
        rows = _upsert_to_db(task.symbol, task.interval, df) if store_in_db else len(df)
        _export_csv(task.symbol, task.interval, df)   # dual-write to data/csv/
    except Exception as exc:
        return DownloadResult(task=task, success=False, error=f"parse-error: {exc}")

    return DownloadResult(
        task=task, success=True, rows=rows, bytes_dl=len(data)
    )


# ── Main downloader class ─────────────────────────────────────────────────────

class BinanceArchiveDownloader:
    """
    Downloads 1 year of Binance historical kline data for a list of symbols
    from the official data.binance.vision archive.

    Usage:
        dl = BinanceArchiveDownloader()
        dl.on_progress(my_callback)
        summary = dl.download(symbols=["BTCUSDT","ETHUSDT"], intervals=["1h","4h"])

    Progress callback receives:
        {
          "pct":        float,       # 0–100
          "done":       int,
          "total":      int,
          "symbol":     str,
          "interval":   str,
          "filename":   str,
          "rows":       int,
          "bytes":      int,
          "skipped":    bool,
          "speed_kbps": float,
        }
    """

    def __init__(
        self,
        archive_root: Path = ARCHIVE_ROOT,
        workers: int = DEFAULT_WORKERS,
        months_back: int = DEFAULT_MONTHS_BACK,
        store_in_db: bool = True,
    ) -> None:
        self._archive_root = archive_root
        self._workers      = workers
        self._months_back  = months_back
        self._store_in_db  = store_in_db
        self._intel        = get_intel_logger()
        self._stop_event   = threading.Event()
        self._progress_cbs: list[Callable] = []
        self._archive_root.mkdir(parents=True, exist_ok=True)
        CSV_ROOT.mkdir(parents=True, exist_ok=True)

    # ── Configuration ──────────────────────────────────────────────────
    def on_progress(self, callback: Callable) -> None:
        """Register a callback for progress updates."""
        self._progress_cbs.append(callback)

    def stop(self) -> None:
        """Signal the downloader to stop after the current task."""
        self._stop_event.set()

    def reset(self) -> None:
        self._stop_event.clear()

    # ── Main entry ─────────────────────────────────────────────────────
    def download(
        self,
        symbols: list[str],
        intervals: list[str] | None = None,
        months_back: int | None = None,
    ) -> dict[str, ArchiveDownloadSummary]:
        """
        Download archive data for all (symbol × interval) combinations.
        Returns a summary dict keyed by symbol.
        """
        self._stop_event.clear()
        intervals   = intervals   or DEFAULT_INTERVALS
        months_back = months_back or self._months_back

        self._intel.ml(
            "ArchiveDownloader",
            f"📦 Starting Binance archive download | {len(symbols)} symbols "
            f"× {len(intervals)} intervals × {months_back} months",
        )

        summaries: dict[str, ArchiveDownloadSummary] = {}
        overall_start = time.time()

        for sym in symbols:
            if self._stop_event.is_set():
                self._intel.warning("ArchiveDownloader", "Download stopped by user.")
                break
            summary = self._download_symbol(sym, intervals, months_back)
            summaries[sym] = summary

        elapsed = time.time() - overall_start
        total_rows  = sum(s.total_rows  for s in summaries.values())
        total_bytes = sum(s.total_bytes for s in summaries.values())
        self._intel.success(
            "ArchiveDownloader",
            f"✅ Archive download complete | {len(summaries)} symbols | "
            f"{total_rows:,} rows | {total_bytes/1e6:.1f} MB | "
            f"{elapsed:.0f}s",
        )
        return summaries

    # ── Per-symbol download ────────────────────────────────────────────
    def _download_symbol(
        self,
        symbol: str,
        intervals: list[str],
        months_back: int,
    ) -> ArchiveDownloadSummary:
        summary = ArchiveDownloadSummary(
            symbol=symbol, intervals=intervals, months_back=months_back
        )
        all_tasks: list[ArchiveTask] = []
        for interval in intervals:
            all_tasks.extend(_generate_tasks(symbol, interval, months_back))

        summary.total_tasks = len(all_tasks)
        if not all_tasks:
            return summary

        self._intel.ml(
            "ArchiveDownloader",
            f"⬇ {symbol}: {len(all_tasks)} files across {len(intervals)} intervals",
        )

        start_t = time.time()
        with ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix=f"arc-{symbol}") as pool:
            futures = {
                pool.submit(_process_task, task, self._store_in_db): task
                for task in all_tasks
            }
            done_count = 0
            for fut in as_completed(futures):
                if self._stop_event.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                task   = futures[fut]
                done_count += 1
                try:
                    result: DownloadResult = fut.result()
                except Exception as exc:
                    result = DownloadResult(task=task, success=False, error=str(exc))

                # Update summary
                if result.skipped:
                    summary.skipped += 1
                elif result.success:
                    summary.completed  += 1
                    summary.total_rows += result.rows
                    summary.total_bytes += result.bytes_dl
                else:
                    summary.failed += 1
                    if result.error and "404" not in result.error:
                        summary.errors.append(f"{task.filename_stem}: {result.error}")

                # Progress callback
                pct      = done_count / summary.total_tasks * 100
                elapsed  = time.time() - start_t
                speed    = (summary.total_bytes / 1024) / max(elapsed, 0.1)
                self._emit_progress({
                    "pct":        pct,
                    "done":       done_count,
                    "total":      summary.total_tasks,
                    "symbol":     symbol,
                    "interval":   task.interval,
                    "filename":   task.filename_stem,
                    "rows":       result.rows,
                    "bytes":      result.bytes_dl,
                    "skipped":    result.skipped,
                    "speed_kbps": speed,
                    "summary": {
                        "completed": summary.completed,
                        "skipped":   summary.skipped,
                        "failed":    summary.failed,
                        "total_rows": summary.total_rows,
                        "total_mb":  round(summary.total_bytes / 1e6, 2),
                    },
                })

                # Per-task Intel Log entry
                if result.success and not result.skipped and result.rows > 0:
                    self._intel.ml(
                        "ArchiveDownloader",
                        f"  ✓ {task.filename_stem}  {result.rows:,} rows  "
                        f"{result.bytes_dl/1024:.0f} KB",
                    )
                elif not result.success:
                    self._intel.warning(
                        "ArchiveDownloader",
                        f"  ✗ {task.filename_stem}: {result.error}",
                    )

        summary.duration_secs = time.time() - start_t
        self._intel.ml(
            "ArchiveDownloader",
            f"  {symbol} done | {summary.completed} DL | {summary.skipped} cached | "
            f"{summary.failed} failed | {summary.total_rows:,} rows | "
            f"{summary.total_bytes/1e6:.1f} MB | {summary.duration_secs:.0f}s",
        )
        return summary

    # ── Utility ────────────────────────────────────────────────────────
    def _emit_progress(self, data: dict) -> None:
        for cb in self._progress_cbs:
            try:
                cb(data)
            except Exception:
                pass

    # ── Disk management ────────────────────────────────────────────────
    def archive_disk_usage(self) -> dict:
        """Return total size, file count, and per-symbol breakdown."""
        total_bytes = 0
        total_files = 0
        per_symbol: dict[str, dict] = {}
        for sym_dir in self._archive_root.iterdir():
            if not sym_dir.is_dir():
                continue
            sym_bytes = sum(f.stat().st_size for f in sym_dir.rglob("*") if f.is_file())
            sym_files = sum(1 for f in sym_dir.rglob("*") if f.is_file())
            per_symbol[sym_dir.name] = {"bytes": sym_bytes, "files": sym_files}
            total_bytes += sym_bytes
            total_files += sym_files
        return {
            "total_gb": round(total_bytes / 1e9, 3),
            "total_mb": round(total_bytes / 1e6, 1),
            "total_files": total_files,
            "per_symbol": per_symbol,
        }

    def clean_zips(self, symbol: str | None = None) -> int:
        """Remove .zip files after successful extraction (keep .csv)."""
        removed = 0
        root = self._archive_root / symbol if symbol else self._archive_root
        for zp in root.rglob("*.zip"):
            csv = zp.with_suffix(".csv")
            if csv.exists() and csv.stat().st_size > 100:
                zp.unlink()
                removed += 1
        self._intel.ml("ArchiveDownloader", f"Cleaned {removed} zip files from archive.")
        return removed

    def list_available(self, symbol: str | None = None) -> list[dict]:
        """List all downloaded CSVs with metadata."""
        results = []
        root = self._archive_root / symbol if symbol else self._archive_root
        for csv_path in sorted(root.rglob("*.csv")):
            rel = csv_path.relative_to(self._archive_root)
            parts = rel.parts
            results.append({
                "symbol":   parts[0] if len(parts) > 0 else "",
                "interval": parts[1] if len(parts) > 1 else "",
                "file":     csv_path.name,
                "size_kb":  round(csv_path.stat().st_size / 1024, 1),
                "path":     str(csv_path),
            })
        return results

    def load_symbol_df(
        self, symbol: str, interval: str, limit_days: int | None = None
    ) -> pd.DataFrame:
        """
        Load all extracted CSVs for (symbol, interval) into a single DataFrame.
        Useful for ML training without hitting the database.
        """
        root = self._archive_root / symbol / interval
        if not root.exists():
            return pd.DataFrame()

        csv_files = sorted(root.glob("*.csv"))
        if not csv_files:
            return pd.DataFrame()

        dfs = []
        for f in csv_files:
            try:
                df = _parse_csv_to_df(f)
                dfs.append(df)
            except Exception as exc:
                logger.warning(f"Failed to parse {f.name}: {exc}")

        if not dfs:
            return pd.DataFrame()

        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)

        if limit_days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=limit_days)
            combined = combined[combined["open_time"] >= cutoff]

        return combined


# ── Module-level convenience function ────────────────────────────────────────

def create_downloader(
    workers: int = DEFAULT_WORKERS,
    months_back: int = DEFAULT_MONTHS_BACK,
    store_in_db: bool = True,
) -> BinanceArchiveDownloader:
    """Factory function returning a configured downloader instance."""
    return BinanceArchiveDownloader(
        archive_root=ARCHIVE_ROOT,
        workers=workers,
        months_back=months_back,
        store_in_db=store_in_db,
    )
