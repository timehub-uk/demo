"""
Help Widget – Keyboard shortcuts, documentation, and about panel.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QTextBrowser, QGroupBox, QScrollArea,
)
from PyQt6.QtGui import QBrush, QColor

from ui.styles import (
    ACCENT, ACCENT2, GREEN, YELLOW, BG0, BG2, BG3, BG4,
    BORDER, BORDER2, FG0, FG1, FG2,
)
from ui.icons import svg_icon

# ── Keyboard shortcuts data ───────────────────────────────────────────────────

SHORTCUTS = [
    # (Category, Key, Description)
    ("Navigation",  "Ctrl+1",       "Go to Trading panel"),
    ("Navigation",  "Ctrl+2",       "Go to AutoTrader panel"),
    ("Navigation",  "Ctrl+3",       "Go to ML Training panel"),
    ("Navigation",  "Ctrl+4",       "Go to Risk Dashboard"),
    ("Navigation",  "Ctrl+5",       "Go to Connections panel"),
    ("Navigation",  "Ctrl+6",       "Go to Settings"),
    ("Navigation",  "Ctrl+7",       "Go to Help"),
    ("Navigation",  "Ctrl+L",       "Toggle Intel Log dock"),
    ("Navigation",  "Ctrl+B",       "Toggle Order Book dock"),
    ("Trading",     "Ctrl+Shift+B", "Market BUY current symbol"),
    ("Trading",     "Ctrl+Shift+S", "Market SELL current symbol"),
    ("Trading",     "Ctrl+Shift+X", "Cancel ALL open orders"),
    ("Trading",     "Ctrl+Shift+E", "Manual Exit (AutoTrader)"),
    ("Trading",     "Ctrl+Shift+A", "Take Aim (confirm trade)"),
    ("Trading",     "Ctrl+Shift+N", "Scan market now"),
    ("ML",          "Ctrl+T",       "Start ML training session"),
    ("ML",          "Ctrl+Shift+T", "Stop ML training"),
    ("ML",          "Ctrl+R",       "Reload ML model"),
    ("ML",          "Ctrl+I",       "Run data integrity check"),
    ("Charts",      "Ctrl++",       "Add chart tab"),
    ("Charts",      "Ctrl+W",       "Close current chart tab"),
    ("Charts",      "Ctrl+Tab",     "Next chart tab"),
    ("System",      "Ctrl+,",       "Open Settings"),
    ("System",      "Ctrl+Q",       "Quit application"),
    ("System",      "F11",          "Toggle fullscreen"),
    ("System",      "Ctrl+Shift+C", "Check all connections"),
]

# ── FAQ / documentation ───────────────────────────────────────────────────────

DOCS_HTML = """
<style>
  body  {{ font-family: 'JetBrains Mono', monospace; font-size: 12px;
          background: {bg2}; color: {fg0}; padding: 16px; }}
  h2    {{ color: {accent}; font-size: 14px; letter-spacing: 2px;
          border-bottom: 1px solid {border}; padding-bottom: 6px; }}
  h3    {{ color: {fg1}; font-size: 12px; margin-top: 16px; }}
  code  {{ background: {bg4}; color: {accent2}; padding: 2px 6px;
          border-radius: 3px; font-size: 11px; }}
  p, li {{ color: {fg0}; line-height: 1.6; }}
  .warn {{ color: {yellow}; }}
  .ok   {{ color: {green}; }}
</style>

<h2>GETTING STARTED</h2>

<h3>1. Configure API Keys</h3>
<p>Open <code>Settings → System</code> and enter your Binance API Key and Secret.
Enable <b>Testnet</b> while testing — this uses paper balances only.</p>

<h3>2. Start the Trading Engine</h3>
<p>From the <code>Trading</code> menu, select a mode:
<ul>
  <li><b>Manual</b> – You place every order manually</li>
  <li><b>Auto</b> – ML signals trigger orders automatically</li>
  <li><b>Hybrid</b> – ML recommends, you confirm</li>
  <li><b>Paper</b> – Simulated execution, real prices</li>
