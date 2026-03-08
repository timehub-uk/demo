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
    ("Navigation",   "Ctrl+1",         "Go to Trading panel"),
    ("Navigation",   "Ctrl+2",         "Go to AutoTrader panel"),
    ("Navigation",   "Ctrl+3",         "Go to ML Training panel"),
    ("Navigation",   "Ctrl+4",         "Go to Risk Dashboard"),
    ("Navigation",   "Ctrl+5",         "Go to Backtesting"),
    ("Navigation",   "Ctrl+6",         "Go to Trade Journal"),
    ("Navigation",   "Ctrl+7",         "Go to Strategy Builder"),
    ("Navigation",   "Ctrl+8",         "Go to Connections"),
    ("Navigation",   "Ctrl+9",         "Go to Settings"),
    ("Navigation",   "F1",             "Go to Help"),
    ("Navigation",   "Ctrl+Shift+S",   "Go to Simulation Panel"),
    ("Navigation",   "Ctrl+L",         "Toggle Intel Log dock"),
    ("Navigation",   "Ctrl+B",         "Toggle Order Book dock"),
    ("Trading",      "Ctrl+Shift+B",   "Market BUY current symbol"),
    ("Trading",      "Ctrl+Shift+X",   "Cancel ALL open orders"),
    ("Trading",      "Ctrl+Shift+E",   "Manual Exit (AutoTrader)"),
    ("Trading",      "Ctrl+Shift+A",   "Take Aim (confirm trade)"),
    ("Trading",      "Ctrl+Shift+N",   "Scan market now"),
    ("ML",           "Ctrl+T",         "Start ML training session"),
    ("ML",           "Ctrl+Shift+T",   "Stop ML training"),
    ("ML",           "Ctrl+R",         "Reload ML model"),
    ("ML",           "Ctrl+I",         "Run data integrity check"),
    ("Simulation",   "Ctrl+Shift+T",   "Open Simulation Twin tab"),
    ("Simulation",   "Ctrl+Shift+M",   "Open Mutation Lab tab"),
    ("Simulation",   "Ctrl+Shift+F",   "Open Safety Scanner tab"),
    ("Layer 1",      "Shift+Alt+1",    "Layer 1 – Infrastructure settings"),
    ("Layer 2",      "Shift+Alt+2",    "Layer 2 – Market Data settings"),
    ("Layer 3",      "Shift+Alt+3",    "Layer 3 – Data Engineering settings"),
    ("Layer 4",      "Shift+Alt+4",    "Layer 4 – Research & Quant settings"),
    ("Layer 5",      "Shift+Alt+5",    "Layer 5 – Alpha & Signal settings"),
    ("Layer 6",      "Shift+Alt+6",    "Layer 6 – Risk settings"),
    ("Layer 7",      "Shift+Alt+7",    "Layer 7 – Execution settings"),
    ("Layer 8",      "Shift+Alt+8",    "Layer 8 – Token Safety settings"),
    ("Layer 9",      "Shift+Alt+9",    "Layer 9 – Monitoring settings"),
    ("Layer 10",     "Shift+Alt+0",    "Layer 10 – Governance settings"),
    ("Charts",       "Ctrl++",         "Add chart tab"),
    ("Charts",       "Ctrl+W",         "Close current chart tab"),
    ("Charts",       "Ctrl+Tab",       "Next chart tab"),
    ("System",       "Ctrl+,",         "Open Settings"),
    ("System",       "Ctrl+Q",         "Quit application"),
    ("System",       "F11",            "Toggle fullscreen"),
    ("System",       "Ctrl+Shift+C",   "Check all connections"),
]

# ── FAQ / documentation ───────────────────────────────────────────────────────

