"""
Trade Journal – Full Audit Trail of Every Trading Decision.

Every trade is logged with the complete decision context:
  - All signal sources and their individual votes
  - Council decision (final deliberated signal)
  - Regime at time of trade
  - MTF confluence score
  - Dynamic risk parameters used (ATR stop, size multiplier)
  - Actual entry/exit prices, P&L, duration

Post-trade attribution:
  - Which sources were correct (predicted the right direction)
  - Win/loss fed back to EnsembleAggregator for weight adaptation
  - Running win rate per source

Persisted to:
  - SQLite file: data/trade_journal.db (primary)
  - JSON file: data/trade_journal.json (human-readable backup)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger
from utils.logger import get_intel_logger

JOURNAL_DIR = Path(__file__).parent.parent / "data"
JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH   = JOURNAL_DIR / "trade_journal.db"
JSON_PATH = JOURNAL_DIR / "trade_journal.json"


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class TradeEntry:
    trade_id: str
    symbol: str
    side: str                    # BUY | SELL
    entry_price: float
    entry_time: str              # ISO timestamp
    stop_loss: float
    take_profit: float
    quantity: float
    position_size_mult: float
    paper: bool = False

    # Decision context
    regime: str = ""
    mtf_confluence_score: float = 0.0
    council_final: str = ""      # Council's final signal
    council_confidence: float = 0.0
    council_disagreement: float = 0.0
    source_signals: dict = field(default_factory=dict)  # {source: {signal, confidence}}

    # Post-trade (filled on close)
    exit_price: float = 0.0
    exit_time: str = ""
    exit_reason: str = ""        # SL | TP | SIGNAL | MANUAL
    pnl: float = 0.0
    pnl_pct: float = 0.0
    duration_minutes: float = 0.0
    is_open: bool = True

    # Attribution
    correct_sources: list[str] = field(default_factory=list)
    wrong_sources: list[str] = field(default_factory=list)


# ── Trade journal ─────────────────────────────────────────────────────────────

class TradeJournal:
    """
    Persistent audit trail of every trade with decision context.
    Thread-safe; writes to both SQLite and JSON.
    """

    def __init__(self, ensemble=None, dynamic_risk=None) -> None:
        self._ensemble     = ensemble
        self._dynamic_risk = dynamic_risk
        self._intel = get_intel_logger()
        self._lock  = threading.Lock()
        self._open_trades: dict[str, TradeEntry] = {}  # trade_id → entry
        self._init_db()

    # ── Public API ─────────────────────────────────────────────────────

    def open_trade(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        paper: bool = False,
        regime: str = "",
        mtf_score: float = 0.0,
        council_decision=None,
        source_signals: dict = None,
        size_mult: float = 1.0,
    ) -> str:
        """
        Log a trade opening. Returns the trade_id.
        """
        trade_id = f"{symbol}_{int(time.time() * 1000)}"
        entry = TradeEntry(
            trade_id=trade_id,
            symbol=symbol, side=side,
            entry_price=entry_price, entry_time=datetime.now(timezone.utc).isoformat(),
            stop_loss=stop_loss, take_profit=take_profit,
            quantity=quantity, position_size_mult=size_mult, paper=paper,
            regime=regime, mtf_confluence_score=mtf_score,
            source_signals=source_signals or {},
        )
        if council_decision:
            entry.council_final      = getattr(council_decision, "final_signal", "")
            entry.council_confidence = getattr(council_decision, "final_confidence", 0.0)
            entry.council_disagreement = getattr(council_decision, "disagreement_score", 0.0)

        with self._lock:
            self._open_trades[trade_id] = entry
            self._db_insert(entry)

        mode = "[PAPER] " if paper else ""
        self._intel.trade("TradeJournal",
            f"📖 {mode}OPEN {side} {symbol} @ {entry_price:.4f} "
            f"| regime={regime} | council={entry.council_final}({entry.council_confidence:.0%}) "
            f"| size×{size_mult:.2f}")
        return trade_id

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str = "SIGNAL",
    ) -> Optional[TradeEntry]:
        """
        Log a trade close, compute P&L, attribute sources, update weights.
        """
        with self._lock:
            entry = self._open_trades.pop(trade_id, None)
            if entry is None:
                # Try loading from DB
                entry = self._db_load_trade(trade_id)
                if entry is None:
                    logger.warning(f"TradeJournal: trade_id {trade_id} not found")
                    return None

        now = datetime.now(timezone.utc).isoformat()
        entry.exit_price  = exit_price
        entry.exit_time   = now
        entry.exit_reason = exit_reason
        entry.is_open     = False

        # Compute P&L
        if entry.side == "BUY":
            entry.pnl = (exit_price - entry.entry_price) * entry.quantity
        else:
            entry.pnl = (entry.entry_price - exit_price) * entry.quantity
        entry.pnl_pct = (entry.pnl / (entry.entry_price * entry.quantity + 1e-9)) * 100

        # Duration
        try:
            from datetime import datetime as dt
            t0 = dt.fromisoformat(entry.entry_time)
            t1 = dt.fromisoformat(now)
            entry.duration_minutes = (t1 - t0).total_seconds() / 60
        except Exception:
            pass

        # Source attribution
        win = entry.pnl > 0
        for src, sig_dict in entry.source_signals.items():
            predicted = (sig_dict.get("signal") or sig_dict.get("action", "HOLD"))
            correct = (predicted == entry.side and win) or (predicted != entry.side and not win and predicted != "HOLD")
            if correct:
                entry.correct_sources.append(src)
            elif predicted != "HOLD":
                entry.wrong_sources.append(src)

        # Feed outcome back to ensemble and dynamic risk
        if self._ensemble:
            self._ensemble.record_outcome(entry.symbol, win)
        if self._dynamic_risk:
            self._dynamic_risk.record_outcome(win, entry.pnl)

        with self._lock:
            self._db_update(entry)
        self._append_json(entry)

        emoji = "✅" if win else "❌"
        self._intel.trade("TradeJournal",
            f"📖 {emoji} CLOSE {entry.side} {entry.symbol} @ {exit_price:.4f} "
            f"| PnL: {entry.pnl:+.4f} ({entry.pnl_pct:+.1f}%) | {exit_reason} "
            f"| correct: {entry.correct_sources} | wrong: {entry.wrong_sources}")
        return entry

    def get_open_trades(self) -> list[TradeEntry]:
        with self._lock:
            return list(self._open_trades.values())

    def get_closed_trades(self, limit: int = 500) -> list[dict]:
        with self._lock:
            return self._db_query_closed(limit)

    def daily_summary(self) -> dict:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        closed = self._db_query_closed(limit=1000)
        today_trades = [t for t in closed if t.get("exit_time", "").startswith(today)]
        if not today_trades:
            return {"total_trades": 0, "pnl": 0.0, "win_rate": 0.0}
        wins = [t for t in today_trades if t.get("pnl", 0) > 0]
        return {
            "total_trades": len(today_trades),
            "pnl": sum(t.get("pnl", 0) for t in today_trades),
            "win_rate": len(wins) / len(today_trades),
            "avg_duration_min": sum(t.get("duration_minutes", 0) for t in today_trades) / len(today_trades),
        }

    def source_attribution(self) -> dict[str, dict]:
        """Return win rates per signal source across all closed trades."""
        closed = self._db_query_closed(limit=5000)
        attribution: dict[str, dict[str, int]] = {}
        for t in closed:
            pnl = t.get("pnl", 0)
            win = pnl > 0
            for src in json.loads(t.get("correct_sources", "[]")):
                attribution.setdefault(src, {"wins": 0, "losses": 0})
                attribution[src]["wins" if win else "losses"] += 1
            for src in json.loads(t.get("wrong_sources", "[]")):
                attribution.setdefault(src, {"wins": 0, "losses": 0})
                attribution[src]["losses" if win else "wins"] += 1

        return {
            src: {
                "wins": d["wins"], "losses": d["losses"],
                "win_rate": d["wins"] / max(1, d["wins"] + d["losses"]),
                "total": d["wins"] + d["losses"],
            }
            for src, d in attribution.items()
        }

    # ── SQLite ─────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        try:
            with self._conn() as c:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        trade_id TEXT PRIMARY KEY,
                        symbol TEXT, side TEXT,
                        entry_price REAL, entry_time TEXT,
                        exit_price REAL, exit_time TEXT,
                        stop_loss REAL, take_profit REAL,
                        quantity REAL, pnl REAL, pnl_pct REAL,
                        duration_minutes REAL, is_open INTEGER,
                        exit_reason TEXT, paper INTEGER,
                        regime TEXT, mtf_confluence_score REAL,
                        council_final TEXT, council_confidence REAL,
                        council_disagreement REAL,
                        position_size_mult REAL,
                        source_signals TEXT,
                        correct_sources TEXT, wrong_sources TEXT
                    )
                """)
        except Exception as exc:
            logger.debug(f"TradeJournal DB init error: {exc}")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _db_insert(self, e: TradeEntry) -> None:
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT OR REPLACE INTO trades VALUES (
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                    )
                """, (
                    e.trade_id, e.symbol, e.side,
                    e.entry_price, e.entry_time,
                    e.exit_price, e.exit_time,
                    e.stop_loss, e.take_profit,
                    e.quantity, e.pnl, e.pnl_pct,
                    e.duration_minutes, int(e.is_open),
                    e.exit_reason, int(e.paper),
                    e.regime, e.mtf_confluence_score,
                    e.council_final, e.council_confidence,
                    e.council_disagreement, e.position_size_mult,
                    json.dumps(e.source_signals),
                    json.dumps(e.correct_sources),
                    json.dumps(e.wrong_sources),
                ))
        except Exception as exc:
            logger.debug(f"TradeJournal DB insert error: {exc}")

    def _db_update(self, e: TradeEntry) -> None:
        self._db_insert(e)

    def _db_load_trade(self, trade_id: str) -> Optional[TradeEntry]:
        try:
            with self._conn() as c:
                row = c.execute("SELECT * FROM trades WHERE trade_id=?", (trade_id,)).fetchone()
                if row:
                    return TradeEntry(
                        trade_id=row["trade_id"], symbol=row["symbol"], side=row["side"],
                        entry_price=row["entry_price"], entry_time=row["entry_time"],
                        exit_price=row["exit_price"] or 0, exit_time=row["exit_time"] or "",
                        stop_loss=row["stop_loss"] or 0, take_profit=row["take_profit"] or 0,
                        quantity=row["quantity"], pnl=row["pnl"] or 0, pnl_pct=row["pnl_pct"] or 0,
                        duration_minutes=row["duration_minutes"] or 0,
                        is_open=bool(row["is_open"]), exit_reason=row["exit_reason"] or "",
                        paper=bool(row["paper"]), regime=row["regime"] or "",
                        mtf_confluence_score=row["mtf_confluence_score"] or 0,
                        council_final=row["council_final"] or "",
                        council_confidence=row["council_confidence"] or 0,
                        council_disagreement=row["council_disagreement"] or 0,
                        position_size_mult=row["position_size_mult"] or 1.0,
                        source_signals=json.loads(row["source_signals"] or "{}"),
                        correct_sources=json.loads(row["correct_sources"] or "[]"),
                        wrong_sources=json.loads(row["wrong_sources"] or "[]"),
                    )
        except Exception as exc:
            logger.debug(f"TradeJournal DB load error: {exc}")
        return None

    def _db_query_closed(self, limit: int = 500) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT * FROM trades WHERE is_open=0 ORDER BY exit_time DESC LIMIT ?",
                    (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.debug(f"TradeJournal DB query error: {exc}")
            return []

    def _append_json(self, entry: TradeEntry) -> None:
        try:
            existing = []
            if JSON_PATH.exists():
                existing = json.loads(JSON_PATH.read_text())
            existing.append(asdict(entry))
            JSON_PATH.write_text(json.dumps(existing[-2000:], indent=2))
        except Exception:
            pass
