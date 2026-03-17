"""
L1 / L2 order book widget.
Displays live bid/ask depth with colour-coded size bars and spread info.
Clicking a price row populates the order-entry panel (via price_clicked signal).
Last trade row flashes to highlight execution.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QSplitter, QProgressBar,
)

from ui.styles import GREEN, RED, ACCENT, BG2, BG3, BG4, BORDER, FG0, FG1, FG2


class OrderBookWidget(QWidget):
    """
    Professional L2 order book panel.
    - Top N bids and asks with price, size, total, and depth bar
    - Spread display
    - L1 best bid/ask highlight with size
    - Click any price row to populate order-entry form (price_clicked signal)
    - Last-trade row flashes to highlight execution
    - Real-time updates every ~1 second via Redis / WebSocket
    """

    # Emitted when user clicks a price row: (price, side) where side="BID"/"ASK"
    price_clicked = pyqtSignal(float, str)

    MAX_ROWS = 30

    # Flash colours: alternating between highlight and normal
    _FLASH_BID_BG = "#00FF7755"
    _FLASH_ASK_BG = "#FF443355"
    _FLASH_CYCLES = 6     # number of on/off cycles

    def __init__(self, symbol: str = "BTCUSDT", parent=None) -> None:
        super().__init__(parent)
        self._symbol = symbol

        # Last-trade tracking for flash highlight
        self._last_trade_price: float = 0.0
        self._last_trade_side: str = ""
        self._flash_row: int = -1
        self._flash_side: str = ""
        self._flash_count: int = 0
        self._flash_on: bool = False

        # Cache sorted data for click→price lookup
        self._bids_data: list = []
        self._asks_data: list = []

        self._setup_ui()

        # 1-second update timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)

        # Flash timer (200 ms per half-cycle)
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(200)
        self._flash_timer.timeout.connect(self._on_flash_tick)

    # ── UI setup ───────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(36)
        header.setStyleSheet(f"background:{BG3}; border-bottom:1px solid {BORDER};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 10, 0)
        lbl = QLabel("ORDER BOOK")
        lbl.setStyleSheet(f"color:{FG1}; font-size:11px; font-weight:700; letter-spacing:1px;")
        hl.addWidget(lbl)
        hl.addStretch()
        self.lbl_spread = QLabel("Spread: —")
        self.lbl_spread.setStyleSheet(f"color:{ACCENT}; font-size:11px;")
        hl.addWidget(self.lbl_spread)
        layout.addWidget(header)

        # Best bid/ask bar
        l1_frame = QFrame()
        l1_frame.setFixedHeight(52)
        l1_frame.setStyleSheet(f"background:{BG4};")
        ll = QHBoxLayout(l1_frame)
        ll.setContentsMargins(10, 4, 10, 4)

        self.lbl_best_bid = QLabel("—")
        self.lbl_best_bid.setStyleSheet(f"color:{GREEN}; font-size:20px; font-weight:700;")
        self.lbl_bid_size = QLabel("")
        self.lbl_bid_size.setStyleSheet(f"color:{FG1}; font-size:11px;")

        self.lbl_best_ask = QLabel("—")
        self.lbl_best_ask.setStyleSheet(f"color:{RED}; font-size:20px; font-weight:700;")
        self.lbl_ask_size = QLabel("")
        self.lbl_ask_size.setStyleSheet(f"color:{FG1}; font-size:11px;")

        bid_col = QVBoxLayout()
        bid_col.addWidget(QLabel("BID", alignment=Qt.AlignmentFlag.AlignLeft))
        bid_col.addWidget(self.lbl_best_bid)
        bid_col.addWidget(self.lbl_bid_size)

        ask_col = QVBoxLayout()
        ask_col.addWidget(QLabel("ASK", alignment=Qt.AlignmentFlag.AlignRight))
        ask_col.addWidget(self.lbl_best_ask)
        ask_col.addWidget(self.lbl_ask_size)

        ll.addLayout(bid_col)
        ll.addStretch()
        ll.addLayout(ask_col)
        layout.addWidget(l1_frame)

        # Last-trade ticker strip
        last_frame = QFrame()
        last_frame.setFixedHeight(24)
        last_frame.setStyleSheet(f"background:{BG3}; border-bottom:1px solid {BORDER};")
        lfl = QHBoxLayout(last_frame)
        lfl.setContentsMargins(10, 2, 10, 2)
        lfl.setSpacing(6)
        last_lbl = QLabel("LAST")
        last_lbl.setStyleSheet(f"color:{FG2}; font-size:10px; font-weight:700;")
        lfl.addWidget(last_lbl)
        self.lbl_last_trade = QLabel("—")
        self.lbl_last_trade.setStyleSheet(f"color:{FG1}; font-size:11px; font-family:monospace; font-weight:700;")
        lfl.addWidget(self.lbl_last_trade)
        lfl.addStretch()
        self.lbl_last_side = QLabel("")
        self.lbl_last_side.setStyleSheet(f"color:{FG2}; font-size:10px;")
        lfl.addWidget(self.lbl_last_side)
        layout.addWidget(last_frame)

        # Depth tables side by side
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Asks table
        self.asks_table = self._create_table(side="ASK")
        self.asks_table.cellClicked.connect(lambda r, c: self._on_cell_clicked(r, "ASK"))
        splitter.addWidget(self.asks_table)

        # Bids table
        self.bids_table = self._create_table(side="BID")
        self.bids_table.cellClicked.connect(lambda r, c: self._on_cell_clicked(r, "BID"))
        splitter.addWidget(self.bids_table)

        layout.addWidget(splitter, 1)

        # Depth imbalance bar
        imbalance_frame = QFrame()
        imbalance_frame.setFixedHeight(24)
        imbalance_frame.setStyleSheet(f"background:{BG3};")
        il = QHBoxLayout(imbalance_frame)
        il.setContentsMargins(6, 4, 6, 4)
        il.setSpacing(4)
        il.addWidget(QLabel("BID", alignment=Qt.AlignmentFlag.AlignLeft))
        self.depth_bar = QProgressBar()
        self.depth_bar.setRange(0, 100)
        self.depth_bar.setValue(50)
        self.depth_bar.setTextVisible(False)
        self.depth_bar.setStyleSheet(f"""
            QProgressBar {{ background:{RED}44; border:none; border-radius:3px; }}
            QProgressBar::chunk {{ background:{GREEN}; border-radius:3px; }}
        """)
        il.addWidget(self.depth_bar, 1)
        il.addWidget(QLabel("ASK", alignment=Qt.AlignmentFlag.AlignRight))
        layout.addWidget(imbalance_frame)

    def _create_table(self, side: str) -> QTableWidget:
        colour = GREEN if side == "BID" else RED
        tbl = QTableWidget(self.MAX_ROWS, 3)
        tbl.setHorizontalHeaderLabels(["Price", "Size", "Total"])
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tbl.verticalHeader().setVisible(False)
        tbl.setShowGrid(False)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tbl.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        tbl.verticalHeader().setDefaultSectionSize(20)
        tbl.setCursor(Qt.CursorShape.PointingHandCursor)
        tbl.setToolTip("Click a price to populate the order entry form")
        tbl.setStyleSheet(f"""
            QTableWidget {{ background:{BG2}; font-size:12px; }}
            QTableWidget::item:selected {{ background:{colour}33; }}
            QTableWidget::item:hover {{ background:{colour}1A; }}
            QHeaderView::section {{ background:{BG3}; color:{colour}; font-size:10px;
                                     font-weight:700; letter-spacing:0.5px; }}
        """)
        return tbl

    # ── Click handler ─────────────────────────────────────────────────
    def _on_cell_clicked(self, row: int, side: str) -> None:
        data = self._bids_data if side == "BID" else self._asks_data
        if row < len(data):
            price = float(data[row][0])
            self.price_clicked.emit(price, side)

    # ── Last-trade flash ──────────────────────────────────────────────
    def set_last_trade(self, price: float, side: str) -> None:
        """
        Call with the last executed trade price and side to trigger a flash
        highlight on the matching order-book row.
        """
        self._last_trade_price = price
        self._last_trade_side  = side

        # Find matching row
        data = self._bids_data if side == "BID" else self._asks_data
        tbl  = self.bids_table if side == "BID" else self.asks_table
        row  = -1
        for i, entry in enumerate(data):
            if abs(float(entry[0]) - price) < 1e-8:
                row = i
                break
        if row == -1 and data:
            # Nearest row
            prices = [float(e[0]) for e in data]
            row = min(range(len(prices)), key=lambda i: abs(prices[i] - price))

        self._flash_row   = row
        self._flash_side  = side
        self._flash_count = 0
        self._flash_on    = False
        if row >= 0:
            self._flash_timer.start()

        # Update ticker strip
        colour = GREEN if side == "BID" else RED
        self.lbl_last_trade.setText(f"{price:,.4f}")
        self.lbl_last_trade.setStyleSheet(
            f"color:{colour}; font-size:11px; font-family:monospace; font-weight:700;"
        )
        self.lbl_last_side.setText(side)
        self.lbl_last_side.setStyleSheet(f"color:{colour}; font-size:10px; font-weight:600;")

    def _on_flash_tick(self) -> None:
        if self._flash_count >= self._FLASH_CYCLES * 2:
            self._flash_timer.stop()
            self._redraw_row_normal(self._flash_row, self._flash_side)
            return

        self._flash_on = not self._flash_on
        tbl  = self.bids_table if self._flash_side == "BID" else self.asks_table
        row  = self._flash_row
        if row < 0 or row >= tbl.rowCount():
            self._flash_timer.stop()
            return

        if self._flash_on:
            flash_col = self._FLASH_BID_BG if self._flash_side == "BID" else self._FLASH_ASK_BG
            for col in range(3):
                item = tbl.item(row, col)
                if item:
                    item.setBackground(QBrush(QColor(flash_col)))
        else:
            self._redraw_row_normal(row, self._flash_side)

        self._flash_count += 1

    def _redraw_row_normal(self, row: int, side: str) -> None:
        """Restore normal row background after flash."""
        tbl  = self.bids_table if side == "BID" else self.asks_table
        colour = GREEN if side == "BID" else RED
        bg_col = (GREEN + "22") if side == "BID" else (RED + "22")
        if row < 0 or row >= tbl.rowCount():
            return
        for col in range(3):
            item = tbl.item(row, col)
            if item:
                item.setBackground(QBrush(QColor(bg_col if col == 0 else BG2)))

    # ── Data update ─────────────────────────────────────────────────────
    def update_book(self, bids: list, asks: list) -> None:
        if not bids or not asks:
            return

        # Sort bids desc, asks asc
        bids_sorted = sorted(bids, key=lambda x: float(x[0]), reverse=True)[:self.MAX_ROWS]
        asks_sorted = sorted(asks, key=lambda x: float(x[0]))[:self.MAX_ROWS]

        # Cache for click lookup
        self._bids_data = bids_sorted
        self._asks_data = asks_sorted

        best_bid = float(bids_sorted[0][0]) if bids_sorted else 0
        best_ask = float(asks_sorted[0][0]) if asks_sorted else 0
        spread = best_ask - best_bid
        spread_pct = (spread / best_bid * 100) if best_bid > 0 else 0

        self.lbl_best_bid.setText(f"{best_bid:,.4f}")
        self.lbl_best_ask.setText(f"{best_ask:,.4f}")
        self.lbl_spread.setText(f"Spread: {spread:.4f} ({spread_pct:.3f}%)")
        if bids_sorted:
            self.lbl_bid_size.setText(f"Vol: {float(bids_sorted[0][1]):,.4f}")
        if asks_sorted:
            self.lbl_ask_size.setText(f"Vol: {float(asks_sorted[0][1]):,.4f}")

        # Fill tables
        max_bid_vol = max((float(b[1]) for b in bids_sorted), default=1)
        max_ask_vol = max((float(a[1]) for a in asks_sorted), default=1)
        total_bid = sum(float(b[1]) for b in bids_sorted)
        total_ask = sum(float(a[1]) for a in asks_sorted)

        # Imbalance bar
        if total_bid + total_ask > 0:
            bid_pct = int(total_bid / (total_bid + total_ask) * 100)
            self.depth_bar.setValue(bid_pct)

        self._fill_table(self.bids_table, bids_sorted, GREEN, max_bid_vol, "BID")
        self._fill_table(self.asks_table, asks_sorted, RED, max_ask_vol, "ASK")

        # Auto-pull latest trade from Redis if available
        try:
            from db.redis_client import RedisClient
            rc = RedisClient()
            trade = rc.get_last_trade(self._symbol) if hasattr(rc, "get_last_trade") else None
            if trade:
                t_price = float(trade.get("price", 0))
                t_side  = trade.get("side", "BID").upper()
                if t_price and t_price != self._last_trade_price:
                    self.set_last_trade(t_price, t_side)
        except Exception:
            pass

    def _fill_table(self, tbl: QTableWidget, data: list, colour: str, max_vol: float, side: str) -> None:
        for row_idx in range(self.MAX_ROWS):
            if row_idx < len(data):
                price, size = float(data[row_idx][0]), float(data[row_idx][1])
                total = sum(float(d[1]) for d in data[:row_idx+1])

                tbl.setItem(row_idx, 0, self._make_item(f"{price:,.4f}", colour))
                tbl.setItem(row_idx, 1, self._make_item(f"{size:.4f}", FG0))
                tbl.setItem(row_idx, 2, self._make_item(f"{total:.4f}", FG1))

                # Background depth bar (subtle)
                bg_colour = (GREEN + "22") if side == "BID" else (RED + "22")
                for col in range(3):
                    item = tbl.item(row_idx, col)
                    if item:
                        item.setBackground(QBrush(QColor(bg_colour if col == 0 else BG2)))
            else:
                for col in range(3):
                    tbl.setItem(row_idx, col, QTableWidgetItem(""))

    @staticmethod
    def _make_item(text: str, colour: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setForeground(QBrush(QColor(colour)))
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _refresh(self) -> None:
        """Pull latest order book from Redis every second."""
        try:
            from db.redis_client import RedisClient
            rc = RedisClient()
            book = rc.get_orderbook(self._symbol)
            if book:
                bids = book.get("bids", [])
                asks = book.get("asks", [])
                self.update_book(bids, asks)
        except Exception:
            pass

    def set_symbol(self, symbol: str) -> None:
        self._symbol = symbol