</ul>

<h3>3. AutoTrader</h3>
<p>The AutoTrader scans all pairs (USDT, BTC, ETH, BNB, SOL) every 5 minutes
using the full ML stack (LSTM + Transformer ensemble, MTF confluence, signal council,
regime detector). In <code>SEMI_AUTO</code> mode, press <b>🎯 Take Aim</b> to approve
the recommended trade. In <code>FULL_AUTO</code> mode, trades fire when confidence ≥ threshold.</p>
<p class="warn">⚠ Minimum trade size: £12.00 GBP (≈ 15.24 USDT). Orders below this floor are rejected.</p>

<h3>4. ML Training</h3>
<p>Go to <code>ML → ML Training</code>. First run will take ~48h.
Models are retrained automatically every 24h when new data is available.</p>

<h2>ML INTELLIGENCE STACK</h2>

<h3>Core ML Models</h3>
<ul>
  <li><code>LSTM Predictor</code> – Per-bar sequence model (30-bar lookback)</li>
  <li><code>Transformer</code> – Attention-based long-range pattern detection</li>
  <li><code>Ensemble Aggregator</code> – Weighted vote with regime multipliers</li>
  <li><code>MTF Confluence Filter</code> – 1h/4h/1d timeframe agreement</li>
  <li><code>Signal Council</code> – Multi-model deliberation with veto power</li>
  <li><code>Regime Detector</code> – Bull/Bear/Ranging/Volatile classification</li>
  <li><code>Dynamic Risk Manager</code> – Kelly-based sizing + circuit breaker</li>
</ul>

<h3>Pair Discovery &amp; Scanning (AutoTrader → Pairs tab)</h3>
<ul>
  <li><code>Pair Scanner</code> – Scans 1000+ pairs across USDT/BTC/ETH/BNB/SOL quotes every 15 min.
      Ranks by volume, activity, momentum → HIGH / MEDIUM / LOW priority.</li>
  <li><code>Multi-TF Trend Scanner</code> – Classifies every pair as UP / SIDEWAYS / DOWN
      across 7 timeframes: 15m, 30m, 1h, 12h, 24h, 7d, 30d.</li>
  <li><code>Pair ML Analyzer</code> – Cross-references all 6 ML tools per pair every 5 min
      to compute a <b>Tradability Score</b> (0–1).</li>
</ul>

<h3>Advanced Detection (AutoTrader tabs)</h3>
<ul>
  <li><code>Accumulation Detector</code> (🕵 Accumulation tab) – Finds stealth accumulation:
      tight price band + rising volume + taker-buy dominance over days/weeks.
      Labels: NONE / WATCH / ALERT / STRONG. Scans LOW+MEDIUM pairs every 30 min.</li>
  <li><code>Liquidity Depth Analyzer</code> (💧 Liquidity tab) – Grades order-book depth:
      DEEP / ADEQUATE / THIN / ILLIQUID. Estimates slippage for £12 minimum trade size.
      Scans HIGH+MEDIUM pairs every 10 min.</li>
  <li><code>Volume Breakout Detector</code> (💥 Breakouts tab) – Detects 4-stage patterns:
      <b>Stage 1 LAUNCH</b> → <b>Stage 2 PUMP</b> → <b>Stage 3 CONSOLIDATION</b>
      → <b>Stage 4 BREAKOUT</b>. Uses 15m klines. Scans every 15 min.</li>
</ul>

<h3>Arbitrage (AutoTrader → Arbitrage tab)</h3>
<p>Statistical arbitrage across correlated USDT pairs. Pair cooldown: 5 min after close.
Minimum profit threshold: <b>£12 GBP</b>. Rate-limited to respect Binance API limits.</p>

