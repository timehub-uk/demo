"""
Trading panel – manual order entry, active orders, trade history,
portfolio overview, and P&L ledger.
"""

from __future__ import annotations

import time
from decimal import Decimal

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QDoubleSpinBox, QComboBox, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, QSplitter, QTabWidget,
    QCheckBox, QFormLayout,
)

from ui.styles import ACCENT, GREEN, RED, YELLOW, BG2, BG3, BG4, BORDER, FG0, FG1, FG2


class OrderEntryPanel(QGroupBox):
    """Manual buy/sell order entry widget."""

    order_submitted = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__("Order Entry", parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Symbol + type row
        row1 = QHBoxLayout()
        self.sym_edit = QLineEdit("BTCUSDT")
        self.sym_edit.setFixedWidth(110)
        row1.addWidget(QLabel("Symbol:"))
        row1.addWidget(self.sym_edit)
        self.order_type = QComboBox()
        for t in ["LIMIT","MARKET","STOP_LIMIT","OCO"]:
            self.order_type.addItem(t)
        row1.addWidget(QLabel("Type:"))
        row1.addWidget(self.order_type)
        row1.addStretch()
        layout.addLayout(row1)

        # Price + quantity
        form = QFormLayout()
        form.setSpacing(8)

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setDecimals(6)
        self.price_spin.setRange(0, 1_000_000)
        self.price_spin.setPrefix("$ ")
        self.price_spin.setSingleStep(0.1)
        form.addRow("Price:", self.price_spin)

        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setDecimals(6)
        self.qty_spin.setRange(0.000001, 1_000_000)
        form.addRow("Quantity:", self.qty_spin)

        self.stop_spin = QDoubleSpinBox()
        self.stop_spin.setDecimals(6)
        self.stop_spin.setRange(0, 1_000_000)
        self.stop_spin.setPrefix("$ ")
        form.addRow("Stop Loss:", self.stop_spin)

        self.tp_spin = QDoubleSpinBox()
        self.tp_spin.setDecimals(6)
        self.tp_spin.setRange(0, 1_000_000)
        self.tp_spin.setPrefix("$ ")
        form.addRow("Take Profit:", self.tp_spin)

        layout.addLayout(form)

        # Total display
        total_row = QHBoxLayout()
        total_row.addWidget(QLabel("Total (USDT):"))
        self.total_lbl = QLabel("0.000000")
        self.total_lbl.setStyleSheet(f"font-size:14px; font-weight:700; color:{ACCENT};")
        total_row.addWidget(self.total_lbl)
        total_row.addStretch()
        layout.addLayout(total_row)

        self.price_spin.valueChanged.connect(self._update_total)
        self.qty_spin.valueChanged.connect(self._update_total)

        # Buy / Sell buttons
        btn_row = QHBoxLayout()
        self.buy_btn = QPushButton("▲ BUY")
        self.buy_btn.setObjectName("btn_buy")
        self.buy_btn.setFixedHeight(44)
        self.buy_btn.clicked.connect(lambda: self._submit("BUY"))
        btn_row.addWidget(self.buy_btn)

        self.sell_btn = QPushButton("▼ SELL")
        self.sell_btn.setObjectName("btn_sell")
        self.sell_btn.setFixedHeight(44)
        self.sell_btn.clicked.connect(lambda: self._submit("SELL"))
        btn_row.addWidget(self.sell_btn)
        layout.addLayout(btn_row)

        # Risk preview
        self.risk_lbl = QLabel("")
        self.risk_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        self.risk_lbl.setWordWrap(True)
        layout.addWidget(self.risk_lbl)

    def _update_total(self) -> None:
        total = self.price_spin.value() * self.qty_spin.value()
        self.total_lbl.setText(f"{total:,.6f}")
        if self.stop_spin.value() > 0:
            risk = abs(self.price_spin.value() - self.stop_spin.value()) * self.qty_spin.value()
            reward = abs(self.tp_spin.value() - self.price_spin.value()) * self.qty_spin.value() if self.tp_spin.value() > 0 else 0
            rr = reward / risk if risk > 0 else 0
            self.risk_lbl.setText(f"Risk: ${risk:.4f} | Reward: ${reward:.4f} | R:R = {rr:.2f}:1")

    def _submit(self, side: str) -> None:
        order = {
            "symbol": self.sym_edit.text().upper().strip(),
            "side": side,
            "type": self.order_type.currentText(),
            "price": self.price_spin.value(),
            "quantity": self.qty_spin.value(),
            "stop_price": self.stop_spin.value(),
            "take_profit": self.tp_spin.value(),
        }
        self.order_submitted.emit(order)

    def set_price(self, price: float) -> None:
        self.price_spin.setValue(price)
        self._update_total()


class TradesTable(QTableWidget):
    """Shared base for trades/orders tables."""

    COLUMNS: list = []
    COLOUR_COL: int = -1   # Column index to colour-code

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(self.COLUMNS), parent)
        self.setHorizontalHeaderLabels(self.COLUMNS)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setDefaultSectionSize(22)
        self.setAlternatingRowColors(True)
        self.setStyleSheet(f"""
            QTableWidget {{ font-size:12px; }}
            QTableWidget::item:alternate {{ background:{BG4}; }}
        """)

    def _colour_item(self, text: str, colour: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setForeground(QBrush(QColor(colour)))
        return item

    def _side_colour(self, side: str) -> str:
        return GREEN if side.upper() == "BUY" else RED


class ActiveOrdersTable(TradesTable):
    COLUMNS = ["Symbol","Side","Type","Qty","Price","Filled","Status","Time","Actions"]
    cancel_requested = pyqtSignal(str, str)   # symbol, order_id

    def refresh_orders(self, orders: list[dict]) -> None:
        self.setRowCount(0)
        for o in orders:
            row = self.rowCount()
            self.insertRow(row)
            items = [
                (o.get("symbol",""), FG0),
                (o.get("side",""), self._side_colour(o.get("side",""))),
                (o.get("type",""), FG1),
                (f"{o.get('quantity',0):.6f}", FG0),
                (f"{o.get('price',0):,.4f}", FG0),
                (f"{o.get('filled_qty',0):.6f}", FG1),
                (o.get("status",""), ACCENT if o.get("status")=="FILLED" else YELLOW),
                (str(o.get("created_at",""))[:19], FG2),
            ]
            for col, (text, fg) in enumerate(items):
                self.setItem(row, col, self._colour_item(text, fg))
            # Cancel button
            cancel_btn = QPushButton("✕")
            cancel_btn.setFixedSize(24, 24)
            cancel_btn.setStyleSheet(f"color:{RED}; border:none; font-size:14px; background:transparent;")
            oid = str(o.get("id",""))
            sym = o.get("symbol","")
            cancel_btn.clicked.connect(lambda _, s=sym, o=oid: self.cancel_requested.emit(s, o))
            self.setCellWidget(row, 8, cancel_btn)


class TradeHistoryTable(TradesTable):
    COLUMNS = ["Date","Symbol","Side","Type","Qty","Avg Price","Fee","P&L","P&L %","Auto"]

    def refresh_trades(self, trades: list) -> None:
        self.setRowCount(0)
        for t in trades:
            row = self.rowCount()
            self.insertRow(row)
            pnl = float(getattr(t,"realized_pnl",0) or 0)
            pnl_colour = GREEN if pnl > 0 else RED if pnl < 0 else FG1
            pnl_pct = 0.0
            if getattr(t,"entry_price",None) and t.entry_price:
                try:
                    pnl_pct = float((float(t.avg_fill_price or t.price) - float(t.entry_price)) / float(t.entry_price) * 100)
                except Exception:
                    pass
            items = [
                (str(t.created_at)[:19], FG2),
                (t.symbol, FG0),
                (t.side, self._side_colour(t.side)),
                (t.order_type, FG1),
                (f"{float(t.quantity):.6f}", FG0),
                (f"{float(t.avg_fill_price or t.price):,.4f}", FG0),
                (f"{float(t.fee or 0):.6f}", FG2),
                (f"{pnl:+,.4f}", pnl_colour),
                (f"{pnl_pct:+.2f}%", pnl_colour),
                ("✓" if t.is_automated else "—", ACCENT if t.is_automated else FG2),
            ]
            for col, (text, fg) in enumerate(items):
                self.setItem(row, col, self._colour_item(text, fg))


class PortfolioTable(TradesTable):
    COLUMNS = ["Asset","Free","Locked","Total","USD Value","GBP Value","24h %"]

    def refresh_portfolio(self, assets: dict) -> None:
        self.setRowCount(0)
        for asset, data in assets.items():
            row = self.rowCount()
            self.insertRow(row)
            chg = data.get("change_24h", 0)
            chg_colour = GREEN if chg >= 0 else RED
            items = [
                (asset, ACCENT),
                (f"{data.get('free',0):.8f}", FG0),
                (f"{data.get('locked',0):.8f}", FG1),
                (f"{data.get('free',0)+data.get('locked',0):.8f}", FG0),
                (f"${data.get('usd_value',0):,.2f}", FG0),
                (f"£{data.get('gbp_value',0):,.2f}", FG0),
                (f"{chg:+.2f}%" if chg != 0 else "—", chg_colour),
            ]
            for col, (text, fg) in enumerate(items):
                self.setItem(row, col, self._colour_item(text, fg))


class TradingPanel(QWidget):
    """
    Complete trading interface panel:
    Left: Order entry + active orders
    Right: Trade history tabs (history / portfolio / P&L ledger)
    """

    order_submitted = pyqtSignal(dict)
    cancel_requested = pyqtSignal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(5000)

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: order entry + active orders ──────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)

        self.order_entry = OrderEntryPanel()
        self.order_entry.order_submitted.connect(self.order_submitted)
        ll.addWidget(self.order_entry)

        # Mode selector
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Engine Mode:"))
        self.mode_combo = QComboBox()
        for m in ["Manual","Auto","Hybrid","Paused"]:
            self.mode_combo.addItem(m)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch()
        ll.addLayout(mode_row)

        # Active orders
        active_grp = QGroupBox("Active Orders")
        agl = QVBoxLayout(active_grp)
        self.active_orders_tbl = ActiveOrdersTable()
        self.active_orders_tbl.cancel_requested.connect(self.cancel_requested)
        agl.addWidget(self.active_orders_tbl)
        ll.addWidget(active_grp, 1)

        splitter.addWidget(left)

        # ── Right: trade history tabs ───────────────────────────────────
        right = QTabWidget()

        self.history_tbl = TradeHistoryTable()
        right.addTab(self.history_tbl, "📜 Trade History")

        self.portfolio_tbl = PortfolioTable()
        right.addTab(self.portfolio_tbl, "💼 Portfolio")

        # P&L Ledger
        self.pnl_widget = self._build_pnl_widget()
        right.addTab(self.pnl_widget, "📊 P&L Ledger")

        splitter.addWidget(right)
        splitter.setSizes([380, 700])
        layout.addWidget(splitter)

    def _build_pnl_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        # Summary cards
        cards = QHBoxLayout()
        self.pnl_cards = {}
        for key, label, colour in [
            ("total_pnl","Total P&L",GREEN),
            ("today_pnl","Today P&L",ACCENT),
            ("win_rate","Win Rate",YELLOW),
            ("open_pos","Open Positions",FG0),
        ]:
            card = QGroupBox(label)
            cl = QVBoxLayout(card)
            lbl = QLabel("—")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"font-size:20px; font-weight:700; color:{colour};")
            cl.addWidget(lbl)
            self.pnl_cards[key] = lbl
            cards.addWidget(card)
        layout.addLayout(cards)

        # Daily P&L chart
        import pyqtgraph as pg
        from ui.styles import BG2, FG1
        pg.setConfigOption("background", BG2)
        pg.setConfigOption("foreground", FG1)
        self.pnl_plot = pg.PlotWidget(title="Daily P&L (USDT)")
        self.pnl_plot.showGrid(x=True, y=True, alpha=0.15)
        self.pnl_plot.setAxisItems({"bottom": pg.DateAxisItem()})
        layout.addWidget(self.pnl_plot, 1)

        return w

    def _refresh(self) -> None:
        try:
            from db.postgres import get_db
            from db.models import Trade, Portfolio
            with get_db() as db:
                trades = db.query(Trade).order_by(Trade.created_at.desc()).limit(100).all()
                self.history_tbl.refresh_trades(trades)
        except Exception:
            pass

    def update_portfolio(self, snapshot) -> None:
        assets = getattr(snapshot, "assets", {}) if not isinstance(snapshot, dict) else snapshot.get("assets", {})
        self.portfolio_tbl.refresh_portfolio(assets)

    def update_active_orders(self, orders: list) -> None:
        self.active_orders_tbl.refresh_orders(orders)

    def update_pnl(self, metrics: dict) -> None:
        pnl = metrics.get("pnl_today", 0)
        colour = GREEN if pnl >= 0 else RED
        self.pnl_cards["total_pnl"].setText(f"${pnl:+,.2f}")
        self.pnl_cards["total_pnl"].setStyleSheet(f"font-size:20px; font-weight:700; color:{colour};")
        self.pnl_cards["today_pnl"].setText(f"${pnl:+,.2f}")
        wins = metrics.get("wins_today",0)
        losses = metrics.get("losses_today",0)
        total = wins + losses
        wr = wins/total if total > 0 else 0
        self.pnl_cards["win_rate"].setText(f"{wr:.1%}")
        self.pnl_cards["open_pos"].setText(str(metrics.get("open_trades",0)))

    def set_current_price(self, price: float) -> None:
        self.order_entry.set_price(price)
