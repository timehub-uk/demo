"""
Reports Panel – Daily / Weekly / Monthly / Quarterly / Ad-Hoc

Provides a comprehensive, at-a-glance view of trading performance
across every time horizon, with one-click export to CSV or email.

Tabs
────
  Daily      – Today's P&L, trade log, source attribution, risk status
  Weekly     – 7-day equity bar chart, daily breakdown table, win trend
  Monthly    – Monthly P&L + tax estimate, week-by-week table, export
  Quarterly  – Q1–Q4 selector, monthly bar chart, full-quarter attribution
  Ad-Hoc     – Custom date-range, report type, generate + export
"""

from __future__ import annotations

import csv
import io
import threading
from datetime import date, datetime, timedelta
from typing import Optional

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, QDate
from PyQt6.QtGui import QColor, QFont, QBrush
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QPushButton, QComboBox, QDateEdit, QSplitter, QScrollArea,
    QFrame, QGridLayout, QTextEdit, QFileDialog, QMessageBox,
)

from ui.styles import (
    ACCENT, ACCENT2, GREEN, GREEN2, RED, ORANGE, YELLOW, PURPLE,
    BG0, BG1, BG2, BG3, BG4, BG5, BORDER, BORDER2,
    FG0, FG1, FG2,
)

pg.setConfigOption("background", BG2)
pg.setConfigOption("foreground", FG1)

# ── shared helpers ─────────────────────────────────────────────────────────────

def _lbl(text: str, colour: str = FG0, size: int = 11,
         bold: bool = False, align=Qt.AlignmentFlag.AlignLeft) -> QLabel:
    w = QLabel(text)
    w.setAlignment(align)
    w.setStyleSheet(f"color:{colour};font-size:{size}px;font-weight:{'700' if bold else '400'};")
    return w


def _card(title: str, colour: str = ACCENT) -> tuple[QGroupBox, QVBoxLayout]:
    grp = QGroupBox(title)
    grp.setStyleSheet(
        f"QGroupBox{{background:{BG3};border:1px solid {BORDER};border-radius:6px;"
        f"color:{colour};font-size:11px;font-weight:700;padding-top:8px;}}"
        f"QGroupBox::title{{subcontrol-origin:margin;left:10px;}}"
    )
    lay = QVBoxLayout(grp)
    lay.setContentsMargins(8, 14, 8, 8)
    lay.setSpacing(4)
    return grp, lay


def _btn(label: str, colour: str = ACCENT, width: int = 0) -> QPushButton:
    b = QPushButton(label)
    if width:
        b.setFixedWidth(width)
    b.setFixedHeight(26)
    b.setStyleSheet(
        f"QPushButton{{background:{colour};color:#000;font-weight:700;font-size:11px;"
        f"border:none;border-radius:3px;padding:0 12px;}}"
        f"QPushButton:hover{{filter:brightness(120%);}}"
        f"QPushButton:disabled{{background:{BG4};color:{FG2};}}"
    )
    return b


def _table(cols: list[str], row_height: int = 24) -> QTableWidget:
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.setStyleSheet(
        f"QTableWidget{{background:{BG3};color:{FG0};gridline-color:{BORDER};"
        f"selection-background-color:{BG5};border:none;font-size:11px;}}"
        f"QHeaderView::section{{background:{BG4};color:{ACCENT};border:none;"
        f"padding:4px;font-size:10px;font-weight:700;}}"
        f"QTableWidget::item:alternate{{background:{BG4};}}"
    )
    t.verticalHeader().setDefaultSectionSize(row_height)
    return t


def _stat_card(value: str, label: str, colour: str = FG0) -> QFrame:
    """Small metric card: big value + small label."""
    f = QFrame()
    f.setStyleSheet(f"QFrame{{background:{BG3};border:1px solid {BORDER};border-radius:6px;}}")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(10, 8, 10, 8)
    v = QLabel(value)
    v.setAlignment(Qt.AlignmentFlag.AlignCenter)
    v.setStyleSheet(f"color:{colour};font-size:20px;font-weight:700;")
    l = QLabel(label.upper())
    l.setAlignment(Qt.AlignmentFlag.AlignCenter)
    l.setStyleSheet(f"color:{FG2};font-size:9px;font-weight:700;letter-spacing:1px;")
    lay.addWidget(v)
    lay.addWidget(l)
    f._value_lbl = v
    f._label_lbl = l
    return f


def _item(text: str, colour: str = FG0, align=Qt.AlignmentFlag.AlignCenter) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    it.setForeground(QColor(colour))
    it.setTextAlignment(align)
    return it


def _pnl_colour(pnl: float) -> str:
    return GREEN if pnl > 0 else RED if pnl < 0 else FG1


# ═══════════════════════════════════════════════════════════════════════════════
# DAILY TAB
# ═══════════════════════════════════════════════════════════════════════════════