<h2>DATA FLOW</h2>
<p><code>Pair Scanner</code> → <code>Trend / Accum / Liquidity / Breakout detectors</code>
→ <code>Pair ML Analyzer</code> (tradability score) → <code>AutoTrader</code>
→ <code>TradingEngine</code> → <code>Binance REST</code></p>

<h2>METAMASK WALLET (Settings → MetaMask)</h2>
<p>Optional profit-sweeping to a MetaMask wallet:</p>
<ul>
  <li>Enter your MetaMask <b>0x…</b> EVM address</li>
  <li>Select network: BSC (lowest fees), Ethereum, Polygon, Arbitrum</li>
  <li>Enable <b>Auto-sweep</b> to automatically transfer profits when they exceed your threshold</li>
  <li>Or request <b>Manual Transfers</b> which you approve in the transfers table</li>
  <li>Binance must have the address whitelisted for withdrawals</li>
</ul>
<p class="warn">⚠ Never share your private key. Auto-sweep uses Binance Withdrawal API only — no private key required.</p>

<h2>RISK MANAGEMENT</h2>
<p class="warn">⚠ Cryptocurrency trading involves substantial risk of loss.</p>
<ul>
  <li>Minimum trade: <b>£12 GBP</b> (≈ 15.24 USDT)</li>
  <li>Default risk per trade: <b>1% of portfolio</b></li>
  <li>Circuit breaker fires at <b>-5% daily drawdown</b></li>
  <li>Pair cooldown after close: <b>5 minutes</b></li>
  <li>Max simultaneous AutoTrader positions: <b>1</b></li>
  <li>Cool-off after stop-loss hit: <b>15 minutes</b></li>
  <li>API rate limit: <b>1,200 requests/min</b> (auto-throttled)</li>
</ul>

<h2>TAX REPORTING (UK)</h2>
<p>BinanceML Pro calculates UK CGT using HMRC's
<b>Section 104 pooling</b> method. Monthly PDF reports are
generated on the 1st of each month and can be emailed automatically.</p>
<p>Annual CGT allowance (2024/25): <code>£3,000</code></p>

