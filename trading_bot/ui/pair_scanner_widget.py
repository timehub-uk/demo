"""
Pair Scanner Widget — Browsable table of all discovered Binance trading pairs
ranked by volume, activity, and ML priority score.

Tabs:
  Trading — All TRADING pairs ranked by score (HIGH / MEDIUM / LOW)
  Upcoming — PRE_TRADING / BREAK / HALT pairs (listed but not yet live)

Columns (Trading tab):
  Priority | Symbol | Price | 24h Change | Volume | Trades | Vol% | Score | Tradability

Columns (Upcoming tab):
  Status | Symbol | Base | Quote | Permissions | Listed | Note

Filtering (Trading tab):
  - Priority pill buttons (ALL / HIGH / MEDIUM / LOW)
  - Text search box (filters by symbol)

Actions:
  - Double-click Trading row → follows symbol on chart
  - "Add to Arbitrage" / "Watch Trends" buttons
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QAbstractItemView, QFrame, QTabWidget,
)
from loguru import logger

try:
    from ml.pair_scanner import PairScanner, PairInfo, PreTradingPair
except Exception:
    PairScanner    = None   # type: ignore[assignment, misc]
    PairInfo       = None   # type: ignore[assignment, misc]
    PreTradingPair = None   # type: ignore[assignment, misc]

from ui.styles import (
    ACCENT, BG1, BG2, BG3, BG4, BORDER, BORDER2,
    FG0, FG1, FG2, GREEN, RED, YELLOW,
)


# Priority colour map
_PRIORITY_COLORS = {
    "HIGH":   ("#00C864", BG1),    # green text
    "MEDIUM": ("#FFD700", BG1),    # gold text
    "LOW":    (FG2,       BG1),    # muted text
}


_TABLE_STYLE = f"""
    QTableWidget {{
        background:{BG1};
        color:{FG0};
        gridline-color:{BORDER};
        border:1px solid {BORDER2};
        border-radius:6px;
        font-size:12px;
        alternate-background-color:{BG2};
    }}
    QHeaderView::section {{
        background:{BG3};
        color:{FG1};
        border:none;
        border-bottom:1px solid {BORDER2};
        padding:5px 8px;
        font-size:12px;
        font-weight:bold;
    }}
    QTableWidget::item {{ padding:3px 6px; }}
    QTableWidget::item:selected {{ background:{BG4}; color:{FG0}; }}