class DailyTab(QWidget):
    def __init__(self, trade_journal=None, dynamic_risk=None, forecast_tracker=None):
        super().__init__()
        self._journal = trade_journal
        self._risk    = dynamic_risk
        self._ft      = forecast_tracker
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Header row: date + refresh
        hdr = QHBoxLayout()
        self._date_lbl = _lbl(f"Today: {date.today().strftime('%A, %d %B %Y')}", ACCENT, 12, bold=True)
        hdr.addWidget(self._date_lbl)
        hdr.addStretch()
        ref = _btn("↻ Refresh", ACCENT2, 90)
        ref.clicked.connect(self.refresh)
        hdr.addWidget(ref)
        root.addLayout(hdr)

        # Stat cards row
        stats_row = QHBoxLayout()
        self._c_pnl     = _stat_card("$0.00",  "Today P&L",   FG0)
        self._c_trades  = _stat_card("0",       "Trades",      FG0)
        self._c_winrate = _stat_card("—%",      "Win Rate",    FG0)
        self._c_dd      = _stat_card("0.0%",    "Drawdown",    FG0)
        self._c_circuit = _stat_card("ACTIVE",  "Circuit",     GREEN)
        for c in [self._c_pnl, self._c_trades, self._c_winrate, self._c_dd, self._c_circuit]:
            stats_row.addWidget(c)
        root.addLayout(stats_row)

        # Trade log + attribution side-by-side
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Trade log
        tg, tlay = _card("Trade Log – Today")
        self._trade_tbl = _table(["Time", "Symbol", "Side", "Qty", "Price", "P&L", "Source"])
        tlay.addWidget(self._trade_tbl)
        splitter.addWidget(tg)

        # Source attribution
        ag, alay = _card("Signal Attribution – Today")
        self._attr_tbl = _table(["Source", "Trades", "Wins", "Win %", "Net P&L"])
        alay.addWidget(self._attr_tbl)

        # Forecast accuracy
        fg, flay = _card("Forecast Accuracy", YELLOW)
        self._fc_lbl = _lbl("No data yet", FG1, 10)
        self._fc_lbl.setWordWrap(True)
        flay.addWidget(self._fc_lbl)

        right_col = QWidget()
        rc = QVBoxLayout(right_col)
        rc.setContentsMargins(0, 0, 0, 0)
        rc.setSpacing(6)
        rc.addWidget(ag)
        rc.addWidget(fg)
        splitter.addWidget(right_col)

        splitter.setSizes([600, 350])
        root.addWidget(splitter, 1)

        self.refresh()

    def refresh(self) -> None:
        self._date_lbl.setText(f"Today: {date.today().strftime('%A, %d %B %Y')}")
        self._load_trades()
        self._load_risk()
        self._load_forecast()

    def _load_trades(self) -> None:
        if not self._journal:
            return
        try:
            summary = self._journal.daily_summary()
            pnl     = float(summary.get("total_pnl", 0))
            trades  = int(summary.get("trade_count", 0))
            wr      = float(summary.get("win_rate", 0))

            self._c_pnl._value_lbl.setText(f"{pnl:+,.2f}")
            self._c_pnl._value_lbl.setStyleSheet(
                f"color:{_pnl_colour(pnl)};font-size:20px;font-weight:700;"
            )
            self._c_trades._value_lbl.setText(str(trades))
            self._c_winrate._value_lbl.setText(f"{wr:.0%}")
            self._c_winrate._value_lbl.setStyleSheet(
                f"color:{GREEN if wr >= 0.5 else YELLOW if wr >= 0.4 else RED};"
                f"font-size:20px;font-weight:700;"
            )

            # Trade table
            trade_list = summary.get("trades", [])
            self._trade_tbl.setRowCount(len(trade_list))
            for r, t in enumerate(trade_list):
                tp = float(t.get("pnl", 0) or 0)
                ts = t.get("created_at", "")[:19].replace("T", " ")
                self._trade_tbl.setItem(r, 0, _item(ts[-8:], FG1))
                self._trade_tbl.setItem(r, 1, _item(t.get("symbol", ""), FG0))
                side = t.get("side", "")
                self._trade_tbl.setItem(r, 2, _item(side, GREEN if side == "BUY" else RED))
                self._trade_tbl.setItem(r, 3, _item(f"{float(t.get('quantity', 0)):.4f}", FG1))
                self._trade_tbl.setItem(r, 4, _item(f"{float(t.get('price', 0)):,.4f}", FG1))
                self._trade_tbl.setItem(r, 5, _item(f"{tp:+,.2f}", _pnl_colour(tp)))
                self._trade_tbl.setItem(r, 6, _item(t.get("ml_signal", "—"), ACCENT2))

            # Attribution
            attr = self._journal.source_attribution() if hasattr(self._journal, "source_attribution") else {}
            self._attr_tbl.setRowCount(len(attr))
            for r, (src, stats) in enumerate(sorted(attr.items(), key=lambda x: -x[1].get("net_pnl", 0))):
                net = float(stats.get("net_pnl", 0))
                wr2 = float(stats.get("win_rate", 0))
                self._attr_tbl.setItem(r, 0, _item(src, ACCENT2))
                self._attr_tbl.setItem(r, 1, _item(str(stats.get("total", 0)), FG1))
                self._attr_tbl.setItem(r, 2, _item(str(stats.get("wins", 0)), GREEN))
                self._attr_tbl.setItem(r, 3, _item(f"{wr2:.0%}", GREEN if wr2 >= 0.5 else YELLOW))
                self._attr_tbl.setItem(r, 4, _item(f"{net:+,.2f}", _pnl_colour(net)))
        except Exception:
            pass

    def _load_risk(self) -> None:
        if not self._risk:
            return
        try:
            s = self._risk.status() if hasattr(self._risk, "status") else {}
            cb = s.get("circuit_broken", False)
            dd = float(s.get("drawdown_pct", 0))
            self._c_dd._value_lbl.setText(f"{dd:.1f}%")
            self._c_dd._value_lbl.setStyleSheet(
                f"color:{GREEN if dd < 5 else YELLOW if dd < 12 else RED};"
                f"font-size:20px;font-weight:700;"
            )
            self._c_circuit._value_lbl.setText("BROKEN" if cb else "ACTIVE")
            self._c_circuit._value_lbl.setStyleSheet(
                f"color:{RED if cb else GREEN};font-size:20px;font-weight:700;"
            )
        except Exception:
            pass

    def _load_forecast(self) -> None:
        if not self._ft:
            return
        try:
            acc = self._ft.get_accuracy() if hasattr(self._ft, "get_accuracy") else {}
            if acc:
                rate  = acc.get("rate", 0)
                total = acc.get("total", 0)
                cal   = acc.get("calibration", 0)
                self._fc_lbl.setText(
                    f"Accuracy: {rate:.0%}  ({acc.get('correct', 0)}/{total} forecasts)\n"
                    f"Avg confidence: {acc.get('avg_confidence', 0):.0%}\n"
                    f"Calibration: {cal:.2f}  (1.0 = perfect)\n"
                    f"Avg realised P&L: {acc.get('avg_actual_pnl', 0):+,.4f}"
                )
        except Exception:
            pass

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Time", "Symbol", "Side", "Qty", "Price", "PnL", "Source"])
        for r in range(self._trade_tbl.rowCount()):
            w.writerow([self._trade_tbl.item(r, c).text() if self._trade_tbl.item(r, c) else ""
                        for c in range(self._trade_tbl.columnCount())])
        return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# WEEKLY TAB
# ═══════════════════════════════════════════════════════════════════════════════

