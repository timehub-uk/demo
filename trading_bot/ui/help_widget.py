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
    ("Navigation",   "F2",             "Go to Reports panel"),
    ("Navigation",   "Ctrl+Shift+S",   "Go to Simulation panel"),
    ("Navigation",   "Ctrl+Shift+W",   "Go to Market Watch dashboard"),
    ("Navigation",   "Ctrl+0",         "Go to Help panel"),
    ("Navigation",   "Ctrl+Shift+M",   "Go to ML Tools panel"),
    ("Navigation",   "Ctrl+Shift+V",   "Go to Simulation Twin tab"),
    ("Navigation",   "Ctrl+Alt+M",     "Go to Strategy Mutation Lab tab"),
    ("Navigation",   "Ctrl+L",         "Toggle Intel Log dock"),
    ("Navigation",   "Ctrl+B",         "Toggle Order Book dock"),
    ("Navigation",   "Ctrl+Shift+R",   "Restore Trading docks"),
    ("Navigation",   "Ctrl+\\",        "Toggle Navigation sidebar"),
    ("Trading",      "Ctrl+Shift+B",   "Toggle Trading Panel dock"),
    ("Trading",      "Ctrl+Shift+X",   "Cancel ALL open orders"),
    ("Trading",      "Ctrl+Shift+E",   "Manual Exit (AutoTrader)"),
    ("Trading",      "Ctrl+Shift+A",   "Take Aim (confirm trade)"),
    ("Trading",      "Ctrl+Shift+N",   "Scan market now"),
    ("ML",           "Ctrl+T",         "Start ML training session"),
    ("ML",           "Ctrl+Shift+T",   "Stop ML training"),
    ("ML",           "Ctrl+R",         "Reload ML model"),
    ("ML",           "Ctrl+I",         "Run data integrity check"),
    ("Simulation",   "Ctrl+Shift+S",   "Go to Simulation panel"),
    ("Simulation",   "Ctrl+Shift+V",   "Open Live Simulation Twin tab"),
    ("Simulation",   "Ctrl+Alt+M",     "Open Strategy Mutation Lab tab"),
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
    ("Charts",       "⎙ PDF button",   "Export chart to PDF (white bg, print colours)"),
    ("System",       "Ctrl+,",         "Open Settings"),
    ("System",       "Ctrl+Q",         "Quit application"),
    ("System",       "F11",            "Toggle fullscreen"),
    ("System",       "Ctrl+Shift+C",   "Check all connections"),
    ("System",       "Ctrl+Shift+D",   "Open System Status Dashboard"),
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

<h2>HOW EVERYTHING WORKS — STEP BY STEP</h2>

<h3>Step 1 · First Run — Setup Wizard</h3>
<p>On first launch the <b>Setup Wizard</b> opens automatically. It walks you through:</p>
<ol>
  <li>Enter your <b>Binance API Key + Secret</b> (read-only keys recommended for testing)</li>
  <li>Toggle <b>Testnet mode</b> — uses paper balances so no real money is at risk</li>
  <li>Set a <b>master password</b> — all keys are stored AES-256-GCM encrypted on disk</li>
  <li>Optionally add AI provider keys (Claude / OpenAI / Gemini / ElevenLabs)</li>
  <li>Choose a <b>trading mode</b>: Manual · Hybrid · Auto · Paper</li>
</ol>
<p>You can revisit any setting at <code>Settings (Ctrl+9)</code> at any time.</p>

<h3>Step 2 · Train the ML Models</h3>
<ol>
  <li>Go to <code>ML Training (Ctrl+3)</code></li>
  <li>Click <b>Start 48h Training</b> — the system downloads ~1 year of OHLCV candles for the
      top 100 pairs from Binance and trains an <b>LSTM + Transformer ensemble</b></li>
  <li>Optuna hyperparameter optimisation runs automatically during training</li>
  <li>After the initial session, the <b>Continuous Learner</b> retrains every 24 h on new data</li>
  <li>A <b>data integrity check</b> runs every 25 min; gaps or anomalies are flagged in the Intel Log</li>
