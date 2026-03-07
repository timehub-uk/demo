"""
MetaMask Wallet Widget — Configure and manage on-chain asset transfers.

Provides a settings panel and transfer management interface for the
optional MetaMask wallet integration.

Features:
  - Configure MetaMask wallet address
  - Select network (Ethereum / BSC / Polygon / Arbitrum)
  - Enable/disable auto-sweep of profits
  - Set auto-sweep threshold (USDT)
  - Approve or cancel pending transfer requests
  - View transfer history
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QLineEdit, QComboBox, QCheckBox, QDoubleSpinBox, QFrame, QGroupBox,
    QMessageBox,
)
from loguru import logger

from ui.styles import (
    ACCENT, BG1, BG2, BG3, BG4, BORDER, BORDER2,
    FG0, FG1, FG2, GREEN, RED, YELLOW,
)

try:
    from core.metamask_wallet import MetaMaskWallet, TransferRequest
except Exception:
    MetaMaskWallet  = None   # type: ignore[assignment, misc]
    TransferRequest = None   # type: ignore[assignment, misc]

_STATUS_COLORS = {
    "PENDING":   "#FFD700",
    "APPROVED":  "#00BFFF",
    "SENT":      "#00CC66",
    "CONFIRMED": "#00FF99",
    "FAILED":    "#FF4040",
}

_COLS = ["ID", "Asset", "Amount", "Address", "Network", "Status", "Time", "Notes"]


class MetaMaskWidget(QWidget):
    """
    MetaMask wallet configuration and transfer management panel.
    """

    transfer_requested = pyqtSignal(str)   # emitted with transfer_id when user requests

    def __init__(
        self,
        metamask_wallet: Optional[MetaMaskWallet] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._wallet = metamask_wallet
        self._transfers: list[TransferRequest] = []

        self._build_ui()
        self._connect_wallet()

        self._timer = QTimer(self)
        self._timer.setInterval(15_000)
        self._timer.timeout.connect(self._refresh_table)
        self._timer.start()

    # ── UI construction ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────────
        title = QLabel("MetaMask Wallet Integration")
        title.setStyleSheet(f"color:{FG0}; font-size:14px; font-weight:bold;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Automatically or manually transfer profits to your MetaMask wallet. "
            "Only withdrawals to whitelisted Binance addresses are supported."
        )
        subtitle.setStyleSheet(f"color:{FG2}; font-size:11px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # ── Configuration group ───────────────────────────────────────────────
        config_grp = QGroupBox("Wallet Configuration")
        config_grp.setStyleSheet(
            f"QGroupBox {{ color:{FG1}; border:1px solid {BORDER}; border-radius:6px; "
            f"margin-top:8px; padding:8px; }}"
            f"QGroupBox::title {{ subcontrol-origin:margin; padding:0 4px; }}"
        )
        config_layout = QVBoxLayout(config_grp)
        config_layout.setSpacing(8)

        # Address row
        addr_row = QHBoxLayout()
        addr_lbl = QLabel("MetaMask Address:")
        addr_lbl.setStyleSheet(f"color:{FG1}; font-size:12px; min-width:140px;")
        addr_row.addWidget(addr_lbl)
        self._addr_input = QLineEdit()
        self._addr_input.setPlaceholderText("0x…  (EVM wallet address)")
        self._addr_input.setStyleSheet(
            f"QLineEdit {{ background:{BG3}; color:{FG0}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:4px 8px; font-family:monospace; }}"
        )
        addr_row.addWidget(self._addr_input)
        config_layout.addLayout(addr_row)

        # Network row
        net_row = QHBoxLayout()
        net_lbl = QLabel("Network:")
        net_lbl.setStyleSheet(f"color:{FG1}; font-size:12px; min-width:140px;")
        net_row.addWidget(net_lbl)
        self._net_combo = QComboBox()
        self._net_combo.addItems(["bsc", "ethereum", "polygon", "arbitrum", "optimism"])
        self._net_combo.setFixedWidth(140)
        self._net_combo.setStyleSheet(
            f"QComboBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 8px; }}"
        )
        net_row.addWidget(self._net_combo)
        net_note = QLabel("(BSC recommended — lowest fees)")
        net_note.setStyleSheet(f"color:{FG2}; font-size:10px;")
        net_row.addWidget(net_note)
        net_row.addStretch()
        config_layout.addLayout(net_row)

        # Auto-transfer row
        auto_row = QHBoxLayout()
        self._auto_chk = QCheckBox("Auto-sweep profits to MetaMask")
        self._auto_chk.setStyleSheet(f"color:{FG1}; font-size:12px;")
        auto_row.addWidget(self._auto_chk)
        auto_row.addSpacing(16)
        thresh_lbl = QLabel("Threshold (USDT):")
        thresh_lbl.setStyleSheet(f"color:{FG1}; font-size:12px;")
        auto_row.addWidget(thresh_lbl)
        self._thresh_spin = QDoubleSpinBox()
        self._thresh_spin.setRange(20.0, 100_000.0)
        self._thresh_spin.setValue(100.0)
        self._thresh_spin.setSingleStep(10.0)
        self._thresh_spin.setDecimals(2)
        self._thresh_spin.setFixedWidth(100)
        self._thresh_spin.setStyleSheet(
            f"QDoubleSpinBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 6px; }}"
        )
        auto_row.addWidget(self._thresh_spin)
        auto_row.addStretch()
        config_layout.addLayout(auto_row)

        # Buttons
        btn_row = QHBoxLayout()
        self._enable_btn = QPushButton("Enable Wallet")
        self._enable_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{GREEN}; border:1px solid {GREEN}; "
            f"border-radius:4px; padding:5px 16px; }}"
            f"QPushButton:hover {{ background:{GREEN}; color:#000; }}"
        )
        self._enable_btn.clicked.connect(self._on_enable)
        btn_row.addWidget(self._enable_btn)

        self._disable_btn = QPushButton("Disable")
        self._disable_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{RED}; border:1px solid {RED}; "
            f"border-radius:4px; padding:5px 16px; }}"
            f"QPushButton:hover {{ background:{RED}; color:#fff; }}"
        )
        self._disable_btn.clicked.connect(self._on_disable)
        btn_row.addWidget(self._disable_btn)

        btn_row.addSpacing(16)

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(f"color:{RED}; font-size:16px;")
        btn_row.addWidget(self._status_dot)
        self._status_lbl = QLabel("Disabled")
        self._status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        btn_row.addWidget(self._status_lbl)
        btn_row.addStretch()
        config_layout.addLayout(btn_row)

        layout.addWidget(config_grp)

        # ── Manual transfer group ─────────────────────────────────────────────
        xfer_grp = QGroupBox("Manual Transfer")
        xfer_grp.setStyleSheet(
            f"QGroupBox {{ color:{FG1}; border:1px solid {BORDER}; border-radius:6px; "
            f"margin-top:8px; padding:8px; }}"
            f"QGroupBox::title {{ subcontrol-origin:margin; padding:0 4px; }}"
        )
        xfer_layout = QHBoxLayout(xfer_grp)
        xfer_layout.setSpacing(8)

        asset_lbl = QLabel("Asset:")
        asset_lbl.setStyleSheet(f"color:{FG1}; font-size:12px;")
        xfer_layout.addWidget(asset_lbl)
        self._asset_combo = QComboBox()
        self._asset_combo.addItems(["USDT", "BNB", "ETH", "BTC", "BUSD"])
        self._asset_combo.setFixedWidth(80)
        self._asset_combo.setStyleSheet(
            f"QComboBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 6px; }}"
        )
        xfer_layout.addWidget(self._asset_combo)

        amount_lbl = QLabel("Amount:")
        amount_lbl.setStyleSheet(f"color:{FG1}; font-size:12px;")
        xfer_layout.addWidget(amount_lbl)
        self._amount_spin = QDoubleSpinBox()
        self._amount_spin.setRange(20.0, 1_000_000.0)
        self._amount_spin.setValue(50.0)
        self._amount_spin.setDecimals(6)
        self._amount_spin.setFixedWidth(120)
        self._amount_spin.setStyleSheet(
            f"QDoubleSpinBox {{ background:{BG3}; color:{FG1}; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:2px 6px; }}"
        )
        xfer_layout.addWidget(self._amount_spin)

        send_btn = QPushButton("Request Transfer →")
        send_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{ACCENT}; border:1px solid {ACCENT}; "
            f"border-radius:4px; padding:5px 16px; }}"
            f"QPushButton:hover {{ background:{ACCENT}; color:#000; }}"
        )
        send_btn.clicked.connect(self._on_request_transfer)
        xfer_layout.addWidget(send_btn)
        xfer_layout.addStretch()
        layout.addWidget(xfer_grp)

        # ── Transfer history table ────────────────────────────────────────────
        hist_lbl = QLabel("Transfer History")
        hist_lbl.setStyleSheet(f"color:{FG1}; font-size:12px; font-weight:bold;")
        layout.addWidget(hist_lbl)

        # Approve / cancel buttons
        action_row = QHBoxLayout()
        self._approve_btn = QPushButton("✅ Approve Selected")
        self._approve_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{GREEN}; border:1px solid {GREEN}; "
            f"border-radius:4px; padding:4px 12px; }}"
            f"QPushButton:hover {{ background:{GREEN}; color:#000; }}"
        )
        self._approve_btn.clicked.connect(self._on_approve)
        action_row.addWidget(self._approve_btn)

        self._cancel_btn = QPushButton("❌ Cancel Selected")
        self._cancel_btn.setStyleSheet(
            f"QPushButton {{ background:{BG3}; color:{RED}; border:1px solid {RED}; "
            f"border-radius:4px; padding:4px 12px; }}"
            f"QPushButton:hover {{ background:{RED}; color:#fff; }}"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        action_row.addWidget(self._cancel_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(True)
        self._table.setSortingEnabled(False)

        self._table.setStyleSheet(f"""
            QTableWidget {{
                background:{BG1}; color:{FG0};
                gridline-color:{BORDER}; border:1px solid {BORDER2};
                border-radius:6px; font-size:12px;
            }}
            QHeaderView::section {{
                background:{BG3}; color:{FG1};
                border:none; border-bottom:1px solid {BORDER2};
                padding:5px 8px; font-size:12px; font-weight:bold;
            }}
            QTableWidget::item {{ padding:4px 6px; }}
            QTableWidget::item:selected {{ background:{BG4}; color:{FG0}; }}
        """)
        layout.addWidget(self._table)

    # ── Wallet wiring ───────────────────────────────────────────────────────────

    def _connect_wallet(self) -> None:
        if not self._wallet:
            return
        try:
            self._wallet.on_transfer(self._on_transfer_update)
            # Populate fields from existing wallet state
            status = self._wallet.get_status()
            self._addr_input.setText(status.get("address", ""))
            net = status.get("network", "bsc")
            idx = self._net_combo.findText(net)
            if idx >= 0:
                self._net_combo.setCurrentIndex(idx)
            self._auto_chk.setChecked(status.get("auto_transfer", False))
            self._thresh_spin.setValue(status.get("threshold_usdt", 100.0))
            self._update_status_indicator(status.get("enabled", False))
        except Exception as exc:
            logger.warning(f"MetaMaskWidget: could not connect wallet: {exc!r}")

    def _on_transfer_update(self, req: TransferRequest) -> None:
        """Called from background thread — update table in Qt thread."""
        # Update local list
        found = False
        for i, t in enumerate(self._transfers):
            if t.id == req.id:
                self._transfers[i] = req
                found = True
                break
        if not found:
            self._transfers.insert(0, req)
        QTimer.singleShot(0, self._refresh_table)

    def _update_status_indicator(self, enabled: bool) -> None:
        if enabled:
            self._status_dot.setStyleSheet(f"color:{GREEN}; font-size:16px;")
            self._status_lbl.setText("Enabled")
        else:
            self._status_dot.setStyleSheet(f"color:{RED}; font-size:16px;")
            self._status_lbl.setText("Disabled")

    # ── Table refresh ───────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        if not self._transfers and self._wallet:
            try:
                self._transfers = self._wallet.get_transfers()
            except Exception:
                pass

        transfers = self._transfers
        self._table.setRowCount(len(transfers))

        for row_idx, t in enumerate(transfers):
            status_color = _STATUS_COLORS.get(t.status, FG2)
            bg = QColor(BG2)

            def _item(text: str, fg=None) -> QTableWidgetItem:
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                it.setBackground(bg)
                it.setForeground(QColor(fg or FG0))
                return it

            self._table.setItem(row_idx, 0, _item(t.id, FG2))
            self._table.setItem(row_idx, 1, _item(t.asset))
            self._table.setItem(row_idx, 2, _item(f"{t.amount:.6f}"))
            self._table.setItem(row_idx, 3, _item(f"{t.to_address[:8]}…{t.to_address[-4:]}", FG2))
            self._table.setItem(row_idx, 4, _item(t.network))
            status_item = _item(t.status, status_color)
            self._table.setItem(row_idx, 5, status_item)
            self._table.setItem(row_idx, 6, _item(t.requested_at[:19], FG2))
            note = t.error if t.error else t.note
            self._table.setItem(row_idx, 7, _item(note, FG2))
            self._table.setRowHeight(row_idx, 34)

    # ── Interactions ────────────────────────────────────────────────────────────

    def _on_enable(self) -> None:
        if not self._wallet:
            QMessageBox.warning(self, "Not Available",
                                "MetaMask wallet module not loaded.")
            return
        addr = self._addr_input.text().strip()
        if not addr:
            QMessageBox.warning(self, "Address Required",
                                "Please enter your MetaMask wallet address.")
            return
        try:
            self._wallet.address        = addr
            self._wallet._network       = self._net_combo.currentText()
            self._wallet.auto_transfer  = self._auto_chk.isChecked()
            self._wallet._threshold     = self._thresh_spin.value()
            self._wallet.enable()
            self._update_status_indicator(True)
        except Exception as exc:
            QMessageBox.critical(self, "Enable Failed", str(exc))

    def _on_disable(self) -> None:
        if self._wallet:
            self._wallet.disable()
        self._update_status_indicator(False)

    def _on_request_transfer(self) -> None:
        if not self._wallet:
            QMessageBox.warning(self, "Not Available",
                                "MetaMask wallet module not loaded.")
            return
        if not self._wallet.enabled:
            QMessageBox.warning(self, "Wallet Disabled",
                                "Enable the wallet first before requesting a transfer.")
            return
        asset  = self._asset_combo.currentText()
        amount = self._amount_spin.value()
        req = self._wallet.request_transfer(asset, amount, auto_approved=False)
        if req:
            # Show confirmation dialog
            msg = QMessageBox.question(
                self, "Confirm Transfer",
                f"Transfer {amount:.6f} {asset} to:\n{self._wallet.address}\n\n"
                f"Network: {self._wallet.network}\n\n"
                f"Do you want to approve this transfer?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if msg == QMessageBox.StandardButton.Yes:
                self._wallet.approve_transfer(req.id)

    def _on_approve(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._transfers):
            return
        req = self._transfers[row]
        if req.status != "PENDING":
            QMessageBox.information(self, "Not Pending",
                                    f"Transfer {req.id} is already {req.status}.")
            return
        if self._wallet:
            self._wallet.approve_transfer(req.id)

    def _on_cancel(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._transfers):
            return
        req = self._transfers[row]
        if self._wallet:
            self._wallet.cancel_transfer(req.id)