class WeeklyTab(QWidget):
    def __init__(self, trade_journal=None):
        super().__init__()
        self._journal = trade_journal
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        hdr = QHBoxLayout()
        self._week_lbl = _lbl("", ACCENT, 12, bold=True)
        hdr.addWidget(self._week_lbl)
        hdr.addStretch()
        ref = _btn("↻ Refresh", ACCENT2, 90)
        ref.clicked.connect(self.refresh)
        hdr.addWidget(ref)
        root.addLayout(hdr)

        # Stats row
        stats_row = QHBoxLayout()
        self._c_pnl     = _stat_card("$0.00", "7-Day P&L",   FG0)
        self._c_trades  = _stat_card("0",      "Total Trades", FG0)
        self._c_winrate = _stat_card("—%",     "Win Rate",     FG0)
        self._c_best    = _stat_card("—",      "Best Day",     GREEN)
        self._c_worst   = _stat_card("—",      "Worst Day",    RED)
        for c in [self._c_pnl, self._c_trades, self._c_winrate, self._c_best, self._c_worst]:
            stats_row.addWidget(c)
        root.addLayout(stats_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Bar chart
        cg, clay = _card("Daily P&L – Last 7 Days")
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=False, y=True, alpha=0.15)
        self._plot.setLabel("left", "P&L (USDT)")
        self._plot.getAxis("bottom").setTicks([])
        clay.addWidget(self._plot)
        splitter.addWidget(cg)

        # Daily breakdown table
        tg, tlay = _card("Day-by-Day Breakdown")
        self._day_tbl = _table(["Date", "Trades", "Wins", "Win %", "Net P&L", "Best Trade"])
        tlay.addWidget(self._day_tbl)
        splitter.addWidget(tg)

        splitter.setSizes([450, 500])
        root.addWidget(splitter, 1)

        self.refresh()

    def refresh(self) -> None:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        self._week_lbl.setText(
            f"Week of {monday.strftime('%d %B %Y')}  (Mon–{today.strftime('%a')})"
        )
        self._load_data()

    def _load_data(self) -> None:
        if not self._journal:
            return
        try:
            today = date.today()
            days  = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
            day_data = []
            for d in days:
                try:
                    s = self._journal.daily_summary(d.isoformat()) \
                        if hasattr(self._journal, "daily_summary") else {}
                    day_data.append({
                        "date": d, "pnl": float(s.get("total_pnl", 0)),
                        "trades": int(s.get("trade_count", 0)),
                        "wins":   int(s.get("wins", 0)),
                        "best":   float(s.get("best_trade_pnl", 0)),
                    })
                except Exception:
                    day_data.append({"date": d, "pnl": 0, "trades": 0, "wins": 0, "best": 0})

            total_pnl    = sum(d["pnl"] for d in day_data)
            total_trades = sum(d["trades"] for d in day_data)
            total_wins   = sum(d["wins"] for d in day_data)
            wr = total_wins / total_trades if total_trades else 0

            self._c_pnl._value_lbl.setText(f"{total_pnl:+,.2f}")
            self._c_pnl._value_lbl.setStyleSheet(
                f"color:{_pnl_colour(total_pnl)};font-size:20px;font-weight:700;"
            )
            self._c_trades._value_lbl.setText(str(total_trades))
            self._c_winrate._value_lbl.setText(f"{wr:.0%}")

            best_day  = max(day_data, key=lambda d: d["pnl"])
            worst_day = min(day_data, key=lambda d: d["pnl"])
            self._c_best._value_lbl.setText(f"{best_day['pnl']:+,.0f}")
            self._c_worst._value_lbl.setText(f"{worst_day['pnl']:+,.0f}")

            # Bar chart
            self._plot.clear()
            xs = list(range(len(day_data)))
            bars = pg.BarGraphItem(
                x=xs, height=[d["pnl"] for d in day_data], width=0.6,
                brushes=[QColor(GREEN if d["pnl"] >= 0 else RED) for d in day_data],
            )
            self._plot.addItem(bars)
            ticks = [(i, day_data[i]["date"].strftime("%a")) for i in xs]
            self._plot.getAxis("bottom").setTicks([ticks])

            # Table
            self._day_tbl.setRowCount(len(day_data))
            for r, d in enumerate(day_data):
                wr2 = d["wins"] / d["trades"] if d["trades"] else 0
                self._day_tbl.setItem(r, 0, _item(d["date"].strftime("%a %d %b"), FG1))
                self._day_tbl.setItem(r, 1, _item(str(d["trades"]), FG0))
                self._day_tbl.setItem(r, 2, _item(str(d["wins"]), GREEN))
                self._day_tbl.setItem(r, 3, _item(f"{wr2:.0%}", GREEN if wr2 >= 0.5 else YELLOW))
                self._day_tbl.setItem(r, 4, _item(f"{d['pnl']:+,.2f}", _pnl_colour(d["pnl"])))
                self._day_tbl.setItem(r, 5, _item(f"{d['best']:+,.2f}", GREEN if d["best"] > 0 else FG2))
        except Exception:
            pass

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = ["Date", "Trades", "Wins", "Win%", "Net PnL", "Best Trade"]
        w.writerow(cols)
        for r in range(self._day_tbl.rowCount()):
            w.writerow([self._day_tbl.item(r, c).text() if self._day_tbl.item(r, c) else ""
                        for c in range(self._day_tbl.columnCount())])
        return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY TAB
# ═══════════════════════════════════════════════════════════════════════════════