</ol>
<p>You can trade in Manual mode while training runs in the background.</p>

<h3>Step 3 · Understand the Signal Pipeline</h3>
<p>Every trade candidate passes through 7 sequential gates before an order is placed:</p>
<table>
  <tr><th>#</th><th>Gate</th><th>What it checks</th><th>Blocks if…</th></tr>
  <tr><td>1</td><td>LSTM Predictor</td><td>60-bar sequence → BUY/SELL/HOLD + confidence</td><td>Confidence &lt; threshold</td></tr>
  <tr><td>2</td><td>Token ML</td><td>Per-symbol fine-tuned model adds second opinion</td><td>Conflicting signal</td></tr>
  <tr><td>3</td><td>Regime Detector</td><td>Is the market TRENDING / RANGING / VOLATILE?</td><td>Signal doesn't suit regime</td></tr>
  <tr><td>4</td><td>MTF Confluence</td><td>1h / 4h / 1d timeframes must agree</td><td>No multi-TF agreement</td></tr>
  <tr><td>5</td><td>Signal Council</td><td>Multi-model deliberation — weighted vote</td><td>Council veto</td></tr>
  <tr><td>6</td><td>Risk Manager</td><td>Kelly sizing · circuit-breaker · daily drawdown</td><td>Risk limit exceeded</td></tr>
  <tr><td>7</td><td>Ensemble Aggregator</td><td>Weights adapt from per-source accuracy history</td><td>Aggregate too low</td></tr>
</table>
<p>Only signals that pass all 7 gates reach the order entry stage.</p>

<h3>Step 4 · Run the AutoTrader</h3>
<ol>
  <li>Go to <code>AutoTrader (Ctrl+2)</code></li>
  <li>Click <b>Start Scanner</b> — scans 1 000+ USDT/BTC/ETH/BNB/SOL pairs every 15 min</li>
  <li>Each pair receives a <b>Tradability Score (0–1)</b> from 6 ML tools</li>
  <li>Pairs scoring above the threshold enter the full signal pipeline</li>
  <li>In <b>SEMI-AUTO</b> mode: confirmed signals appear in the queue — click <b>Take Aim</b> to trade</li>
  <li>In <b>FULL-AUTO</b> mode: orders are placed automatically when all gates pass</li>
</ol>
<p class="warn">⚠ Minimum trade size: £12.00 GBP (≈ 15.24 USDT). Orders below this floor are rejected.</p>

<h3>Step 5 · Watch the Intel Log</h3>
<p>Press <code>Ctrl+L</code> to open the <b>Intel Log</b> dock. Every ML module, service, and trade
action logs here in real time. Filter by level (DEBUG / INFO / WARNING / ERROR) or search by keyword.
Use <b>Export</b> to save the log to a file.</p>

<h3>Step 6 · Monitor Connection Health</h3>
<p>Go to <code>Connections (Ctrl+8)</code>. The panel shows live status for Binance REST/WS,
PostgreSQL, Redis, REST API server, voice alerts, and all <b>AI providers</b>.
Unconfigured AI providers appear in <span style="color:{yellow}">amber</span> — they are
disabled but the bot continues to run with fallback behaviour.</p>

<h3>Step 7 · Review Trades and Tax</h3>
<ol>
  <li>Go to <code>Trade Journal (Ctrl+6)</code> — full history with entry/exit annotations on charts</li>
  <li>UK CGT tax is calculated automatically under the Section 104 pool + 30-day rule</li>
  <li>Monthly PDF reports are generated on the 1st of each month (optional email delivery)</li>
  <li>Export a CSV for HMRC Self Assessment from the Trade Journal toolbar</li>
</ol>