DOCS_HTML = """
<style>
  body  {{ font-family: 'JetBrains Mono', monospace; font-size: 12px;
          background: {bg2}; color: {fg0}; padding: 16px; }}
  h2    {{ color: {accent}; font-size: 14px; letter-spacing: 2px;
          border-bottom: 1px solid {border}; padding-bottom: 6px; margin-top: 20px; }}
  h3    {{ color: {fg1}; font-size: 12px; margin-top: 14px; }}
  code  {{ background: {bg4}; color: {accent2}; padding: 2px 6px;
          border-radius: 3px; font-size: 11px; }}
  p, li {{ color: {fg0}; line-height: 1.6; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
  th    {{ color: {accent}; font-size: 11px; text-align: left;
          border-bottom: 1px solid {border2}; padding: 4px 8px; }}
  td    {{ color: {fg0}; font-size: 11px; padding: 3px 8px;
          border-bottom: 1px solid {border}; }}
  .warn {{ color: {yellow}; }}
  .ok   {{ color: {green}; }}
</style>

<h2>GETTING STARTED</h2>

<h3>1. Configure API Keys</h3>
<p>Open <code>Settings (Ctrl+9) → System</code> and enter your Binance API Key and Secret.
Enable <b>Testnet</b> while testing — testnet keys use paper balances only.</p>

<h3>2. Choose a Trading Mode</h3>
<ul>
  <li><b>Manual</b> – You place every order in the Trading panel</li>
  <li><b>Auto</b> – ML signals trigger orders automatically when confidence ≥ threshold</li>
  <li><b>Hybrid</b> – ML recommends; you confirm with <b>🎯 Take Aim</b></li>
  <li><b>Paper</b> – Simulated execution on real prices, no real money</li>
</ul>

<h3>3. Start the AutoTrader</h3>
<p>Go to <code>AutoTrader (Ctrl+2)</code>. The scanner runs every 5 minutes across
1 000+ USDT / BTC / ETH / BNB / SOL pairs, running the full ML stack.</p>
<p class="warn">⚠ Minimum trade size: £12.00 GBP (≈ 15.24 USDT). Orders below this floor are rejected.</p>

<h3>4. Train the ML Model</h3>
<p>Go to <code>ML Training (Ctrl+3)</code> → <b>Start 48h Training</b>.
The initial training session downloads ~1 year of candle data for the top 100 pairs
and trains an LSTM + Transformer ensemble. After that, models retrain automatically every 24h.</p>

<h2>ML INTELLIGENCE STACK</h2>

<h3>Signal Pipeline (in order)</h3>
<table>
  <tr><th>Stage</th><th>Component</th><th>What it does</th></tr>
  <tr><td>1</td><td>LSTM Predictor</td><td>Per-bar sequence model (60-bar lookback) → raw BUY/SELL/HOLD + confidence</td></tr>
  <tr><td>2</td><td>Token ML</td><td>Per-symbol fine-tuned model adds a second opinion</td></tr>
  <tr><td>3</td><td>Regime Detector</td><td>Blocks signals that don't suit current market regime (TRENDING/RANGING/VOLATILE)</td></tr>
  <tr><td>4</td><td>MTF Confluence</td><td>1h / 4h / 1d timeframe agreement required to pass</td></tr>
  <tr><td>5</td><td>Signal Council</td><td>Multi-model deliberation — can veto any signal</td></tr>
  <tr><td>6</td><td>Dynamic Risk Manager</td><td>Kelly-based position sizing · circuit-breaker drawdown guard</td></tr>
  <tr><td>7</td><td>Ensemble Aggregator</td><td>Weights adapt based on per-source historical accuracy</td></tr>
</table>

<h3>Pair Discovery &amp; Scanning (AutoTrader → tabs)</h3>
<ul>
  <li><code>Pair Scanner</code> – Scans 1 000+ pairs every 15 min, ranks by volume / activity /
      momentum → <b>HIGH / MEDIUM / LOW</b> priority buckets.</li>
  <li><code>Multi-TF Trend Scanner</code> – Classifies every pair as UP / SIDEWAYS / DOWN
      across 7 timeframes: 15m, 30m, 1h, 12h, 24h, 7d, 30d.</li>
  <li><code>Pair ML Analyzer</code> – Cross-references all 6 ML tools per pair every 5 min
      → <b>Tradability Score</b> (0–1).</li>
  <li><code>Accumulation Detector</code> – Finds stealth accumulation: tight band + rising volume
      + taker-buy dominance. Labels: NONE / WATCH / ALERT / STRONG. Scans every 30 min.</li>
  <li><code>Liquidity Depth Analyzer</code> – Grades order-book depth:
      DEEP / ADEQUATE / THIN / ILLIQUID. Estimates slippage for the £12 minimum trade size.
      Scans HIGH+MEDIUM pairs every 10 min.</li>
  <li><code>Volume Breakout Detector</code> – Detects 4-stage patterns:
      <b>Stage 1 LAUNCH</b> → <b>Stage 2 PUMP</b> → <b>Stage 3 CONSOLIDATION</b>
      → <b>Stage 4 BREAKOUT</b>. Scans every 15 min.</li>
</ul>

<h3>Whale Watcher &amp; Sentiment</h3>
<ul>
  <li><code>Whale Watcher</code> – Monitors L2 order book for block orders above threshold,
      volume spikes &gt; 3σ, and smart-money accumulation / distribution patterns.</li>
  <li><code>Sentiment Analyser</code> – News + social media scoring fed into Signal Council.</li>
</ul>

<h3>Data Flow</h3>
<p><code>Pair Scanner</code> → <code>Trend / Accum / Liquidity / Breakout</code>
→ <code>Pair ML Analyzer</code> (tradability score)
→ <code>AutoTrader</code> → <code>Signal Pipeline</code>
→ <code>TradingEngine</code> → <code>Binance REST API</code></p>

<h2>CHART FEATURES</h2>

<h3>Overlays</h3>
<p>EMA 9/20/50/200 · SMA 20/50 · Bollinger Bands · VWAP ±1σ/±2σ · Ichimoku Cloud</p>

<h3>Sub-Panel Oscillators</h3>
<p>Volume + OBV · RSI (14) · MACD (12,26,9) · Stochastic (14,3,3) · ATR (14) · ADX (14)</p>

<h3>AI Forecast Overlay</h3>
<p>Toggle <b>AI FORECAST</b> pill → choose 5b / 10b / 20b / 50b / 100b horizon.
Green cone = bullish · Red cone = bearish. <b>ACC</b> badge shows historical accuracy.</p>

<h3>Trade Markers</h3>
<p>Toggle <b>TRADES</b> pill → yellow squares at every entry/exit, connected by a dotted line.
Hover for full trade details (side, price, qty, gross P&amp;L, fees, tax, net).</p>

<h2>REST API</h2>
<p>Auto-starts at <code>http://127.0.0.1:8765</code>. Use Bearer token from Settings → API Keys.</p>
<table>
  <tr><th>Method</th><th>Path</th><th>Description</th></tr>
  <tr><td>GET</td><td>/health</td><td>Health check (no auth)</td></tr>
  <tr><td>GET</td><td>/api/v1/status</td><td>Engine mode, uptime</td></tr>
  <tr><td>GET</td><td>/api/v1/portfolio</td><td>Balances (USDT + GBP)</td></tr>
  <tr><td>GET</td><td>/api/v1/signals</td><td>Latest ML signals</td></tr>
  <tr><td>GET</td><td>/api/v1/trades</td><td>Recent trades (?limit=50&amp;symbol=BTCUSDT)</td></tr>
  <tr><td>POST</td><td>/api/v1/order</td><td>Place a limit order</td></tr>
  <tr><td>DELETE</td><td>/api/v1/order/{id}</td><td>Cancel an order</td></tr>
  <tr><td>POST</td><td>/api/v1/ml/predict</td><td>On-demand prediction</td></tr>
  <tr><td>GET</td><td>/api/v1/tax/monthly</td><td>Monthly CGT summary</td></tr>
  <tr><td>POST</td><td>/api/v1/webhook/register</td><td>Register a webhook URL</td></tr>
</table>

<h2>METAMASK WALLET (Settings → MetaMask)</h2>
<p>Optional profit-sweeping to any EVM wallet:</p>
<ul>
  <li>Enter your <b>0x…</b> EVM address</li>
  <li>Select network: BSC (lowest fees) · Ethereum · Polygon · Arbitrum</li>
  <li><b>Auto-sweep</b> — transfers profits automatically when they exceed your threshold</li>
  <li><b>Manual Transfers</b> — approve each transfer individually in the transfers table</li>
  <li>Binance must have the address whitelisted for withdrawals</li>
</ul>
<p class="warn">⚠ Auto-sweep uses the Binance Withdrawal API only — your private key is never required or stored.</p>

<h2>RISK MANAGEMENT</h2>
<p class="warn">⚠ Cryptocurrency trading involves substantial risk of loss.</p>
<ul>
  <li>Minimum trade: <b>£12 GBP</b> (≈ 15.24 USDT)</li>
  <li>Default risk per trade: <b>1% of portfolio</b></li>
  <li>Circuit breaker fires at <b>−5% daily drawdown</b></li>
  <li>Pair cooldown after close: <b>5 minutes</b></li>
  <li>Max simultaneous AutoTrader positions: <b>1</b></li>
  <li>Cool-off after stop-loss hit: <b>15 minutes</b></li>
  <li>Binance API rate limit: <b>1,200 requests/min</b> (auto-throttled)</li>
</ul>

<h2>UK TAX REPORTING</h2>
<p>BinanceML Pro calculates UK CGT using HMRC's rules (Section 104 pool,
30-day bed-and-breakfast rule, same-day matching).</p>
<ul>
  <li>Monthly PDF reports generated on the 1st of each month (can be emailed)</li>
  <li>Annual CGT allowance (2024/25): <code>£3,000</code></li>
  <li>Basic rate: <code>10%</code> · Higher rate: <code>20%</code></li>
  <li>Export trade history CSV for HMRC Self Assessment via Trade Journal</li>
</ul>

<h2>SIMULATION</h2>
<ul>
  <li><code>Live Simulation Twin (Ctrl+Shift+T)</code> – Shadows every live decision across
      6 parallel variants (size_half, size_2x, delayed_5m, tighter_stop, wider_stop, skip).
      Drift detection alerts if live accuracy deviates &gt;5% from backtested baseline.</li>
  <li><code>Strategy Mutation Lab (Ctrl+Shift+M)</code> – Genetic evolution of strategy parameters:
      initialise → evaluate → gate (Sharpe &lt; 0.5 rejected) → breed → promote champions.</li>
  <li><code>Safety Scanner (Ctrl+Shift+F)</code> – Honeypot detection, liquidity lock check,
      contract analysis, rug-pull scoring (0–100%).</li>
</ul>

<h2>SUPPORT &amp; LOGS</h2>
<p>Intel Log (<code>Ctrl+L</code>) shows all real-time activity from every ML module and service.</p>
<p>Log files are saved to <code>~/.binanceml/logs/</code>. Config is at
<code>~/.binanceml/config.enc</code> (AES-256-GCM encrypted).</p>
<p class="ok">● SQLAlchemy 3.0 compatible — all DB queries use the select() API.</p>
""".format(
    bg2=BG2, fg0=FG0, fg1=FG1, accent=ACCENT, accent2=ACCENT2,
    border=BORDER, border2=BORDER2, bg4=BG4, yellow=YELLOW, green=GREEN,
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
        version = QLabel("BinanceML Pro  v2.0")
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

        ver_lbl = QLabel("Version 2.0  ·  Professional AI Trading Platform")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_lbl.setStyleSheet(f"color:{FG2}; font-size:12px; letter-spacing:1px;")
        layout.addWidget(ver_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER};")
        layout.addWidget(sep)

        features = [
            (GREEN,  "LSTM + Transformer ensemble ML models — MPS GPU accelerated"),
            (GREEN,  "Autonomous AutoTrader — SEMI/FULL-AUTO modes"),
            (GREEN,  "1 000+ pairs: USDT / BTC / ETH / BNB / SOL quotes"),
            (GREEN,  "7-stage signal pipeline: Regime → MTF → Council → Risk"),
            (GREEN,  "Multi-TF Trend Scanner — 15m to 30d across all pairs"),
            (GREEN,  "Pair ML Analyzer — Tradability Score (6 ML tools)"),
            (GREEN,  "Stealth Accumulation Detector — WATCH / ALERT / STRONG"),
            (GREEN,  "Liquidity Depth Analyzer — DEEP / ADEQUATE / THIN / ILLIQUID"),
            (GREEN,  "Volume Breakout Detector — 4-stage LAUNCH → BREAKOUT"),
            (GREEN,  "Statistical + triangular arbitrage auto-trader"),
            (GREEN,  "Ping-Pong range trader with consecutive-loss protection"),
            (GREEN,  "Live Simulation Twin — 6 shadow variants + drift detection"),
            (GREEN,  "Strategy Mutation Lab — genetic parameter evolution"),
            (GREEN,  "Token safety scanner — honeypot, rug-pull, liquidity lock"),
            (GREEN,  "Dynamic risk management with Kelly position sizing"),
            (GREEN,  "UK HMRC CGT tax reporting · Section 104 pool · monthly PDFs"),
            (GREEN,  "Continuous learning & walk-forward validation every 24 h"),
            (GREEN,  "MetaMask wallet — optional auto-sweep of profits to EVM"),
            (GREEN,  "REST API (15+ endpoints) + webhooks · Bearer token auth"),
            (GREEN,  "Whale detection · sentiment analysis · AES-256-GCM security"),
            (GREEN,  "SQLAlchemy 3.0-ready — all queries use select() API"),
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