class MonthlyTab(QWidget):
    def __init__(self, trade_journal=None, tax_calc=None, email_notifier=None):
        super().__init__()
        self._journal       = trade_journal
        self._tax           = tax_calc
        self._email         = email_notifier
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        hdr = QHBoxLayout()
        self._month_combo = QComboBox()
        self._month_combo.setStyleSheet(
            f"background:{BG4};color:{FG0};border:1px solid {BORDER};padding:3px 8px;border-radius:3px;"
        )
        today = date.today()
        for i in range(12):
            d = today.replace(day=1) - timedelta(days=30 * i)
            self._month_combo.addItem(d.strftime("%B %Y"), (d.year, d.month))
        self._month_combo.currentIndexChanged.connect(self.refresh)
        hdr.addWidget(_lbl("Month:", FG1, 10))
        hdr.addWidget(self._month_combo)
        hdr.addStretch()
        email_btn = _btn("✉ Email Report", PURPLE, 120)
        email_btn.clicked.connect(self._email_report)
        hdr.addWidget(email_btn)
        exp_btn = _btn("⬇ Export CSV", ACCENT2, 110)
        exp_btn.clicked.connect(lambda: self._export_csv())
        hdr.addWidget(exp_btn)
        ref = _btn("↻ Refresh", ACCENT2, 90)
        ref.clicked.connect(self.refresh)
        hdr.addWidget(ref)
        root.addLayout(hdr)

        # Stat cards
        stats_row = QHBoxLayout()
        self._c_pnl     = _stat_card("$0.00", "Month P&L",    FG0)
        self._c_trades  = _stat_card("0",      "Total Trades", FG0)
        self._c_winrate = _stat_card("—%",     "Win Rate",     FG0)
        self._c_tax     = _stat_card("£—",     "Est. Tax",     YELLOW)
        self._c_net_cgt = _stat_card("£—",     "Net CGT Gain", FG0)
        for c in [self._c_pnl, self._c_trades, self._c_winrate, self._c_tax, self._c_net_cgt]:
            stats_row.addWidget(c)
        root.addLayout(stats_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Monthly bar chart (week-by-week)
        cg, clay = _card("Weekly P&L – This Month")
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=False, y=True, alpha=0.15)
        self._plot.setLabel("left", "P&L (USDT)")
        clay.addWidget(self._plot)
        splitter.addWidget(cg)

        # Week breakdown + tax detail
        right = QWidget()
        rc = QVBoxLayout(right)
        rc.setContentsMargins(0, 0, 0, 0)
        rc.setSpacing(6)

        wg, wlay = _card("Week-by-Week Breakdown")
        self._week_tbl = _table(["Week", "Trades", "Win %", "Net P&L", "Cum. P&L"])
        wlay.addWidget(self._week_tbl)
        rc.addWidget(wg)

        tg, tlay = _card("Tax Summary (UK CGT)", YELLOW)
        self._tax_lbl = _lbl("Tax data unavailable – configure tax module.", FG1, 10)
        self._tax_lbl.setWordWrap(True)
        tlay.addWidget(self._tax_lbl)
        rc.addWidget(tg)

        splitter.addWidget(right)
        splitter.setSizes([450, 500])
        root.addWidget(splitter, 1)

        self.refresh()

    def refresh(self) -> None:
        data = self._month_combo.currentData()
        if data:
            self._load(data[0], data[1])

    def _load(self, year: int, month: int) -> None:
        self._load_trading(year, month)
        self._load_tax(year, month)

    def _load_trading(self, year: int, month: int) -> None:
        if not self._journal:
            return
        try:
            # Build weekly buckets
            import calendar
            _, last_day = calendar.monthrange(year, month)
            first = date(year, month, 1)
            last  = date(year, month, last_day)

            weeks: list[tuple[date, date]] = []
            cur = first
            while cur <= last:
                week_end = min(cur + timedelta(days=6 - cur.weekday()), last)
                weeks.append((cur, week_end))
                cur = week_end + timedelta(days=1)

            week_data = []
            for wstart, wend in weeks:
                tot_pnl, tot_trades, tot_wins = 0.0, 0, 0
                d = wstart
                while d <= wend:
                    try:
                        s = self._journal.daily_summary(d.isoformat()) \
                            if hasattr(self._journal, "daily_summary") else {}
                        tot_pnl    += float(s.get("total_pnl", 0))
                        tot_trades += int(s.get("trade_count", 0))
                        tot_wins   += int(s.get("wins", 0))
                    except Exception:
                        pass
                    d += timedelta(days=1)
                week_data.append({"label": f"W/E {wend.strftime('%d %b')}", "pnl": tot_pnl,
                                  "trades": tot_trades, "wins": tot_wins})

            total_pnl    = sum(d["pnl"] for d in week_data)
            total_trades = sum(d["trades"] for d in week_data)
            total_wins   = sum(d["wins"] for d in week_data)
            wr = total_wins / total_trades if total_trades else 0

            self._c_pnl._value_lbl.setText(f"{total_pnl:+,.2f}")
            self._c_pnl._value_lbl.setStyleSheet(
                f"color:{_pnl_colour(total_pnl)};font-size:20px;font-weight:700;"
            )
            self._c_trades._value_lbl.setText(str(total_trades))
            self._c_winrate._value_lbl.setText(f"{wr:.0%}")

            # Bar chart
            self._plot.clear()
            xs = list(range(len(week_data)))
            self._plot.addItem(pg.BarGraphItem(
                x=xs, height=[d["pnl"] for d in week_data], width=0.6,
                brushes=[QColor(GREEN if d["pnl"] >= 0 else RED) for d in week_data],
            ))
            self._plot.getAxis("bottom").setTicks(
                [[(i, week_data[i]["label"]) for i in xs]]
            )

            # Table
            cum = 0.0
            self._week_tbl.setRowCount(len(week_data))
            for r, d in enumerate(week_data):
                cum += d["pnl"]
                wr2  = d["wins"] / d["trades"] if d["trades"] else 0
                self._week_tbl.setItem(r, 0, _item(d["label"], FG1))
                self._week_tbl.setItem(r, 1, _item(str(d["trades"]), FG0))
                self._week_tbl.setItem(r, 2, _item(f"{wr2:.0%}", GREEN if wr2 >= 0.5 else YELLOW))
                self._week_tbl.setItem(r, 3, _item(f"{d['pnl']:+,.2f}", _pnl_colour(d["pnl"])))
                self._week_tbl.setItem(r, 4, _item(f"{cum:+,.2f}", _pnl_colour(cum)))
        except Exception:
            pass

    def _load_tax(self, year: int, month: int) -> None:
        if not self._tax:
            return
        try:
            data = self._tax.monthly_summary(year, month)
            if data:
                net     = float(data.get("net_gain", 0))
                proceeds= float(data.get("total_proceeds", 0))
                cost    = float(data.get("total_cost", 0))
                tax_est = float(data.get("estimated_tax", 0))
                disposals = int(data.get("disposal_count", 0))
                self._tax_lbl.setText(
                    f"Disposals: {disposals}  |  Proceeds: £{proceeds:,.2f}\n"
                    f"Cost basis: £{cost:,.2f}  |  Net gain/loss: £{net:+,.2f}\n"
                    f"Estimated tax (10%/20%): £{tax_est:,.2f}\n\n"
                    f"UK tax year: {self._tax.current_tax_year()}"
                    if hasattr(self._tax, "current_tax_year") else
                    f"Disposals: {disposals}  |  Net: £{net:+,.2f}  |  Est. tax: £{tax_est:,.2f}"
                )
                self._c_tax._value_lbl.setText(f"£{tax_est:,.0f}")
                self._c_net_cgt._value_lbl.setText(f"£{net:+,.0f}")
                self._c_net_cgt._value_lbl.setStyleSheet(
                    f"color:{_pnl_colour(net)};font-size:20px;font-weight:700;"
                )
        except Exception:
            pass

    def _email_report(self) -> None:
        if not self._email:
            QMessageBox.warning(self, "Email", "Email notifier not configured.")
            return
        data = self._month_combo.currentData()
        if not data:
            return
        year, month = data
        import calendar
        month_name = calendar.month_name[month]
        self._email.send_text(
            subject=f"[BinanceML Pro] Monthly Report – {month_name} {year}",
            message=f"Monthly report for {month_name} {year} generated from the app."
        )
        QMessageBox.information(self, "Email", f"Report emailed for {month_name} {year}.")

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Monthly Report", f"monthly_report_{date.today()}.csv", "CSV (*.csv)"
        )
        if path:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["Week", "Trades", "Win %", "Net P&L", "Cumulative P&L"])
            for r in range(self._week_tbl.rowCount()):
                w.writerow([self._week_tbl.item(r, c).text() if self._week_tbl.item(r, c) else ""
                            for c in range(self._week_tbl.columnCount())])
            with open(path, "w", newline="") as f:
                f.write(buf.getvalue())

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Week", "Trades", "Win %", "Net P&L", "Cumulative P&L"])
        for r in range(self._week_tbl.rowCount()):
            w.writerow([self._week_tbl.item(r, c).text() if self._week_tbl.item(r, c) else ""
                        for c in range(self._week_tbl.columnCount())])
        return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# QUARTERLY TAB