<h2>AI PROVIDER REQUIREMENTS</h2>
<p>All AI features degrade gracefully — the bot never crashes if a key is absent.
Check live status in <code>Connections (Ctrl+8) → AI Providers</code>.</p>
<table>
  <tr><th>Provider</th><th>ML Features that use it</th><th>Fallback when disabled</th></tr>
  <tr>
    <td><span class="ok">Claude (Anthropic)</span></td>
    <td>Sentiment scoring (primary) · Signal Council AI opinion</td>
    <td>Tries OpenAI → Gemini → keyword scoring</td>
  </tr>
  <tr>
    <td><span class="warn">ChatGPT (OpenAI)</span></td>
    <td>Sentiment scoring (secondary fallback)</td>
    <td>Tries Gemini → keyword scoring · <b>Sentiment still works</b></td>
  </tr>
  <tr>
    <td><span class="warn">Gemini (Google)</span></td>
    <td>Sentiment scoring (tertiary fallback)</td>
    <td>Keyword-only sentiment scoring · <b>Sentiment still works</b></td>
  </tr>
  <tr>
    <td><span class="warn">ElevenLabs TTS</span></td>
    <td>High-quality voice alerts for trades, signals, whale events</td>
    <td>macOS <code>say</code> / Linux <code>espeak</code> · <b>Voice alerts still work</b></td>
  </tr>
</table>
<p class="warn">⚠ When ALL three sentiment providers are disabled, the Sentiment Analyser falls back to
keyword-only scoring (bull/bear keyword counts). The signal pipeline continues to operate;
only the AI-quality sentiment score is degraded.</p>

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

<h3>Chart Styles</h3>
<p>Candlestick · OHLC Bar · Heikin-Ashi · Line · Area — switch with the STYLE buttons in toolbar row 1.</p>

<h3>Overlays (toolbar row 1 pills)</h3>
<p>EMA 9/20/50/200 · SMA 20/50 · Bollinger Bands (20,2σ) · VWAP ±1σ/±2σ · Ichimoku Cloud</p>

<h3>Sub-Panel Oscillators (toolbar row 2 pills)</h3>
<p>Volume + OBV · RSI (14) with overbought/oversold fill · MACD (12,26,9) histogram ·
Stochastic (14,3,3) · ATR (14) · ADX (14) with ±DI lines</p>

<h3>AI Forecast Overlay</h3>
<p>Toggle <b>AI FORECAST</b> pill → choose 5b / 10b / 20b / 50b / 100b horizon.
Green cone = bullish · Red cone = bearish. <b>ACC</b> badge shows live historical accuracy vs model ceiling.</p>

<h3>Trade Markers</h3>
<p>Toggle <b>TRADES</b> pill → gold squares at every entry/exit, connected by a dotted line.
Hover any square for full trade details: side, price, qty, gross P&amp;L, fees (2×0.1%), UK CGT 20%, net.</p>

<h3>Event Annotations (EVENTS pill)</h3>
<p>Coloured diamond markers appear on the price chart for live market events — fired automatically
as they occur from the backend services:</p>
<table>
  <tr><th>Event Type</th><th>Colour</th><th>Source</th></tr>
  <tr><td>CASCADE</td><td style="color:#FF5722">▼ orange-red</td><td>Liquidation cascade detector</td></tr>
  <tr><td>WHALE</td><td style="color:#CE93D8">◆ purple</td><td>Whale watcher (large block orders)</td></tr>
  <tr><td>FUNDING</td><td style="color:#FFD700">◆ gold</td><td>Funding rate monitor (±0.10 % trigger)</td></tr>
  <tr><td>LEAD_LAG</td><td style="color:#26C6DA">→ cyan</td><td>Correlation engine (lead/lag opportunity)</td></tr>
  <tr><td>AGGRESSOR</td><td style="color:#FF7043">★ deep-orange</td><td>Order flow monitor (smart money)</td></tr>
  <tr><td>ML_SIGNAL</td><td style="color:#4CAF50">▲ green</td><td>ML predictor BUY signal</td></tr>
  <tr><td>VOLUME_SPIKE</td><td style="color:#AB47BC">↑ purple</td><td>Volume spike alert</td></tr>
</table>
<p>Hover any diamond for a tooltip: event type, UTC timestamp, and detail text.</p>