"""


class PairScannerWidget(QWidget):
    """
    Ranked pair discovery widget with two tabs:
      Trading  — all TRADING pairs ranked by score
      Upcoming — PRE_TRADING / BREAK / HALT pairs (announced but not live)

    Pass ``pair_scanner``, optionally ``arb_detector`` and ``trend_scanner``
    to enable cross-module actions.
    """

    symbol_selected = pyqtSignal(str)   # double-click → chart follows

    _TRADING_COLS  = ["", "Symbol", "Price", "24h %", "Volume", "Trades", "Vol%", "Score", "Tradability"]
    _UPCOMING_COLS = ["Status", "Symbol", "Base", "Quote", "Permissions", "Detected", "Note"]

    def __init__(
        self,
        pair_scanner=None,
        arb_detector=None,
        trend_scanner=None,
        pair_ml_analyzer=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._scanner        = pair_scanner
        self._arb_detector   = arb_detector
        self._trend_scanner  = trend_scanner
        self._ml_analyzer    = pair_ml_analyzer
        self._ml_results: dict[str, dict] = {}

        self._all_pairs: list = []
        self._pre_trading_pairs: list = []
        self._filter_priority = "ALL"
        self._filter_text     = ""

        self._build_ui()
        self._connect_scanner()

        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._refresh_all)
        self._timer.start()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Title bar
        top = QHBoxLayout()
        title = QLabel("Pair Discovery — All Markets")
        title.setStyleSheet(f"color:{FG0}; font-size:14px; font-weight:bold;")
        top.addWidget(title)
        top.addStretch()
        ref_btn = QPushButton("↻")
        ref_btn.setFixedWidth(32)
        ref_btn.setToolTip("Force refresh")
        ref_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; font-size:14px; }}"
            f"QPushButton:hover {{ color:{ACCENT}; border-color:{ACCENT}; }}"
        )
        ref_btn.clicked.connect(self._refresh_all)
        top.addWidget(ref_btn)
        layout.addLayout(top)

        # Tabs
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("QTabBar::tab { padding:4px 12px; font-size:11px; }")
        layout.addWidget(self._tabs)

        # ── Tab 1: Trading ─────────────────────────────────────────────────────
        trading_tab = QWidget()
        t_layout = QVBoxLayout(trading_tab)
        t_layout.setContentsMargins(0, 4, 0, 0)
        t_layout.setSpacing(4)

        # Filter row
        pill_row = QHBoxLayout()
        pill_row.setSpacing(6)
        self._pills: dict[str, QPushButton] = {}
        for label, color in [("ALL", ACCENT), ("HIGH", GREEN), ("MEDIUM", YELLOW), ("LOW", FG2)]:
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setCheckable(True)
            btn.setChecked(label == "ALL")
            btn.setStyleSheet(
                f"QPushButton {{ background:{BG3}; color:{color}; border:1px solid {color}; "
                f"border-radius:4px; padding:2px 10px; font-size:11px; }}"
                f"QPushButton:checked {{ background:{color}; color:#000; }}"
            )
            btn.clicked.connect(lambda checked, l=label: self._on_priority_filter(l))
            self._pills[label] = btn
            pill_row.addWidget(btn)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.setFixedWidth(120)
        self._search.setStyleSheet(
            f"QLineEdit {{ background:{BG3}; color:{FG0}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 6px; }}"
        )
        self._search.textChanged.connect(self._on_search_changed)
        pill_row.addWidget(self._search)
        pill_row.addStretch()

        add_arb_btn = QPushButton("+ Arbitrage")
        add_arb_btn.setFixedHeight(24)
        add_arb_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{ACCENT}; border:1px solid {ACCENT}; "
            f"border-radius:4px; padding:2px 10px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{ACCENT}; color:#000; }}"
        )
        add_arb_btn.clicked.connect(self._on_add_to_arb)
        pill_row.addWidget(add_arb_btn)

        add_trend_btn = QPushButton("+ Trend Watch")
        add_trend_btn.setFixedHeight(24)
        add_trend_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{GREEN}; border:1px solid {GREEN}; "
            f"border-radius:4px; padding:2px 10px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{GREEN}; color:#000; }}"
        )
        add_trend_btn.clicked.connect(self._on_add_to_trend)
        pill_row.addWidget(add_trend_btn)
        t_layout.addLayout(pill_row)

        # Trading table
        self._table = QTableWidget(0, len(self._TRADING_COLS))
        self._table.setHorizontalHeaderLabels(self._TRADING_COLS)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for i in range(2, len(self._TRADING_COLS)):
            self._table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.setMinimumHeight(300)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        self._table.setStyleSheet(_TABLE_STYLE)
        t_layout.addWidget(self._table)

        self._status = QLabel("Waiting for pair data…")
        self._status.setStyleSheet(f"color:{FG2}; font-size:11px;")
        t_layout.addWidget(self._status)

        self._tabs.addTab(trading_tab, "📊  Trading")

        # ── Tab 2: Upcoming ────────────────────────────────────────────────────
        upcoming_tab = QWidget()
        u_layout = QVBoxLayout(upcoming_tab)
        u_layout.setContentsMargins(0, 4, 0, 0)
        u_layout.setSpacing(4)

        u_desc = QLabel(
            "Pairs listed on Binance but NOT yet tradeable  ·  "
            "PRE_TRADING = upcoming launch  ·  BREAK/HALT = temporarily suspended"
        )
        u_desc.setStyleSheet(f"color:{FG2}; font-size:11px;")
        u_layout.addWidget(u_desc)

        self._upcoming_table = QTableWidget(0, len(self._UPCOMING_COLS))
        self._upcoming_table.setHorizontalHeaderLabels(self._UPCOMING_COLS)
        for i in range(len(self._UPCOMING_COLS)):
            self._upcoming_table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents
            )
        self._upcoming_table.horizontalHeader().setSectionResizeMode(
            len(self._UPCOMING_COLS) - 1, QHeaderView.ResizeMode.Stretch
        )
        self._upcoming_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._upcoming_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._upcoming_table.verticalHeader().setVisible(False)
        self._upcoming_table.setAlternatingRowColors(True)
        self._upcoming_table.setSortingEnabled(True)
        self._upcoming_table.setMinimumHeight(300)
        self._upcoming_table.setStyleSheet(_TABLE_STYLE)
        u_layout.addWidget(self._upcoming_table)

        self._upcoming_status = QLabel("Scanning for upcoming pairs…")
        self._upcoming_status.setStyleSheet(f"color:{FG2}; font-size:11px;")
        u_layout.addWidget(self._upcoming_status)

        self._tabs.addTab(upcoming_tab, "🔜  Upcoming")

    # ── Scanner integration ────────────────────────────────────────────────────

    def _connect_scanner(self) -> None:
        if self._scanner:
            try:
                self._scanner.on_update(self._on_scanner_update)
            except Exception as exc:
                logger.warning(f"PairScannerWidget: scanner connect failed: {exc!r}")
            try:
                self._scanner.on_pre_trading(self._on_pre_trading_update)
            except Exception as exc:
                logger.warning(f"PairScannerWidget: pre_trading connect failed: {exc!r}")
        if self._ml_analyzer:
            try:
                self._ml_analyzer.on_update(self._on_ml_update)
            except Exception as exc:
                logger.warning(f"PairScannerWidget: ML analyzer connect failed: {exc!r}")

    def _on_ml_update(self, results: list) -> None:
        self._ml_results = {r["symbol"]: r for r in results}
        QTimer.singleShot(0, self._refresh_table)

    def _on_scanner_update(self, pairs: list) -> None:
        self._all_pairs = list(pairs)
        QTimer.singleShot(0, self._refresh_table)

    def _on_pre_trading_update(self, pairs: list) -> None:
        """Called from scanner background thread when new PRE_TRADING pairs appear."""
        # Merge with full list from scanner
        QTimer.singleShot(0, self._refresh_upcoming)

    def _refresh_all(self) -> None:
        self._refresh_table()
        self._refresh_upcoming()

    # ── Table rendering ────────────────────────────────────────────────────────

    def _refresh_upcoming(self) -> None:
        """Refresh the Upcoming (pre-trading) tab."""
        pairs: list = []
        if self._scanner:
            try:
                pairs = self._scanner.get_pre_trading_pairs()
            except Exception:
                pass

        _STATUS_COLORS = {
            "PRE_TRADING":  "#00CCFF",
            "BREAK":        "#FFB347",
            "HALT":         "#FF4444",
            "END_OF_DAY":   "#AAAAAA",
            "POST_TRADING": "#888888",
        }

        self._upcoming_table.setSortingEnabled(False)
        self._upcoming_table.setRowCount(len(pairs))

        for row, p in enumerate(pairs):
            col = _STATUS_COLORS.get(p.status, FG2)

            def _item(text: str, fg: str = FG1) -> QTableWidgetItem:
                it = QTableWidgetItem(str(text))
                it.setForeground(QColor(fg))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                return it

            # Status badge
            badge = QTableWidgetItem(f"{p.status_emoji} {p.status}")
            badge.setForeground(QColor(col))
            badge.setFont(QFont("monospace", 10, QFont.Weight.Bold))
            badge.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self._upcoming_table.setItem(row, 0, badge)

            # Symbol
            sym_item = QTableWidgetItem(p.symbol)
            sym_item.setFont(QFont("monospace", 11, QFont.Weight.Bold))
            sym_item.setForeground(QColor(FG0))
            self._upcoming_table.setItem(row, 1, sym_item)

            self._upcoming_table.setItem(row, 2, _item(p.base,  FG1))
            self._upcoming_table.setItem(row, 3, _item(p.quote, FG2))

            # Permissions
            perms = ", ".join(p.permissions) if p.permissions else "—"
            self._upcoming_table.setItem(row, 4, _item(perms, FG2))

            # Detected at
            detected = p.detected_at[:19].replace("T", " ") if p.detected_at else "—"
            self._upcoming_table.setItem(row, 5, _item(detected, FG2))

            # Note
            orders = ", ".join(p.order_types[:3]) if p.order_types else "—"
            self._upcoming_table.setItem(row, 6, _item(f"Orders: {orders}", FG2))

            self._upcoming_table.setRowHeight(row, 28)

        self._upcoming_table.setSortingEnabled(True)

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self._upcoming_status.setText(
            f"{len(pairs)} upcoming / suspended pairs  ·  Updated {ts}"
        )
        # Update tab badge
        self._tabs.setTabText(1, f"🔜  Upcoming ({len(pairs)})")

    def _refresh_table(self) -> None:
        pairs = list(self._all_pairs)
        if not pairs and self._scanner:
            pairs = self._scanner.get_all_pairs()

        # Apply filters
        if self._filter_priority != "ALL":
            pairs = [p for p in pairs if p.priority == self._filter_priority]
        if self._filter_text:
            txt = self._filter_text.upper()
            pairs = [p for p in pairs if txt in p.symbol]

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(pairs))

        for row, p in enumerate(pairs):
            txt_col, _ = _PRIORITY_COLORS.get(p.priority, (FG2, BG1))

            # Priority badge
            pri_item = QTableWidgetItem(f"{p.priority_emoji} {p.priority}")
            pri_item.setForeground(QColor(txt_col))
            pri_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, pri_item)

            # Symbol
            sym_item = QTableWidgetItem(p.symbol)
            sym_item.setFont(QFont("monospace", 11, QFont.Weight.Bold))
            sym_item.setForeground(QColor(FG0))
            self._table.setItem(row, 1, sym_item)

            # Price
            self._table.setItem(row, 2, self._num_item(self._fmt_price(p.last_price)))

            # 24h %
            sign    = "+" if p.price_change_pct >= 0 else ""
            pct_itm = QTableWidgetItem(f"{sign}{p.price_change_pct:.2f}%")
            pct_itm.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            pct_itm.setForeground(QColor(GREEN if p.price_change_pct >= 0 else RED))
            self._table.setItem(row, 3, pct_itm)

            # Volume
            self._table.setItem(row, 4, self._num_item(self._fmt_volume(p.quote_volume)))

            # Trades
            self._table.setItem(row, 5, self._num_item(f"{p.trade_count:,}"))

            # Volatility
            self._table.setItem(row, 6, self._num_item(f"{p.volatility_pct:.2f}%"))

            # Priority score
            score_itm = QTableWidgetItem(f"{p.priority_score:.3f}")
            score_itm.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            score_itm.setForeground(QColor(ACCENT))
            self._table.setItem(row, 7, score_itm)

            # Tradability score (from PairMLAnalyzer)
            ml_rec = self._ml_results.get(p.symbol)
            if ml_rec:
                tscore = ml_rec.get("tradability_score", 0.0)
                sig    = ml_rec.get("ml_signal", "HOLD")
                t_txt  = f"{tscore:.3f}  {sig}"
                t_col  = GREEN if sig == "BUY" else (RED if sig == "SELL" else FG2)
                t_item = QTableWidgetItem(t_txt)
                t_item.setForeground(QColor(t_col))
                t_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                trend_d = ml_rec.get("trend_detail", {})
                t_item.setToolTip(
                    f"<b>{p.symbol} — Tradability</b><br>"
                    f"Score: {tscore:.3f}<br>"
                    f"Signal: {sig} ({ml_rec.get('ml_confidence', 0):.0%})<br>"
                    f"Regime: {ml_rec.get('regime', '—')}<br>"
                    f"Whale: {ml_rec.get('whale_score', 0):.2f}  "
                    f"Sentiment: {ml_rec.get('sentiment_score', 0):.2f}<br>"
                    f"Trends: {', '.join(f'{k}:{v[:1]}' for k, v in trend_d.items())}"
                )
            else:
                t_item = QTableWidgetItem("—")
                t_item.setForeground(QColor(FG2))
                t_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 8, t_item)

            self._table.setRowHeight(row, 28)

        self._table.setSortingEnabled(True)

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        total_tradable = 0
        if self._scanner:
            try:
                total_tradable = len(self._scanner.get_all_tradable_symbols())
            except Exception:
                total_tradable = len(self._all_pairs)
        showing = len(pairs)
        total   = len(self._all_pairs)
        self._status.setText(
            f"Showing {showing} of {total} ranked  ·  "
            f"Total tradable on Binance: {total_tradable:,}  ·  Updated {ts}"
        )
        self._tabs.setTabText(0, f"📊  Trading ({total:,})")

    @staticmethod
    def _num_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(QColor(FG1))
        return item

    @staticmethod
    def _fmt_price(price: float) -> str:
        if price >= 1000:
            return f"{price:,.2f}"
        if price >= 1:
            return f"{price:.4f}"
        if price >= 0.001:
            return f"{price:.6f}"
        return f"{price:.8f}"

    @staticmethod
    def _fmt_volume(vol: float) -> str:
        if vol >= 1_000_000_000:
            return f"{vol/1_000_000_000:.2f}B"
        if vol >= 1_000_000:
            return f"{vol/1_000_000:.1f}M"
        if vol >= 1_000:
            return f"{vol/1_000:.0f}K"
        return f"{vol:.0f}"

    # ── Interactions ───────────────────────────────────────────────────────────

    def _on_priority_filter(self, label: str) -> None:
        self._filter_priority = label
        for k, btn in self._pills.items():
            btn.setChecked(k == label)
        self._refresh_table()

    def _on_search_changed(self, text: str) -> None:
        self._filter_text = text.strip()
        self._refresh_table()

    def _on_row_double_clicked(self, index) -> None:
        row = index.row()
        item = self._table.item(row, 1)
        if item:
            self.symbol_selected.emit(item.text())

    def _on_add_to_arb(self) -> None:
        sym = self._selected_symbol()
        if not sym or not self._arb_detector:
            return
        try:
            base = sym[:-4] if sym.endswith("USDT") else sym
            self._arb_detector.add_pair(sym, base + "USDT")
            logger.info(f"PairScannerWidget: added {sym} to ArbitrageDetector")
        except Exception as exc:
            logger.warning(f"PairScannerWidget: arb add failed: {exc!r}")

    def _on_add_to_trend(self) -> None:
        sym = self._selected_symbol()
        if not sym or not self._trend_scanner:
            return
        try:
            self._trend_scanner.add_symbol(sym)
            logger.info(f"PairScannerWidget: added {sym} to TrendScanner")
        except Exception as exc:
            logger.warning(f"PairScannerWidget: trend add failed: {exc!r}")

    def _selected_symbol(self) -> Optional[str]:
        row = self._table.currentRow()
        item = self._table.item(row, 1)
        return item.text() if item else None