# ═══════════════════════════════════════════════════════════════════════════════

class QuarterlyTab(QWidget):
    def __init__(self, trade_journal=None, tax_calc=None):
        super().__init__()
        self._journal = trade_journal
        self._tax     = tax_calc
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        hdr = QHBoxLayout()
        self._q_combo = QComboBox()
        self._q_combo.setStyleSheet(
            f"background:{BG4};color:{FG0};border:1px solid {BORDER};padding:3px 8px;border-radius:3px;"
        )
        today = date.today()
        for year in [today.year, today.year - 1]:
            for q in range(4, 0, -1):
                self._q_combo.addItem(f"Q{q} {year}", (year, q))
        self._q_combo.currentIndexChanged.connect(self.refresh)
        hdr.addWidget(_lbl("Quarter:", FG1, 10))
        hdr.addWidget(self._q_combo)
        hdr.addStretch()
        exp_btn = _btn("⬇ Export CSV", ACCENT2, 110)
        exp_btn.clicked.connect(self._export_csv)
        hdr.addWidget(exp_btn)
        ref = _btn("↻ Refresh", ACCENT2, 90)
        ref.clicked.connect(self.refresh)
        hdr.addWidget(ref)
        root.addLayout(hdr)

        # Stat row
        stats_row = QHBoxLayout()
        self._c_pnl     = _stat_card("$0.00", "Quarter P&L",  FG0)
        self._c_trades  = _stat_card("0",      "Total Trades", FG0)
        self._c_winrate = _stat_card("—%",     "Win Rate",     FG0)
        self._c_sharpe  = _stat_card("—",      "Sharpe (est.)",ACCENT)
        self._c_tax     = _stat_card("£—",     "Q Tax Est.",   YELLOW)
        for c in [self._c_pnl, self._c_trades, self._c_winrate, self._c_sharpe, self._c_tax]:
            stats_row.addWidget(c)
        root.addLayout(stats_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Monthly bar chart
        cg, clay = _card("Monthly P&L – Quarter")
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=False, y=True, alpha=0.15)
        self._plot.setLabel("left", "P&L (USDT)")
        clay.addWidget(self._plot)
        splitter.addWidget(cg)

        # Month-by-month table
        tg, tlay = _card("Month-by-Month")
        self._month_tbl = _table(["Month", "Trades", "Wins", "Win %", "Net P&L", "Tax Est."])
        tlay.addWidget(self._month_tbl)

        # Source attribution for quarter
        ag, alay = _card("Signal Attribution", ACCENT2)
        self._attr_tbl = _table(["Source", "Trades", "Win %", "Net P&L"])
        alay.addWidget(self._attr_tbl)

        right = QWidget()
        rc = QVBoxLayout(right)
        rc.setContentsMargins(0, 0, 0, 0)
        rc.setSpacing(6)
        rc.addWidget(tg)
        rc.addWidget(ag)
        splitter.addWidget(right)

        splitter.setSizes([450, 500])
        root.addWidget(splitter, 1)

        self.refresh()

    @staticmethod
    def _quarter_months(year: int, q: int) -> list[tuple[int, int]]:
        start = (q - 1) * 3 + 1
        return [(year, m) for m in range(start, start + 3)]

    def refresh(self) -> None:
        data = self._q_combo.currentData()
        if data:
            self._load(*data)

    def _load(self, year: int, q: int) -> None:
        months = self._quarter_months(year, q)
        month_data = []
        total_pnl, total_trades, total_wins = 0.0, 0, 0
        daily_pnls: list[float] = []

        for yr, mo in months:
            mp, mt, mw, mt_est = 0.0, 0, 0, 0.0
            if self._journal:
                try:
                    s = self._journal.daily_summary() if hasattr(self._journal, "daily_summary") else {}
                    # For historical months use monthly aggregate if available
                    try:
                        import calendar
                        _, last_d = calendar.monthrange(yr, mo)
                        for dd in range(1, last_d + 1):
                            try:
                                ds = self._journal.daily_summary(f"{yr}-{mo:02d}-{dd:02d}") \
                                    if hasattr(self._journal, "daily_summary") else {}
                                mp += float(ds.get("total_pnl", 0))
                                mt += int(ds.get("trade_count", 0))
                                mw += int(ds.get("wins", 0))
                                daily_pnls.append(float(ds.get("total_pnl", 0)))
                            except Exception:
                                pass
                    except Exception:
                        pass
                except Exception:
                    pass
            if self._tax:
                try:
                    ts = self._tax.monthly_summary(yr, mo)
                    mt_est = float(ts.get("estimated_tax", 0)) if ts else 0.0
                except Exception:
                    pass
            month_data.append({"year": yr, "month": mo, "pnl": mp, "trades": mt, "wins": mw, "tax": mt_est})
            total_pnl    += mp
            total_trades += mt
            total_wins   += mw

        wr = total_wins / total_trades if total_trades else 0

        # Sharpe estimate
        import numpy as np
        sharpe = 0.0
        if len(daily_pnls) > 5:
            arr = np.array(daily_pnls)
            if arr.std() > 0:
                sharpe = (arr.mean() / arr.std()) * np.sqrt(252)

        self._c_pnl._value_lbl.setText(f"{total_pnl:+,.2f}")
        self._c_pnl._value_lbl.setStyleSheet(
            f"color:{_pnl_colour(total_pnl)};font-size:20px;font-weight:700;"
        )
        self._c_trades._value_lbl.setText(str(total_trades))
        self._c_winrate._value_lbl.setText(f"{wr:.0%}")
        self._c_sharpe._value_lbl.setText(f"{sharpe:.2f}")
        self._c_sharpe._value_lbl.setStyleSheet(
            f"color:{GREEN if sharpe >= 1 else YELLOW if sharpe >= 0 else RED};"
            f"font-size:20px;font-weight:700;"
        )
        tax_total = sum(d["tax"] for d in month_data)
        self._c_tax._value_lbl.setText(f"£{tax_total:,.0f}")

        # Chart
        self._plot.clear()
        import calendar as cal
        labels = [cal.month_abbr[d["month"]] for d in month_data]
        self._plot.addItem(pg.BarGraphItem(
            x=list(range(len(month_data))),
            height=[d["pnl"] for d in month_data],
            width=0.6,
            brushes=[QColor(GREEN if d["pnl"] >= 0 else RED) for d in month_data],
        ))
        self._plot.getAxis("bottom").setTicks([[(i, labels[i]) for i in range(len(labels))]])

        # Table
        self._month_tbl.setRowCount(len(month_data))
        import calendar as cal2
        for r, d in enumerate(month_data):
            wr2 = d["wins"] / d["trades"] if d["trades"] else 0
            self._month_tbl.setItem(r, 0, _item(f"{cal2.month_abbr[d['month']]} {d['year']}", FG1))
            self._month_tbl.setItem(r, 1, _item(str(d["trades"]), FG0))
            self._month_tbl.setItem(r, 2, _item(str(d["wins"]), GREEN))
            self._month_tbl.setItem(r, 3, _item(f"{wr2:.0%}", GREEN if wr2 >= 0.5 else YELLOW))
            self._month_tbl.setItem(r, 4, _item(f"{d['pnl']:+,.2f}", _pnl_colour(d["pnl"])))
            self._month_tbl.setItem(r, 5, _item(f"£{d['tax']:,.0f}", YELLOW if d["tax"] > 0 else FG2))

        # Attribution (journal-level)
        if self._journal and hasattr(self._journal, "source_attribution"):
            try:
                attr = self._journal.source_attribution()
                self._attr_tbl.setRowCount(len(attr))
                for r, (src, stats) in enumerate(sorted(attr.items(), key=lambda x: -x[1].get("net_pnl", 0))):
                    wr3 = float(stats.get("win_rate", 0))
                    net = float(stats.get("net_pnl", 0))
                    self._attr_tbl.setItem(r, 0, _item(src, ACCENT2))
                    self._attr_tbl.setItem(r, 1, _item(str(stats.get("total", 0)), FG0))
                    self._attr_tbl.setItem(r, 2, _item(f"{wr3:.0%}", GREEN if wr3 >= 0.5 else YELLOW))
                    self._attr_tbl.setItem(r, 3, _item(f"{net:+,.2f}", _pnl_colour(net)))
            except Exception:
                pass

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Quarterly Report",
            f"quarterly_report_{self._q_combo.currentText().replace(' ','_')}.csv",
            "CSV (*.csv)"
        )
        if not path:
            return
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Month", "Trades", "Wins", "Win%", "Net P&L", "Tax Est."])
        for r in range(self._month_tbl.rowCount()):
            w.writerow([self._month_tbl.item(r, c).text() if self._month_tbl.item(r, c) else ""
                        for c in range(self._month_tbl.columnCount())])
        with open(path, "w", newline="") as f:
            f.write(buf.getvalue())

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Month", "Trades", "Wins", "Win%", "Net P&L", "Tax Est."])
        for r in range(self._month_tbl.rowCount()):
            w.writerow([self._month_tbl.item(r, c).text() if self._month_tbl.item(r, c) else ""
                        for c in range(self._month_tbl.columnCount())])
        return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# AD-HOC TAB