<h3>Session Background Bands (SESSIONS pill)</h3>
<p>Faint colour bands mark the three major trading sessions across every visible day:</p>
<ul>
  <li><span style="color:#7986CB">■ Asian</span> — 00:00–09:00 UTC (deep blue)</li>
  <li><span style="color:#66BB6A">■ London</span> — 07:00–16:00 UTC (deep green)</li>
  <li><span style="color:#EF5350">■ New York</span> — 13:00–21:00 UTC (deep red)</li>
</ul>

<h3>Auto Support &amp; Resistance (S/R pill)</h3>
<p>Automatically detects swing highs and lows using a 5-bar rolling window, clusters levels within
±0.5%, and draws up to 5 <span class="warn">red dashed resistance</span> and 5
<span class="ok">green dashed support</span> lines with price labels.</p>

<h3>Pair Watermark (WMARK pill)</h3>
<p>Ultra-faint bold pair name (e.g. <b>BTC — USDT</b>) centred on the price plot, ~5 % opacity.
Useful for screenshots and screen shares. Toggle off for a cleaner chart.</p>

<h3>PDF Export (⎙ PDF button, top-right toolbar)</h3>
<p>Exports the chart to a landscape A4 PDF with a <b>white background and print-optimised colours</b>
(indicator lines remapped to dark-on-white equivalents, axis text set to near-black).
A header showing <code>SYMBOL · INTERVAL · UTC timestamp</code> is added automatically.
The live dark-theme view is restored immediately after capture.</p>

<h3>Chart Navigation (toolbar row 3)</h3>
<p>◀◀ / ◀ / ▶ / ▶▶ pan · − Zoom / + Zoom / Fit · Auto-Scale · Auto-Follow (locks view to latest candles)</p>

<h2>MARKET WATCH DASHBOARD (Ctrl+Shift+W)</h2>
<p>Unified real-time market surveillance panel with six tabs.
Each backend service has an <b>on/off toggle button</b> in the top bar — when disabled the
service stops all processing and fires no alerts, saving CPU and network bandwidth.</p>

<h3>Backend Services (toggle bar)</h3>
<table>
  <tr><th>Service</th><th>What it does</th><th>Alert trigger</th></tr>
  <tr>
    <td><b>Funding Rate Monitor</b></td>
    <td>Polls Binance perpetual futures <code>/fapi/v1/premiumIndex</code> every 5 min</td>
    <td>Rate ≥ ±0.10 % → FUNDING_RATE alert</td>
  </tr>
  <tr>
    <td><b>Order Flow (OFI)</b></td>
    <td>Consumes aggTrade WebSocket; tracks 1-min and 5-min buy/sell aggressor ratio and
        Order Flow Imbalance per symbol</td>
    <td>1-min ratio ≥ 72 % (BUY_PRESSURE) or ≤ 28 % (SELL_PRESSURE) → AGGRESSOR alert</td>
  </tr>
  <tr>
    <td><b>Correlation Engine</b></td>
    <td>Lead/lag detector for BTC→ETH/BNB/SOL/XRP and ETH→BNB.
        Adaptive Welford thresholds learn each pair's normal move size (MIN_SAMPLES=20).
        Pearson r checked — only pairs with r ≥ 0.50 generate alerts.</td>
    <td>Leader moves &gt; adaptive threshold AND follower hasn't reacted within 45 s → LEAD_LAG alert</td>
  </tr>
  <tr>
    <td><b>Cascade Detector</b></td>
    <td>Compound liquidation cascade detector. Per-symbol Welford statistics learn
        normal price-move magnitude and volume-spike ratios (MIN_SAMPLES=30).
        Fires when BOTH price ≥ adaptive threshold AND volume ≥ adaptive threshold within a 2-min window.</td>
    <td>CASCADE alert — severity: MEDIUM / HIGH / EXTREME</td>
  </tr>
</table>

<h3>Tab 1 — Volume Alerts</h3>
<p>Single scrolling table (max 300 rows) receiving alerts from all types:
VOLUME_SPIKE · EARLY_PUMP · CASCADE · FUNDING_RATE · LEAD_LAG · AGGRESSOR · WHALE.
Columns: Time · Type · Symbol · Details · Value.</p>

