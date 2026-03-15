"""
L1 / L2 order book widget.
Displays live bid/ask depth with colour-coded size bars and spread info.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
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
    - L1 best bid/ask highlight
    - Real-time updates via Redis / WebSocket
    """

    MAX_ROWS = 20

    def __init__(self, symbol: str = "BTCUSDT", parent=None) -> None:
        super().__init__(parent)
        self._symbol = symbol
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(500)

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
        l1_frame.setFixedHeight(48)
        l1_frame.setStyleSheet(f"background:{BG4};")
        ll = QHBoxLayout(l1_frame)
        ll.setContentsMargins(10, 4, 10, 4)

        self.lbl_best_bid = QLabel("—")
        self.lbl_best_bid.setStyleSheet(f"color:{GREEN}; font-size:18px; font-weight:700;")
        self.lbl_bid_size = QLabel("")
        self.lbl_bid_size.setStyleSheet(f"color:{FG1}; font-size:11px;")

        self.lbl_best_ask = QLabel("—")
        self.lbl_best_ask.setStyleSheet(f"color:{RED}; font-size:18px; font-weight:700;")
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

        # Depth tables side by side
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Asks table (top half – reversed)
        self.asks_table = self._create_table(side="ASK")
        splitter.addWidget(self.asks_table)

        # Bids table (bottom half)
        self.bids_table = self._create_table(side="BID")
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
        tbl.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        tbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tbl.verticalHeader().setDefaultSectionSize(18)
        tbl.setStyleSheet(f"""
            QTableWidget {{ background:{BG2}; font-size:12px; }}
            QHeaderView::section {{ background:{BG3}; color:{colour}; font-size:10px;
                                     font-weight:700; letter-spacing:0.5px; }}
        """)
        return tbl

    # ── Data update ─────────────────────────────────────────────────────
    def update_book(self, bids: list, asks: list) -> None:
        if not bids or not asks:
            return

        # Sort bids desc, asks asc
        bids_sorted = sorted(bids, key=lambda x: float(x[0]), reverse=True)[:self.MAX_ROWS]
        asks_sorted = sorted(asks, key=lambda x: float(x[0]))[:self.MAX_ROWS]

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

    def _fill_table(self, tbl: QTableWidget, data: list, colour: str, max_vol: float, side: str) -> None:
        for row_idx in range(self.MAX_ROWS):
            if row_idx < len(data):
                price, size = float(data[row_idx][0]), float(data[row_idx][1])
                total = sum(float(d[1]) for d in data[:row_idx+1])
                bar_pct = size / max_vol if max_vol > 0 else 0

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
        """Pull latest order book from Redis."""
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