# ═══════════════════════════════════════════════════════════════════════════════

class AdHocTab(QWidget):
    """Custom date range + report type → generate + export."""

    REPORT_TYPES = [
        "Full Report (P&L + Attribution + Forecast + Risk)",
        "P&L Summary",
        "Signal Attribution",
        "Forecast Accuracy",
        "Risk Metrics",
        "Tax Summary",
    ]

    def __init__(self, trade_journal=None, tax_calc=None,
                 forecast_tracker=None, dynamic_risk=None,
                 email_notifier=None, discord=None, slack=None):
        super().__init__()
        self._journal = trade_journal
        self._tax     = tax_calc
        self._ft      = forecast_tracker
        self._risk    = dynamic_risk
        self._email   = email_notifier
        self._discord = discord
        self._slack   = slack
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Controls row
        ctrl = QHBoxLayout()
        ctrl.addWidget(_lbl("From:", FG1, 10))
        self._from = QDateEdit()
        self._from.setCalendarPopup(True)
        self._from.setDate(QDate.currentDate().addDays(-30))
        self._from.setStyleSheet(
            f"background:{BG4};color:{FG0};border:1px solid {BORDER};padding:3px 6px;border-radius:3px;"
        )
        ctrl.addWidget(self._from)

        ctrl.addWidget(_lbl("To:", FG1, 10))
        self._to = QDateEdit()
        self._to.setCalendarPopup(True)
        self._to.setDate(QDate.currentDate())
        self._to.setStyleSheet(
            f"background:{BG4};color:{FG0};border:1px solid {BORDER};padding:3px 6px;border-radius:3px;"
        )
        ctrl.addWidget(self._to)

        ctrl.addWidget(_lbl("Report:", FG1, 10))
        self._type_combo = QComboBox()
        self._type_combo.addItems(self.REPORT_TYPES)
        self._type_combo.setMinimumWidth(300)
        self._type_combo.setStyleSheet(
            f"background:{BG4};color:{FG0};border:1px solid {BORDER};padding:3px 8px;border-radius:3px;"
        )
        ctrl.addWidget(self._type_combo)
        ctrl.addStretch()

        gen_btn = _btn("▶ Generate", GREEN, 100)
        gen_btn.clicked.connect(self._generate)
        ctrl.addWidget(gen_btn)
        root.addLayout(ctrl)

        # Export row
        exp_row = QHBoxLayout()
        exp_row.addStretch()
        csv_btn  = _btn("⬇ Export CSV",     ACCENT2, 110)
        email_btn= _btn("✉ Email Report",   PURPLE,  120)
        disc_btn = _btn("Discord",           "#5865F2", 90)
        slk_btn  = _btn("Slack",            "#4A154B", 90)
        csv_btn.clicked.connect(self._export_csv)
        email_btn.clicked.connect(self._email_report)
        disc_btn.clicked.connect(self._discord_report)
        slk_btn.clicked.connect(self._slack_report)
        for b in [csv_btn, email_btn, disc_btn, slk_btn]:
            exp_row.addWidget(b)
        root.addLayout(exp_row)

        # Output area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(
            f"QTextEdit{{background:{BG3};color:{FG0};border:1px solid {BORDER};"
            f"font-family:monospace;font-size:11px;border-radius:4px;}}"
        )
        root.addWidget(self._output, 1)

        self._last_report: dict = {}

    def _generate(self) -> None:
        from_date = self._from.date().toPyDate()
        to_date   = self._to.date().toPyDate()
        rtype     = self._type_combo.currentText()

        self._output.setPlainText("Generating report…")
        self._last_report = {}

        def _run():
            lines = [
                f"{'═' * 60}",
                f"  BinanceML Pro – {rtype}",
                f"  Period: {from_date.strftime('%d %b %Y')} → {to_date.strftime('%d %b %Y')}",
                f"  Generated: {datetime.now().strftime('%d %b %Y %H:%M:%S')}",
                f"{'═' * 60}",
                "",
            ]

            need_pnl  = "P&L" in rtype or "Full" in rtype
            need_attr = "Attribution" in rtype or "Full" in rtype
            need_fc   = "Forecast" in rtype or "Full" in rtype
            need_risk = "Risk" in rtype or "Full" in rtype
            need_tax  = "Tax" in rtype or "Full" in rtype

            if need_pnl and self._journal:
                lines += self._section_pnl(from_date, to_date)
            if need_attr and self._journal:
                lines += self._section_attr()
            if need_fc and self._ft:
                lines += self._section_forecast()
            if need_risk and self._risk:
                lines += self._section_risk()
            if need_tax and self._tax:
                lines += self._section_tax(from_date, to_date)

            self._last_report = {
                "title":   rtype,
                "from":    from_date.isoformat(),
                "to":      to_date.isoformat(),
                "content": "\n".join(lines),
            }
            from PyQt6.QtCore import QTimer as _QT
            _QT.singleShot(0, lambda: self._output.setPlainText("\n".join(lines)))

        threading.Thread(target=_run, daemon=True, name="adhoc-report").start()

    def _section_pnl(self, from_date: date, to_date: date) -> list[str]:
        lines = ["── P&L SUMMARY ─────────────────────────────────────"]
        try:
            total_pnl, total_trades, total_wins = 0.0, 0, 0
            d = from_date
            while d <= to_date:
                try:
                    s = self._journal.daily_summary(d.isoformat()) \
                        if hasattr(self._journal, "daily_summary") else {}
                    total_pnl    += float(s.get("total_pnl", 0))
                    total_trades += int(s.get("trade_count", 0))
                    total_wins   += int(s.get("wins", 0))
                except Exception:
                    pass
                d += timedelta(days=1)
            wr = total_wins / total_trades if total_trades else 0
            lines += [
                f"  Net P&L:      {total_pnl:+,.2f} USDT",
                f"  Total trades: {total_trades}",
                f"  Win rate:     {wr:.1%}",
                f"  Wins / Losses:{total_wins} / {total_trades - total_wins}",
                "",
            ]
        except Exception as exc:
            lines.append(f"  Error: {exc}")
        return lines

    def _section_attr(self) -> list[str]:
        lines = ["── SIGNAL ATTRIBUTION ──────────────────────────────"]
        try:
            attr = self._journal.source_attribution() if hasattr(self._journal, "source_attribution") else {}
            for src, stats in sorted(attr.items(), key=lambda x: -x[1].get("net_pnl", 0)):
                wr = float(stats.get("win_rate", 0))
                net = float(stats.get("net_pnl", 0))
                lines.append(
                    f"  {src:<30} {stats.get('total',0):>4} trades  "
                    f"WR {wr:.0%}  Net {net:+,.2f}"
                )
            lines.append("")
        except Exception as exc:
            lines.append(f"  Error: {exc}")
        return lines

    def _section_forecast(self) -> list[str]:
        lines = ["── FORECAST ACCURACY ───────────────────────────────"]
        try:
            acc = self._ft.get_accuracy() if hasattr(self._ft, "get_accuracy") else {}
            if acc:
                lines += [
                    f"  Accuracy:        {acc.get('rate', 0):.1%}  "
                    f"({acc.get('correct', 0)}/{acc.get('total', 0)})",
                    f"  Avg confidence:  {acc.get('avg_confidence', 0):.1%}",
                    f"  Calibration:     {acc.get('calibration', 0):.2f}  (1.0 = perfect)",
                    f"  Avg realised PnL:{acc.get('avg_actual_pnl', 0):+,.4f}",
                ]
            hb = self._ft.get_horizon_breakdown() if hasattr(self._ft, "get_horizon_breakdown") else []
            if hb:
                lines.append("  Horizon decay:")
                for h in hb:
                    lines.append(
                        f"    ≤{h.get('horizon', '?'):>3} bars  {h.get('rate', 0):.1%}  "
                        f"({h.get('n', 0)} forecasts)"
                    )
            lines.append("")
        except Exception as exc:
            lines.append(f"  Error: {exc}")
        return lines

    def _section_risk(self) -> list[str]:
        lines = ["── RISK METRICS ────────────────────────────────────"]
        try:
            s = self._risk.status() if hasattr(self._risk, "status") else {}
            lines += [
                f"  Circuit breaker:    {'BROKEN' if s.get('circuit_broken') else 'ACTIVE'}",
                f"  Drawdown:           {float(s.get('drawdown_pct', 0)):.1f}%",
                f"  Rolling win rate:   {float(s.get('rolling_win_rate', 0)):.1%}",
                f"  Consecutive losses: {s.get('consecutive_losses', 0)}",
                "",
            ]
        except Exception as exc:
            lines.append(f"  Error: {exc}")
        return lines

    def _section_tax(self, from_date: date, to_date: date) -> list[str]:
        lines = ["── TAX SUMMARY (UK CGT) ────────────────────────────"]
        try:
            # Summarise by month
            months_covered = set()
            d = from_date
            while d <= to_date:
                months_covered.add((d.year, d.month))
                d += timedelta(days=28)
            months_covered.add((to_date.year, to_date.month))

            total_net, total_tax = 0.0, 0.0
            for yr, mo in sorted(months_covered):
                try:
                    import calendar
                    ms = self._tax.monthly_summary(yr, mo)
                    if ms:
                        net = float(ms.get("net_gain", 0))
                        tax = float(ms.get("estimated_tax", 0))
                        total_net += net
                        total_tax += tax
                        lines.append(
                            f"  {calendar.month_abbr[mo]} {yr}  "
                            f"Net: £{net:+,.2f}  Est. tax: £{tax:,.2f}"
                        )
                except Exception:
                    pass
            lines += [
                f"  {'─' * 40}",
                f"  Period net gain:   £{total_net:+,.2f}",
                f"  Period tax est.:   £{total_tax:,.2f}",
                f"  Annual allowance:  £3,000",
                "",
            ]
        except Exception as exc:
            lines.append(f"  Error: {exc}")
        return lines

    def _export_csv(self) -> None:
        if not self._last_report:
            QMessageBox.warning(self, "Export", "Generate a report first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Ad-Hoc Report",
            f"adhoc_report_{date.today()}.txt", "Text (*.txt);;All (*)"
        )
        if path:
            with open(path, "w") as f:
                f.write(self._last_report.get("content", ""))

    def _email_report(self) -> None:
        if not self._last_report or not self._email:
            QMessageBox.warning(self, "Email", "Generate report and configure email first.")
            return
        content = self._last_report.get("content", "")
        self._email.send_text(
            subject=f"[BinanceML Pro] {self._last_report.get('title','')} – {date.today()}",
            message=content,
        )
        QMessageBox.information(self, "Email", "Report sent via email.")

    def _discord_report(self) -> None:
        if not self._last_report or not self._discord:
            QMessageBox.warning(self, "Discord", "Generate report and configure Discord first.")
            return
        content = self._last_report.get("content", "")
        self._discord.send_text(f"```\n{content[:1900]}\n```")
        QMessageBox.information(self, "Discord", "Report sent to Discord.")

    def _slack_report(self) -> None:
        if not self._last_report or not self._slack:
            QMessageBox.warning(self, "Slack", "Generate report and configure Slack first.")
            return
        content = self._last_report.get("content", "")
        self._slack.send_text(f"```\n{content[:2900]}\n```")
        QMessageBox.information(self, "Slack", "Report sent to Slack.")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN REPORTS WIDGET