<h3>Tab 2 — ML Watch</h3>
<p>Two-pane layout: top = live signal feed (Time · Symbol · Signal · Confidence · Source),
bottom = per-symbol confidence summary table. Receives signals from the LSTM predictor,
continuous learner, and whale watcher.</p>

<h3>Tab 3 — Order Flow</h3>
<p>Live table updated every 30 s: Symbol · Buy Vol 1m · Sell Vol 1m · Aggressor % · OFI 1m ·
Buy Vol 5m · Signal.  Colour-coded: green BUY_PRESSURE / red SELL_PRESSURE / grey NEUTRAL.</p>

<h3>Tab 4 — Portfolio Heatmap</h3>
<p>Grid of tiles — one per open position. Tile <b>colour</b> = P&amp;L direction/magnitude
(deep green profit → deep red loss). Tile <b>size</b> = position USD value (60–140 px).
Updates every 5 seconds.</p>

<h3>Tab 5 — Regime &amp; Cascade</h3>
<p>Left: market regime table per symbol (TRENDING · RANGING · VOLATILE · BEAR · BULL).
Right: cascade and lead-lag event feed with severity labels.
Split with a resizable QSplitter. Polls every 30 s.</p>

<h3>Tab 6 — Kill Switch</h3>
<p>Emergency trading halt controls with confirmation dialogs:</p>
<ul>
  <li><b>Cancel All Orders</b> — cancels every open order on Binance immediately</li>
  <li><b>Pause AutoTrader</b> — stops the AutoTrader from placing new orders</li>
  <li><b>Switch to Paper Mode</b> — switches execution to simulated paper trading</li>
  <li><b>EMERGENCY STOP</b> (large red button) — executes all three actions simultaneously</li>
</ul>

<h2>STREAM DECK INTEGRATION</h2>
<p>If an <b>Elgato Stream Deck</b> is connected, BinanceML Pro maps trading actions to the physical
buttons automatically.  No Stream Deck hardware? The integration silently does nothing — no errors.</p>
<p>Set <code>STREAM_DECK_SIMULATE=1</code> as an environment variable to test button renders
without hardware.</p>
<table>
  <tr><th>Button</th><th>Row</th><th>Action</th></tr>
  <tr><td>Keys 0–4</td><td>Row 1</td><td>BUY BTC · ETH · SOL · BNB · XRP (market order at current size)</td></tr>
  <tr><td>Keys 5–9</td><td>Row 2</td><td>SELL BTC · ETH · SOL · BNB · XRP</td></tr>
  <tr><td>Key 10</td><td>Row 3</td><td>Enable AUTO trading mode</td></tr>
  <tr><td>Key 11</td><td>Row 3</td><td>Disable AUTO trading mode</td></tr>
  <tr><td>Key 12</td><td>Row 3</td><td>Switch to PAPER mode</td></tr>
  <tr><td>Key 13</td><td>Row 3</td><td>CANCEL ALL open orders</td></tr>
  <tr><td>Key 14</td><td>Row 3</td><td>⛔ KILL — emergency stop (cancel all + pause AT)</td></tr>
</table>
<p>Live prices and P&amp;L are displayed on the button faces (refreshed every heartbeat).</p>

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

<h2>ON-CHAIN DATA APIS (Settings → On-Chain)</h2>

<h3>MetaMask Live Data</h3>
<p>Polls your EVM wallet address using <b>free public JSON-RPC endpoints</b> — no API key required.
Runs as a background thread, updating every 30 seconds. Provides:</p>
<ul>
  <li>Native balance (ETH / BNB / MATIC …)</li>
  <li>ERC-20 token balances (USDT, USDC, WBTC, DAI, LINK, UNI, AAVE, WETH …)</li>
  <li>Current gas price (standard + fast tier)</li>
  <li>Latest block number and transaction count (nonce)</li>