<h2>SUPPORT</h2>
<p>Intel Log (<code>Ctrl+L</code>) shows all real-time activity from every ML module.
Error logs are saved to <code>~/.binanceml/logs/</code>.</p>
""".format(
    bg2=BG2, fg0=FG0, fg1=FG1, accent=ACCENT, accent2=ACCENT2,
    border=BORDER, bg4=BG4, yellow=YELLOW, green=GREEN,
)


# ── Help Widget ───────────────────────────────────────────────────────────────

class HelpWidget(QWidget):
    """Help, keyboard shortcuts, and documentation panel."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ─────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setFixedHeight(52)
        hdr.setStyleSheet(f"background:{BG0}; border-bottom:1px solid {BORDER};")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(20, 0, 20, 0)
        title = QLabel("HELP  &  DOCUMENTATION")
        title.setStyleSheet(f"color:{ACCENT}; font-size:13px; font-weight:700; letter-spacing:3px;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()
        version = QLabel("BinanceML Pro  v1.0.0")
        version.setStyleSheet(f"color:{FG2}; font-size:11px;")
        hdr_layout.addWidget(version)
        root.addWidget(hdr)

        # ── Tabs ────────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        self._build_shortcuts_tab()
        self._build_docs_tab()
        self._build_about_tab()

    def _build_shortcuts_tab(self) -> None:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        info = QLabel(
            f"Press and hold any nav icon for 5 s to see its tooltip — "
            f"hold for 10 s to open contextual help."
        )
        info.setStyleSheet(f"color:{FG2}; font-size:11px; padding:4px;")
        layout.addWidget(info)

        tbl = QTableWidget(len(SHORTCUTS), 3)
        tbl.setHorizontalHeaderLabels(["Category", "Shortcut", "Description"])
        tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tbl.verticalHeader().setDefaultSectionSize(22)
        tbl.setAlternatingRowColors(True)

        CAT_COLOURS = {
            "Navigation": ACCENT, "Trading": GREEN, "ML": "#AA00FF",
            "Charts": "#FF6D00", "System": FG1,
        }

        for row, (cat, key, desc) in enumerate(SHORTCUTS):
            col = CAT_COLOURS.get(cat, FG1)
            cat_it = QTableWidgetItem(cat)
            cat_it.setForeground(QBrush(QColor(col)))
            cat_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            key_it = QTableWidgetItem(key)
            key_it.setForeground(QBrush(QColor(YELLOW)))
            key_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            key_it.setFont(_monospace())
            desc_it = QTableWidgetItem(desc)
            desc_it.setForeground(QBrush(QColor(FG0)))
            tbl.setItem(row, 0, cat_it)
            tbl.setItem(row, 1, key_it)
            tbl.setItem(row, 2, desc_it)

        layout.addWidget(tbl, 1)
        self.tabs.addTab(w, svg_icon("keyboard", FG1, 14), "  Shortcuts  ")

    def _build_docs_tab(self) -> None:
        browser = QTextBrowser()
        browser.setHtml(DOCS_HTML)
        browser.setOpenExternalLinks(False)
        browser.setStyleSheet(f"background:{BG2}; border:none; padding:8px;")
        self.tabs.addTab(browser, svg_icon("info", FG1, 14), "  Documentation  ")

    def _build_about_tab(self) -> None:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        from ui.icons import svg_pixmap
        logo_lbl = QLabel()
        logo_lbl.setPixmap(svg_pixmap("logo", ACCENT, 80))
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_lbl)

        name_lbl = QLabel("BinanceML Pro")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet(f"color:{ACCENT}; font-size:22px; font-weight:700; letter-spacing:4px;")
        layout.addWidget(name_lbl)

        ver_lbl = QLabel("Version 1.0.0  ·  Professional AI Trading Platform")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_lbl.setStyleSheet(f"color:{FG2}; font-size:12px; letter-spacing:1px;")
        layout.addWidget(ver_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER};")
        layout.addWidget(sep)

        features = [
            (GREEN,  "LSTM + Transformer ensemble ML models"),
            (GREEN,  "Autonomous AutoTrader — SEMI/FULL-AUTO modes"),
            (GREEN,  "1000+ pairs: USDT / BTC / ETH / BNB / SOL quotes"),
            (GREEN,  "Multi-TF Trend Scanner — 15m to 30d across all pairs"),
            (GREEN,  "Pair ML Analyzer — Tradability Score (6 ML tools)"),
            (GREEN,  "Stealth Accumulation Detector — WATCH / ALERT / STRONG"),
            (GREEN,  "Liquidity Depth Analyzer — DEEP / ADEQUATE / THIN / ILLIQUID"),
            (GREEN,  "Volume Breakout Detector — 4-stage LAUNCH → BREAKOUT"),
            (GREEN,  "Arbitrage detector + auto-trader with £12 GBP floor"),
            (GREEN,  "Dynamic risk management with Kelly sizing"),
            (GREEN,  "UK HMRC CGT tax reporting & monthly emails"),
            (GREEN,  "Continuous learning & walk-forward validation"),
            (GREEN,  "MetaMask wallet — optional auto-sweep of profits"),
            (GREEN,  "REST API + webhooks + Telegram alerts"),
            (GREEN,  "Whale detection & sentiment analysis"),
        ]
        for col, feat in features:
            fl = QLabel(f"  ●  {feat}")
            fl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fl.setStyleSheet(f"color:{FG1}; font-size:12px;")
            layout.addWidget(fl)

        layout.addStretch()
        self.tabs.addTab(w, svg_icon("info", FG1, 14), "  About  ")


def _monospace():
    from PyQt6.QtGui import QFont
    f = QFont("JetBrains Mono")
    f.setPointSize(11)
    return f