# ═══════════════════════════════════════════════════════════════════════════════

class ReportsWidget(QWidget):
    """
    Top-level Reports panel.

    Constructor kwargs
    ──────────────────
      trade_journal     TradeJournal instance
      tax_calc          UKTaxCalculator instance
      forecast_tracker  ForecastTracker instance
      dynamic_risk      DynamicRiskManager instance
      email_notifier    EmailNotifier instance
      discord           DiscordNotifier instance
      slack             SlackNotifier instance
    """

    def __init__(
        self,
        trade_journal=None,
        tax_calc=None,
        forecast_tracker=None,
        dynamic_risk=None,
        email_notifier=None,
        discord=None,
        slack=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._journal = trade_journal
        self._tax     = tax_calc
        self._ft      = forecast_tracker
        self._risk    = dynamic_risk
        self._email   = email_notifier
        self._discord = discord
        self._slack   = slack
        self._build()
        # Auto-refresh daily tab every 60 s
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start(60_000)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        hdr = QWidget()
        hdr.setFixedHeight(40)
        hdr.setStyleSheet(f"background:{BG0};border-bottom:1px solid {BORDER};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 12, 0)
        title = _lbl("📊  REPORTS", ACCENT, 14, bold=True)
        hl.addWidget(title)
        hl.addStretch()
        export_all = _btn("⬇ Export All Tabs", ACCENT2, 130)
        export_all.clicked.connect(self._export_all)
        hl.addWidget(export_all)
        root.addWidget(hdr)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabWidget::pane{{border:none;background:{BG1};}}"
            f"QTabBar::tab{{background:{BG2};color:{FG1};padding:8px 18px;"
            f"border:none;border-bottom:2px solid transparent;font-size:11px;}}"
            f"QTabBar::tab:selected{{background:{BG3};color:{ACCENT};"
            f"border-bottom:2px solid {ACCENT};font-weight:700;}}"
            f"QTabBar::tab:hover{{color:{FG0};}}"
        )

        self._daily_tab = DailyTab(
            trade_journal=self._journal,
            dynamic_risk=self._risk,
            forecast_tracker=self._ft,
        )
        self._weekly_tab = WeeklyTab(trade_journal=self._journal)
        self._monthly_tab = MonthlyTab(
            trade_journal=self._journal,
            tax_calc=self._tax,
            email_notifier=self._email,
        )
        self._quarterly_tab = QuarterlyTab(
            trade_journal=self._journal,
            tax_calc=self._tax,
        )
        self._adhoc_tab = AdHocTab(
            trade_journal=self._journal,
            tax_calc=self._tax,
            forecast_tracker=self._ft,
            dynamic_risk=self._risk,
            email_notifier=self._email,
            discord=self._discord,
            slack=self._slack,
        )

        self._tabs.addTab(self._daily_tab,    "📅  Daily")
        self._tabs.addTab(self._weekly_tab,   "📆  Weekly")
        self._tabs.addTab(self._monthly_tab,  "🗓  Monthly")
        self._tabs.addTab(self._quarterly_tab,"📊  Quarterly")
        self._tabs.addTab(self._adhoc_tab,    "🔍  Ad-Hoc")

        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs, 1)

    def _on_tab_changed(self, idx: int) -> None:
        tab = self._tabs.widget(idx)
        if hasattr(tab, "refresh"):
            tab.refresh()

    def _auto_refresh(self) -> None:
        if self._tabs.currentIndex() == 0:
            self._daily_tab.refresh()

    def _export_all(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export All Reports", f"reports_{date.today()}.csv",
            "CSV (*.csv)"
        )
        if not path:
            return
        buf = io.StringIO()
        w = csv.writer(buf)
        for label, tab in [
            ("DAILY", self._daily_tab),
            ("WEEKLY", self._weekly_tab),
            ("MONTHLY", self._monthly_tab),
            ("QUARTERLY", self._quarterly_tab),
        ]:
            w.writerow([f"=== {label} ==="])
            try:
                content = tab.to_csv()
                buf.write(content)
            except Exception:
                pass
            w.writerow([])
        with open(path, "w", newline="") as f:
            f.write(buf.getvalue())