</ul>
<p>Configure under <code>Settings (Ctrl+9) → On-Chain → MetaMask Live Data</code>.</p>

<h3>CoinGecko DEX API v3</h3>
<p>On-chain pool data sourced from CoinGecko's DEX endpoints:</p>
<ul>
  <li>Top liquidity pools by network (Ethereum, BSC, Polygon, Arbitrum)</li>
  <li>Pool OHLCV data and 24h volume / liquidity statistics</li>
  <li>Trending tokens by network</li>
  <li>Token metadata (market cap, price, fully diluted valuation)</li>
</ul>
<p>Free tier: <b>10,000 calls/month</b> → automatically budgeted to <b>~13 calls/hr</b>
using a 12-slot hourly scheduler + 1 emergency reserve slot.</p>
<table>
  <tr><th>Plan</th><th>Monthly quota</th><th>Auto-budget (calls/hr)</th></tr>
  <tr><td>Demo</td><td>10,000</td><td>~13</td></tr>
  <tr><td>Analyst / Lite</td><td>500,000</td><td>~680</td></tr>
  <tr><td>Pro</td><td>1,000,000</td><td>~1,370</td></tr>
</table>
<p>Configure under <code>Settings (Ctrl+9) → On-Chain → CoinGecko DEX API</code>.
Get a free API key at <code>https://www.coingecko.com/en/api</code>.</p>

<h3>Codex GraphQL API</h3>
<p>On-chain token and pair statistics via GraphQL. Used as a <b>confirmation gate</b>
for high-confidence DEX arbitrage opportunities:</p>
<ul>
  <li>Pair stats: price, 24h volume, liquidity, buy/sell counts</li>
  <li>Token info: market cap, holders, deployer, launch date</li>
  <li>OHLCV data and recent trades</li>
</ul>
<p>Free tier: <b>~500 calls/month</b> → <b>~1 call per 87 minutes</b>.
Only fired after 0x confirms a spread is real (emergency confirmation gate).
Get a free API key at <code>https://www.codex.io</code>.</p>

<h3>0x Protocol Swap API v2</h3>
<p>Real-time <b>executable DEX swap prices</b> aggregated across Uniswap, Curve,
Balancer, SushiSwap and other major DEXs:</p>
<ul>
  <li><code>permit2/price</code> — indicative price, no signature needed (used for validation)</li>
  <li>Returns best route, price impact %, gas estimate, liquidity sources breakdown</li>
  <li>Supports: Ethereum · BSC · Polygon · Arbitrum · Optimism · Base</li>
</ul>
<p>Free tier: <b>1 req/s</b>. The arbitrage detector throttles to
1 call per 30 s per symbol to stay well within the budget.
Get a free API key at <code>https://dashboard.0x.org</code>.</p>

<h3>DEX Arbitrage Confirmation Pipeline</h3>
<p>When a DEX↔CEX spread opportunity is detected:</p>
<ol>
  <li><b>CoinGecko cache</b> (free, no new call) → pool DEX price</li>
  <li><b>Binance WebSocket</b> → CEX price · spread &gt; 0.3%?</li>
  <li><b>0x get_price()</b> → confirms actual <em>executable</em> DEX price
    — boosts confidence ×1.1 if confirmed, discounts ×0.7 if price was tighter</li>
  <li><b>Codex emergency call</b> → pool liquidity depth (fired only when 0x confirms + confidence &gt; 80%)</li>
</ol>
<p>This preserves the Codex monthly budget for genuine opportunities only.</p>

<h3>DEX Features in ML Training</h3>
<p>When CoinGecko is active, the ML training pipeline automatically injects four
on-chain features per symbol:</p>
<table>
  <tr><th>Feature</th><th>What it represents</th></tr>
  <tr><td><code>dex_volume_24h_usd_norm</code></td><td>Log-normalised 24h on-chain volume</td></tr>
  <tr><td><code>dex_liquidity_usd_norm</code></td><td>Log-normalised pool liquidity depth</td></tr>
  <tr><td><code>dex_vol_liq_ratio</code></td><td>Volume ÷ liquidity (liquidity utilisation)</td></tr>
  <tr><td><code>dex_pool_count_top5</code></td><td>Number of top-5 pools for this token</td></tr>
