"""
Token & Contract Safety Widget  (Layer 8)
==========================================
UI panel for contract analysis, honeypot detection, liquidity lock,
wallet graph, and rug-pull scoring.

Shortcut: Shift+Alt+8 (Layer 8 – Safety)
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from ui.styles import DARK_BG, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, TEXT_MUTED
except Exception:
    DARK_BG = "#0A0A12"
    ACCENT_BLUE = "#00D4FF"
    ACCENT_GREEN = "#00FF88"
    ACCENT_RED = "#FF4444"
    TEXT_MUTED = "#8888AA"


class AnalysisWorker(QThread):
    """Background thread for token safety analysis."""
    result_ready = pyqtSignal(dict)

    def __init__(self, address: str, symbol: str, chain: str,
                 contract_analyzer=None, honeypot_detector=None,
                 liq_analyzer=None, wallet_analyzer=None, rugpull_scorer=None):
        super().__init__()
        self.address = address
        self.symbol = symbol
        self.chain = chain
        self._contract = contract_analyzer
        self._honeypot = honeypot_detector
        self._liq = liq_analyzer
        self._wallet = wallet_analyzer
        self._rugpull = rugpull_scorer

    def run(self):
        result = {}
        try:
            if self._contract:
                cr = self._contract.analyze(self.address, self.chain, self.symbol)
                result["contract"] = {
                    "risk_score": cr.risk_score,
                    "flags": cr.flags,
                    "has_mint": cr.has_mint,
                    "has_blacklist": cr.has_blacklist,
                    "buy_tax": cr.buy_tax_pct,
                    "sell_tax": cr.sell_tax_pct,
                    "verified": cr.verified_source,
                }
        except Exception as e:
            result["contract_error"] = str(e)

        try:
            if self._honeypot:
                hp = self._honeypot.check(self.address, self.chain, self.symbol)
                result["honeypot"] = {
                    "is_honeypot": hp.is_honeypot,
                    "can_sell": hp.can_sell,
                    "sell_tax": hp.sell_tax_pct,
                    "buy_tax": hp.buy_tax_pct,
                }
        except Exception as e:
            result["honeypot_error"] = str(e)

        try:
            if self._rugpull:
                rp = self._rugpull.score(self.address, None, None, self.symbol, self.chain)
                result["rugpull"] = {
                    "probability": rp.probability,
                    "risk_level": rp.risk_level,
                    "red_flags": rp.red_flags,
                    "green_flags": rp.green_flags,
                    "recommendation": rp.recommendation,
                }
        except Exception as e:
            result["rugpull_error"] = str(e)

        self.result_ready.emit(result)


class SafetyWidget(QWidget):
    """
    Token & Contract Safety analysis panel.

    Features:
    - Manual token address input for on-demand analysis
    - Live feed of new token launches and their scores
    - Contract flag breakdown
    - Rug-pull probability with component scores
    - Honeypot detection result

    Keyboard shortcut: Shift+Alt+7 (Layer 7)
    """

    def __init__(self, contract_analyzer=None, honeypot_detector=None,
                 liq_analyzer=None, wallet_analyzer=None, rugpull_scorer=None,
                 launch_signal_engine=None, parent=None):
        super().__init__(parent)
        self._contract = contract_analyzer
        self._honeypot = honeypot_detector
        self._liq = liq_analyzer
        self._wallet = wallet_analyzer
        self._rugpull = rugpull_scorer
        self._launch = launch_signal_engine
        self._worker: Optional[AnalysisWorker] = None
        self._setup_ui()
        self._setup_timer()
        self._setup_shortcut()

    def _setup_shortcut(self):
        sc = QShortcut(QKeySequence("Shift+Alt+7"), self)
        sc.activated.connect(self.show)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("Token & Contract Safety  ·  Layer 8")
        title.setStyleSheet(f"color:{ACCENT_BLUE}; font-size:16px; font-weight:bold;")
        hdr.addWidget(title)
        root.addLayout(hdr)

        # Input row
        input_row = QHBoxLayout()
        self._addr_input = QLineEdit()
        self._addr_input.setPlaceholderText("Token contract address (0x...)")
        self._addr_input.setStyleSheet(
            "background:#1A1A2E; color:#E0E0FF; border:1px solid #3A3A5A; "
            "border-radius:4px; padding:6px; font-family:monospace;"
        )
        input_row.addWidget(self._addr_input)

        self._sym_input = QLineEdit()
        self._sym_input.setPlaceholderText("Symbol")
        self._sym_input.setMaximumWidth(100)
        self._sym_input.setStyleSheet(self._addr_input.styleSheet())
        input_row.addWidget(self._sym_input)

        self._analyze_btn = QPushButton("Analyze")
        self._analyze_btn.setFixedWidth(90)
        self._analyze_btn.setStyleSheet(
            f"background:{ACCENT_BLUE}; color:#000; font-weight:bold; "
            f"border-radius:4px; padding:6px;"
        )
        self._analyze_btn.clicked.connect(self._run_analysis)
        input_row.addWidget(self._analyze_btn)
        root.addLayout(input_row)

        # Tabs: Analysis | Launch Feed
        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabBar::tab {{ color:{TEXT_MUTED}; background:#1A1A2E; padding:6px 14px; }}"
            f"QTabBar::tab:selected {{ color:{ACCENT_BLUE}; border-bottom:2px solid {ACCENT_BLUE}; }}"
        )

        # ── Analysis tab ─────────────────────────────────────────────────────
        analysis_tab = QWidget()
        atab_lay = QVBoxLayout(analysis_tab)

        self._analyzing_lbl = QLabel("Enter a contract address above and click Analyze.")
        self._analyzing_lbl.setStyleSheet(f"color:{TEXT_MUTED}; padding:20px;")
        self._analyzing_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        atab_lay.addWidget(self._analyzing_lbl)

        # Result panel
        self._result_frame = QFrame()
        self._result_frame.setVisible(False)
        self._result_frame.setStyleSheet("background:#12121E; border-radius:8px; border:1px solid #2A2A4A;")
        result_lay = QVBoxLayout(self._result_frame)

        # Rug-pull bar
        rp_row = QHBoxLayout()
        rp_row.addWidget(QLabel("Rug-Pull Probability:"))
        self._rp_bar = QProgressBar()
        self._rp_bar.setRange(0, 100)
        self._rp_bar.setTextVisible(True)
        self._rp_bar.setFixedHeight(20)
        rp_row.addWidget(self._rp_bar)
        self._rp_level = QLabel("—")
        self._rp_level.setFixedWidth(80)
        rp_row.addWidget(self._rp_level)
        result_lay.addLayout(rp_row)

        # Status indicators
        indicators = QHBoxLayout()
        self._hp_lbl = self._indicator("Honeypot", "—", TEXT_MUTED)
        self._verified_lbl = self._indicator("Verified", "—", TEXT_MUTED)
        self._mint_lbl = self._indicator("Mint Auth", "—", TEXT_MUTED)
        self._blacklist_lbl = self._indicator("Blacklist", "—", TEXT_MUTED)
        for lbl in (self._hp_lbl, self._verified_lbl, self._mint_lbl, self._blacklist_lbl):
            indicators.addWidget(lbl)
        indicators.addStretch()
        result_lay.addLayout(indicators)

        # Taxes
        tax_row = QHBoxLayout()
        self._buy_tax_lbl = QLabel("Buy Tax: —")
        self._buy_tax_lbl.setStyleSheet(f"color:{TEXT_MUTED};")
        self._sell_tax_lbl = QLabel("Sell Tax: —")
        self._sell_tax_lbl.setStyleSheet(f"color:{TEXT_MUTED};")
        tax_row.addWidget(self._buy_tax_lbl)
        tax_row.addWidget(self._sell_tax_lbl)
        tax_row.addStretch()
        result_lay.addLayout(tax_row)

        # Red flags
        self._flags_lbl = QLabel("Flags: —")
        self._flags_lbl.setWordWrap(True)
        self._flags_lbl.setStyleSheet(f"color:{ACCENT_RED}; font-size:11px;")
        result_lay.addWidget(self._flags_lbl)

        # Recommendation
        self._rec_lbl = QLabel("Recommendation: —")
        self._rec_lbl.setStyleSheet("font-size:14px; font-weight:bold; padding:6px;")
        result_lay.addWidget(self._rec_lbl)

        atab_lay.addWidget(self._result_frame)
        atab_lay.addStretch()
        tabs.addTab(analysis_tab, "Contract Analysis")

        # ── Launch Feed tab ───────────────────────────────────────────────────
        feed_tab = QWidget()
        feed_lay = QVBoxLayout(feed_tab)
        self._launch_table = QTableWidget(0, 6)
        self._launch_table.setHorizontalHeaderLabels(
            ["Symbol", "Signal", "Rug Risk", "Honeypot", "Liq Locked", "Rec"]
        )
        self._launch_table.horizontalHeader().setStretchLastSection(True)
        self._launch_table.setStyleSheet(self._table_style())
        feed_lay.addWidget(self._launch_table)
        tabs.addTab(feed_tab, "Token Launch Feed")

        root.addWidget(tabs, stretch=1)

    def _indicator(self, label: str, value: str, color: str) -> QLabel:
        lbl = QLabel(f"{label}: {value}")
        lbl.setStyleSheet(
            f"color:{color}; background:#1A1A2E; border-radius:4px; "
            f"padding:4px 8px; font-size:11px;"
        )
        return lbl

    def _setup_timer(self):
        self._timer = QTimer()
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._refresh_feed)
        self._timer.start()

    def _run_analysis(self):
        addr = self._addr_input.text().strip()
        if not addr:
            return
        sym = self._sym_input.text().strip() or "TOKEN"
        self._analyzing_lbl.setText(f"Analyzing {sym} ({addr[:10]}...)  Please wait…")
        self._analyzing_lbl.setVisible(True)
        self._result_frame.setVisible(False)
        self._analyze_btn.setEnabled(False)

        self._worker = AnalysisWorker(
            addr, sym, "eth",
            self._contract, self._honeypot, self._liq, self._wallet, self._rugpull
        )
        self._worker.result_ready.connect(self._show_result)
        self._worker.start()

    def _show_result(self, result: dict):
        self._analyze_btn.setEnabled(True)
        self._analyzing_lbl.setVisible(False)
        self._result_frame.setVisible(True)

        # Rug-pull
        rp = result.get("rugpull", {})
        prob = rp.get("probability", 0.5)
        level = rp.get("risk_level", "unknown")
        self._rp_bar.setValue(int(prob * 100))
        color = ACCENT_GREEN if prob < 0.3 else ("#FFA500" if prob < 0.55 else ACCENT_RED)
        self._rp_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background:{color}; }} "
            f"QProgressBar {{ color:#FFF; border-radius:3px; }}"
        )
        self._rp_level.setText(level.upper())
        self._rp_level.setStyleSheet(f"color:{color}; font-weight:bold;")

        # Honeypot
        hp = result.get("honeypot", {})
        is_hp = hp.get("is_honeypot", False)
        self._update_indicator(self._hp_lbl, "Honeypot",
                               "YES" if is_hp else "NO",
                               ACCENT_RED if is_hp else ACCENT_GREEN)

        # Contract
        cr = result.get("contract", {})
        verified = cr.get("verified", False)
        self._update_indicator(self._verified_lbl, "Verified",
                               "YES" if verified else "NO",
                               ACCENT_GREEN if verified else "#FFA500")

        has_mint = cr.get("has_mint", False)
        self._update_indicator(self._mint_lbl, "Mint Auth",
                               "YES" if has_mint else "NO",
                               ACCENT_RED if has_mint else ACCENT_GREEN)

        has_bl = cr.get("has_blacklist", False)
        self._update_indicator(self._blacklist_lbl, "Blacklist",
                               "YES" if has_bl else "NO",
                               ACCENT_RED if has_bl else ACCENT_GREEN)

        buy_tax = cr.get("buy_tax", hp.get("buy_tax", 0))
        sell_tax = cr.get("sell_tax", hp.get("sell_tax", 0))
        self._buy_tax_lbl.setText(f"Buy Tax: {buy_tax:.1f}%")
        self._sell_tax_lbl.setText(f"Sell Tax: {sell_tax:.1f}%")

        red_flags = rp.get("red_flags", cr.get("flags", []))
        self._flags_lbl.setText("Flags: " + (", ".join(red_flags) or "None"))

        rec = rp.get("recommendation", "—")
        rec_color = {
            "proceed_with_caution": "#FFA500",
            "reduce_position_size": "#FFA500",
            "avoid": ACCENT_RED,
            "do_not_trade": ACCENT_RED,
        }.get(rec, ACCENT_GREEN)
        self._rec_lbl.setText(f"Recommendation: {rec.replace('_', ' ').upper()}")
        self._rec_lbl.setStyleSheet(f"color:{rec_color}; font-size:14px; font-weight:bold; padding:6px;")

    def _update_indicator(self, lbl: QLabel, label: str, value: str, color: str):
        lbl.setText(f"{label}: {value}")
        lbl.setStyleSheet(
            f"color:{color}; background:#1A1A2E; border-radius:4px; "
            f"padding:4px 8px; font-size:11px;"
        )

    def _refresh_feed(self):
        if not self._launch:
            return
        signals = self._launch.get_recent_signals(50)
        self._launch_table.setRowCount(len(signals))
        for row, sig in enumerate(reversed(signals)):
            color = ACCENT_GREEN if sig.is_tradeable else (
                "#FFA500" if sig.rugpull_probability < 0.5 else ACCENT_RED
            )
            self._launch_table.setItem(row, 0, QTableWidgetItem(sig.symbol))
            str_item = QTableWidgetItem(f"{sig.signal_strength:.2f}")
            str_item.setForeground(QColor(color))
            self._launch_table.setItem(row, 1, str_item)
            rp_item = QTableWidgetItem(f"{sig.rugpull_probability:.0%}")
            rp_item.setForeground(
                QColor(ACCENT_GREEN if sig.rugpull_probability < 0.3
                       else ACCENT_RED)
            )
            self._launch_table.setItem(row, 2, rp_item)
            hp_item = QTableWidgetItem("YES" if sig.honeypot else "NO")
            hp_item.setForeground(
                QColor(ACCENT_RED if sig.honeypot else ACCENT_GREEN)
            )
            self._launch_table.setItem(row, 3, hp_item)
            self._launch_table.setItem(row, 4, QTableWidgetItem(
                f"{sig.liquidity_locked_pct:.0f}%"
            ))
            dir_item = QTableWidgetItem(sig.direction.upper())
            dir_item.setForeground(
                QColor(ACCENT_GREEN if sig.direction == "long" else ACCENT_RED)
            )
            self._launch_table.setItem(row, 5, dir_item)

    def _table_style(self) -> str:
        return (
            "QTableWidget { background:#0A0A12; color:#C0C0E0; "
            "gridline-color:#2A2A4A; border:none; font-size:11px; }"
            "QHeaderView::section { background:#16162A; color:#8888AA; border:none; padding:4px; }"
        )