</table>

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

<h2>SYSTEM STATUS DASHBOARD (Ctrl+Shift+D)</h2>
<p>Opens a Grafana-style popup showing 60-second rolling graphs for six system metrics:</p>
<table>
  <tr><th>Panel</th><th>What it shows</th></tr>
  <tr><td>CPU %</td><td>System CPU utilisation (all cores, sampled every second)</td></tr>
  <tr><td>MEM %</td><td>System memory utilisation</td></tr>
  <tr><td>DB Latency ms</td><td>PostgreSQL round-trip query time</td></tr>
  <tr><td>Redis Latency ms</td><td>Redis PING round-trip time</td></tr>
  <tr><td>NET TX KB/s</td><td>Network bytes sent per second</td></tr>
  <tr><td>NET RX KB/s</td><td>Network bytes received per second</td></tr>
</table>
<p>A DEX API Quota panel shows remaining CoinGecko calls/hr, Codex calls/hr,
scheduler cache warm slots (N/12), and emergency slot availability.</p>
<p>Also accessible via: <b>Setup menu → System → Status/Health</b>
or by clicking any status indicator in the bottom status bar.</p>

<h2>STATUS BAR (Bottom of Screen)</h2>
<p>The bottom status bar shows live indicators — click any to open the System Status Dashboard:</p>
<ul>
  <li><span class="ok">● Network: ONLINE</span> — internet connectivity (checked every 15 s)</li>
  <li><span class="ok">● DB: ONLINE</span> — PostgreSQL connection status</li>
  <li><span class="ok">● Redis: ONLINE</span> — Redis connection status</li>
  <li><span class="ok">● API: ACTIVE</span> — Binance REST API status</li>
  <li><b>P/L: +£12.34</b> — today's realised profit/loss (GBP)</li>
  <li><b>Trading mode</b> — PAPER / LIVE / AUTO / HYBRID</li>
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
        version = QLabel("BinanceML Pro  v0.0.1")
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

        ver_lbl = QLabel("Version 0.0.1  ·  Professional AI Trading Platform")
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
            (GREEN,  "Statistical + Triangular + DEX↔CEX Spread arbitrage"),
            (GREEN,  "CoinGecko DEX API — on-chain pool data, 12-slot hourly scheduler"),
            (GREEN,  "Codex GraphQL API — pool liquidity confirmation gate"),
            (GREEN,  "0x Protocol Swap API — executable DEX price validation"),
            (GREEN,  "MetaMask Live Data — free public RPC wallet polling"),
            (GREEN,  "DEX on-chain ML features — volume, liquidity, pool count"),
            (GREEN,  "Grafana-style System Status Dashboard (Ctrl+Shift+D)"),
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
            (GREEN,  "Market Watch dashboard — 6-tab market surveillance (Ctrl+Shift+W)"),
            (GREEN,  "Funding Rate Monitor — perpetual futures ±0.10 % extreme alerts"),
            (GREEN,  "Order Flow / OFI — aggressor ratio + smart-money detection"),
            (GREEN,  "Correlation Engine — lead/lag detector with Welford adaptive thresholds"),
            (GREEN,  "Cascade Detector — liquidation cascade ML (adaptive per-symbol σ)"),
            (GREEN,  "Portfolio Heatmap — P&L colour tiles sized by position USD value"),
            (GREEN,  "Emergency Kill Switch — Cancel All · Pause AT · Paper Mode"),
            (GREEN,  "Elgato Stream Deck — 15-button hardware trading control panel"),
            (GREEN,  "Chart event annotations — CASCADE/WHALE/FUNDING/LEAD-LAG on chart"),
            (GREEN,  "Chart session bands — Asian / London / NY coloured regions"),
            (GREEN,  "Auto S/R levels — swing-high/low cluster detection"),
            (GREEN,  "Chart PDF export — white background, print-optimised colours"),
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
