# BinanceML Pro — Installation, Setup & User Manual

**Version 2.0 · Professional AI Trading Platform for Binance**

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Installation](#2-installation)
3. [First-Run Setup Wizard](#3-first-run-setup-wizard)
4. [Application Overview](#4-application-overview)
5. [Trading Panel](#5-trading-panel)
6. [Chart Features](#6-chart-features)
7. [AutoTrader Panel](#7-autotrader-panel)
8. [Ping-Pong Range Trader](#8-ping-pong-range-trader)
9. [ML Strategy Selector](#9-ml-strategy-selector)
10. [Arbitrage Detector & Auto-Trader](#10-arbitrage-detector--auto-trader)
11. [ML Training Panel](#11-ml-training-panel)
12. [Risk Dashboard](#12-risk-dashboard)
13. [Trade Journal](#13-trade-journal)
14. [Backtesting Engine](#14-backtesting-engine)
15. [Connections & Health](#15-connections--health)
16. [On-Chain Data APIs](#16-on-chain-data-apis)
17. [Settings & Layer Configuration](#17-settings--layer-configuration)
18. [Simulation Panel](#18-simulation-panel)
19. [REST API Reference](#19-rest-api-reference)
20. [UK Tax (CGT) Reporting](#20-uk-tax-cgt-reporting)
21. [Keyboard Shortcuts](#21-keyboard-shortcuts)
22. [Troubleshooting](#22-troubleshooting)
23. [Architecture Overview — 10-Layer Stack](#23-architecture-overview--10-layer-stack)

---

## 1. System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Ubuntu 20.04 / macOS 12 / Windows 10 | Ubuntu 22.04 / macOS 14 (M4) |
| Python | 3.10 | 3.11+ |
| RAM | 8 GB | 16 GB+ |
| Storage | 10 GB free | 50 GB SSD |
| CPU | 4 cores | Apple M4 or Intel i7+ |
| GPU | None (CPU training) | Apple Silicon MPS / CUDA |
| Network | 10 Mbit/s | 100 Mbit/s+ |
| Binance account | Required | API keys with trading permissions |

---

## 2. Installation

### 2.1 Clone the Repository

```bash
git clone https://github.com/timehub-uk/demo.git
cd demo
```

### 2.2 Create a Python Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate.bat       # Windows
```

### 2.3 Install Dependencies

```bash
pip install --upgrade pip
pip install -r trading_bot/requirements.txt
```

Key packages installed:

| Package | Purpose |
|---|---|
| `PyQt6`, `pyqtgraph` | Desktop UI and real-time charts |
| `torch` | LSTM / Transformer neural networks (MPS on Apple Silicon) |
| `numpy`, `scipy`, `scikit-learn` | ML and statistics |
| `python-binance` | Binance REST + WebSocket client |
| `sqlalchemy`, `psycopg2-binary` | PostgreSQL ORM (SQLAlchemy 3.0-ready) |
| `redis` | Real-time caching |
| `flask` | Embedded REST API server |
| `loguru` | Structured logging |
| `cryptography` | AES-256-GCM config encryption |
| `pydantic`, `pydantic-settings` | Typed configuration models |
| `pandas`, `optuna` | Data analysis and hyperparameter optimisation |
| `web3` | Optional — on-chain gas fee estimation |

### 2.4 Optional: Install PostgreSQL and Redis

PostgreSQL and Redis are **optional**. The application runs in offline/demo mode without them.

**Ubuntu:**
```bash
sudo apt install postgresql redis-server
sudo systemctl start postgresql redis-server
sudo -u postgres createuser --superuser binanceml
sudo -u postgres createdb binanceml
```

**macOS (Homebrew):**
```bash
brew install postgresql@16 redis
brew services start postgresql@16 redis
createdb binanceml
```

### 2.5 Start the Application

```bash
cd demo
python trading_bot/main.py
```

On first launch the **Setup Wizard** opens automatically.

---

## 3. First-Run Setup Wizard

The Setup Wizard guides you through initial configuration:

1. **Binance API Keys**
   - Create keys at: Binance → Account → API Management
   - Required permissions: **Read Info**, **Enable Spot & Margin Trading**
   - Do **not** enable withdrawals
   - Tick **Testnet** if you want to start in paper-trading mode

2. **Trading Mode**
   - **Paper Trading** — simulates orders with no real money (recommended to start)
   - **Live Trading** — places real orders on Binance

3. **Risk Settings**
   - Maximum daily loss limit (default: 2% of portfolio)
   - Maximum position size (default: 5% per trade)
   - Circuit-breaker drawdown threshold (default: 5%)

4. **Database** — optionally enter PostgreSQL connection details.
   If left blank the application uses SQLite as a fallback.

5. **AI Provider** — optionally enter a Claude / OpenAI / Gemini API key
   for enhanced sentiment analysis and reasoning.

6. **Complete** — saves encrypted config to `~/.binanceml/config.enc`

---

## 4. Application Overview

### Navigation

The left sidebar contains navigation buttons:

| Button | Page | Shortcut |
|--------|------|----------|
| TRADE | Trading Panel | Ctrl+1 |
| AT | AutoTrader | Ctrl+2 |
| ML | ML Training | Ctrl+3 |
| RISK | Risk Dashboard | Ctrl+4 |
| BT | Backtesting | Ctrl+5 |
| JNL | Trade Journal | Ctrl+6 |
| STRAT | Strategy Builder | Ctrl+7 |
| CONN | Connections | Ctrl+8 |
| SET | Settings | Ctrl+9 |
| HELP | Help | F1 |
| SIM | Simulation | Ctrl+Shift+S |

Hover any nav button for **5 seconds** to see a tooltip.
Hover for **10 seconds** to open contextual help for that panel.

### Intel Log

The dockable Intel Log at the bottom of the screen shows real-time
system events, trade signals, ML decisions, and alerts.
Toggle it with **Ctrl+L**.

### Status Bar

The bottom status bar shows live indicators — **click any indicator** to open the
System Status Dashboard:

| Indicator | Description |
|-----------|-------------|
| **Network: ONLINE / OFFLINE** | Internet connectivity (checked every 15 s) |
| **DB: ONLINE / OFFLINE** | PostgreSQL connection |
| **Redis: ONLINE / OFFLINE** | Redis connection |
| **API: ACTIVE / DOWN** | Binance REST API status |
| **P/L: +£12.34** | Today's realised profit/loss (GBP) |
| Trading mode | PAPER / LIVE / AUTO / HYBRID |
| AutoTrader state | SCANNING / IDLE / PAUSED |
| CPU usage | System CPU % |

### System Status Dashboard

**Shortcut:** `Ctrl+Shift+D` · Also accessible via **Setup → System → Status/Health**
or by clicking any status indicator in the bottom bar.

Displays 60-second rolling Grafana-style area charts for:

| Panel | Metric |
|-------|--------|
| CPU % | System CPU utilisation, sampled every second |
| MEM % | System memory utilisation |
| DB Latency ms | PostgreSQL round-trip query time |
| Redis Latency ms | Redis PING round-trip time |
| NET TX KB/s | Network bytes sent per second |
| NET RX KB/s | Network bytes received per second |

A **DEX API Quota** panel shows:
- CoinGecko calls remaining this hour
- Codex calls remaining this hour
- DexCallScheduler cache warm slots (N/12)
- Emergency reserve slot available (Yes/No)

---

## 5. Trading Panel

**Navigate:** TRADE (Ctrl+1)

### Charts

- **Multi-tab layout** — open multiple symbols simultaneously
- **Chart styles** — Candlestick, OHLC Bar, Heikin-Ashi, Line, Area
- **Overlay indicators** — EMA 9/20/50/200, SMA 20/50, Bollinger Bands,
  VWAP ±1σ/±2σ, Ichimoku Cloud
- **Sub-panel oscillators** — Volume + OBV, RSI (14), MACD (12,26,9),
  Stochastic (14,3,3), ATR (14), ADX (14)
- **AI Forecast** — ML price projection cone for 5–100 bars ahead

### Order Entry

Order types supported:

| Type | Description |
|------|-------------|
| LIMIT | Specify price and quantity |
| MARKET | Fills immediately at best available price |
| STOP-LIMIT | Triggers a limit order when stop price is hit |
| OCO | One-Cancels-Other (limit + stop-limit pair) |

All orders include:
- **Stop Loss** — automatic loss limit
- **Take Profit** — automatic profit target
- **Position sizing** — auto-calculated from risk % of portfolio

### Active Orders Table

Shows all open orders with:
- Symbol, type, side, price, quantity, status
- One-click **Cancel** button per order
- Binance order ID for reference

### Daily P&L Chart

The bottom-right chart shows daily realised P&L as green (profit) or red (loss) bars,
updated on every refresh cycle.

---

## 6. Chart Features

### Trade Markers (Yellow Squares)

When the **TRADES** pill is toggled on in the chart toolbar:
- Yellow squares appear at every trade entry and exit
- Entry squares have a **yellow border**
- Exit squares have a **green border** (profit) or **red border** (loss)
- A **yellow dotted line** connects each matched entry→exit pair

**Hovering** over a trade square shows a detailed tooltip:

```
  ENTRY  ─  A1B2C3D4
  Side:    BUY
  Entry:   65,000.0000  @  2025-01-05 12:34 UTC
  Qty:     0.001000 BTC
  Exit:    66,500.0000  @  2025-01-05 13:45 UTC
  Held:    1h 11m
  Gross:   +$1.50  (+2.31%)
  Fees:    -$0.13  (2 × 0.1%)
  Tax:     -$0.27  (UK CGT 20%)
  Net:     +$1.10
```

### Chart Navigation Controls (Toolbar Row 3)

| Button | Action |
|--------|--------|
| ◀◀ | Pan far left (80% of view) |
| ◀ | Pan left (20% of view) |
| ▶ | Pan right (20% of view) |
| ▶▶ | Pan far right (80% of view) |
| − Zoom | Zoom out (view 70% wider) |
| + Zoom | Zoom in (view 70% narrower) |
| Fit | Auto-fit all data in view |
| Auto-Scale ✓ | Toggle Y-axis auto-scaling |
| Auto-Follow ✓ | Toggle auto-scroll to latest candle |

**Mouse controls:**
- Scroll wheel — zoom in/out
- Click + drag — pan
- Right-click → View All — fit view

### AI Forecast Overlay

Toggle the **AI FORECAST** pill to show an ML price projection:
- Choose horizon: 5b / 10b / 20b / 50b / 100b bars ahead
- Cone width represents uncertainty (wider = less certain)
- Green cone = bullish signal · Red cone = bearish
- **ACC badge** shows historical forecast accuracy for this symbol + interval

---

## 7. AutoTrader Panel

**Navigate:** AT (Ctrl+2)

The AutoTrader automates the full scan → analyse → enter → monitor → exit cycle.

### Modes

| Mode | Behaviour |
|------|-----------|
| **SEMI\_AUTO** | Recommends trades; press **Take Aim** to confirm |
| **FULL\_AUTO** | Executes automatically when confidence ≥ threshold |
| **PAUSED** | Monitoring only, no new trades |

### Tabs

| Tab | Content |
|-----|---------|
| **Pairs** | Pair scanner results and tradability scores |
| **Trend** | Multi-timeframe trend scanner (15m → 30d) |
| **Accumulation** | Stealth accumulation detector results |
| **Liquidity** | Order-book depth grades per pair |
| **Breakouts** | Volume breakout stage tracker |
| **Arbitrage** | Statistical + triangular arb opportunities |
| **Ping-Pong** | Range trader controls and status |
| **Strategies** | ML strategy selector and override |

### Top Opportunities Table

Displays the top 5 profit and top 5 R:R opportunities from the market scanner,
updated every 5 minutes.

### Signal Quality Indicators

The AutoTrader uses multiple signal sources:
- **LSTM Predictor** — recurrent neural network on OHLCV sequences
- **Token ML** — per-symbol fine-tuned models
- **Ensemble Aggregator** — votes weighted by historical accuracy
- **Regime Detector** — adjusts strategy to market conditions
- **MTF Confluence** — multi-timeframe confirmation (1h / 4h / 1d)
- **Signal Council** — final deliberation (veto power)
- **Whale Watcher** — large-order flow detection
- **Sentiment Analyser** — news/social media scoring

---

## 8. Ping-Pong Range Trader

**Activate:** AutoTrader panel → **Ping-Pong** tab

### How It Works

1. Detects a ranging market using Bollinger Bands (20-bar, 2σ) + Donchian Channel
2. Calculates range high and low
3. **Buy Zone** — bottom 25% of the range
4. **Sell Zone** — top 25% of the range
5. Opens BUY when price enters Buy Zone; closes and opens SELL when price
   reaches Sell Zone (and vice versa)
6. Automatically **suspends** if the regime detector classifies the market as
   TRENDING (strong directional move)

### Consecutive Loss Protection

After **3 consecutive losses** the Ping-Pong trader pauses for **10 bars**
to avoid trading a broken range.

### Controls

| Control | Description |
|---------|-------------|
| Symbol | Which crypto to trade |
| Risk % | Position size as % of portfolio |
| Start | Begin scanning and trading |
| Stop | Halt new entries |
| Close Active | Immediately close the current open trade |

### Status Indicators

- **Range bar** — coloured progress bar showing price position within range
  - Green = in Buy Zone · Amber = middle of range · Red = in Sell Zone
- **Regime** — current market regime (RANGING / TRENDING / VOLATILE)
- **Consecutive Losses** — count since last reset

---

## 9. ML Strategy Selector

**Activate:** AutoTrader panel → **Strategies** tab

The ML Strategy Selector automatically chooses the best-performing trading
strategy for current market conditions.

### Available Strategies

| Strategy | Best Regime | Description |
|----------|-------------|-------------|
| trend\_follow | TRENDING | EMA crossover + MACD momentum |
| mean\_revert | RANGING | Buy dips, sell rallies in a range |
| ping\_pong | RANGING / VOLATILE | Tight buy/sell between channel bounds |
| momentum | VOLATILE / TRENDING | Breakout + volume confirmation |
| sentiment | ANY | News/social sentiment-driven trades |
| ml\_pure | ANY | Pure ML ensemble signal, no overlay |

### Scoring Formula

Every 60 seconds the selector scores each strategy:

```
score = regime_fit × 0.40
      + win_rate   × 0.30
      + avg_rr     × 0.20   (capped at 3:1)
      + momentum   × 0.10   (last 10 trades)
```

The highest-scoring strategy becomes the **Active Strategy**.

### Manual Override

Tick **Override auto-selection** and pick a strategy from the dropdown to
force a specific strategy regardless of ML scoring.

Click **⟳ Force Re-Evaluate Now** to trigger an immediate scoring cycle.

---

## 10. Arbitrage Detector & Auto-Trader

**Activate:** AutoTrader panel → **Arbitrage** tab

### Strategy Types

#### Statistical Arbitrage

Two assets that normally move together (cointegrated) have temporarily
diverged. The engine:

1. Computes a rolling **hedge ratio (β)** via OLS regression
2. Measures how far the current spread is from its mean (z-score)
3. When `|z| ≥ 2.0` — opens a position (BUY underpriced leg, SELL overpriced leg)
4. When `|z| ≤ 0.5` — closes position (spread has reverted — profit taken)
5. Emergency close if `|z| ≥ 3.8` (spread still widening — stop loss)

Default monitored pairs: BTC/ETH · BTC/BNB · ETH/BNB · SOL/AVAX · XRP/ADA · DOGE/SHIB

#### Triangular Arbitrage

Exploits price inconsistencies between three currency pairs.
Example: BTC → ETH → BNB → BTC. If this round-trip returns > 100% + fees, a signal is emitted.

#### DEX↔CEX Spread Arbitrage

Detects price divergences between on-chain DEX pools and Binance (CEX).
Requires CoinGecko DEX API to be active. Uses a **zero-extra-call** approach:

1. CoinGecko pool prices are read from the DexCallScheduler's cache
2. Compared to the live Binance CEX price
3. Spreads > 0.3% and confidence > 0.55 are flagged as opportunities
4. High-confidence opportunities (> 0.8 confidence, > 0.5% spread) trigger:
   - **0x price validation** — confirms the spread is real and executable
     (boosts confidence if confirmed, discounts if 0x price is tighter)
   - **Codex emergency call** — fetches pool liquidity depth (only fired after 0x confirms)

Networks monitored: Ethereum, BSC, Polygon, Arbitrum (when pools are cached by the scheduler)

### Opportunity Score

```
score = z_magnitude   × 0.35
      + cointegration × 0.30   (half-life of mean reversion)
      + net_profit    × 0.20   (after 0.1% Binance fees per leg)
      + confidence    × 0.15   (pair historical win rate)
```

Only opportunities with `score ≥ 0.50` and `confidence ≥ 0.55` are shown.

**Arbitrage types** (`arb_type` field):

| Type | Description |
|------|-------------|
| `STAT` | Statistical arbitrage — cointegrated CEX pairs |
| `TRIANGULAR` | Three-leg currency loop on Binance |
| `DEX_CEX_SPREAD` | On-chain DEX pool vs Binance CEX price divergence |

### Controls

| Control | Description |
|---------|-------------|
| Auto-Trade | Automatically execute opportunities when found |
| Paper Mode | Simulate trades without real orders (default: ON) |
| Budget (USDT) | Amount allocated per arb leg (default: $100) |
| Min score | Filter: only show opportunities above this score |
| Add pair | Add a custom pair to the scanner |

### Safety Rules

- Maximum **1 position per pair** at any time
- Hard stop if spread z-score reaches **3.8**
- Force-close any position open longer than **1 hour**
- Paper mode is enabled by default

---

## 11. ML Training Panel

**Navigate:** ML (Ctrl+3)

### Model Types

| Model | Description |
|-------|-------------|
| **LSTM Predictor** | Long Short-Term Memory network trained on OHLCV sequences (30-bar lookback) |
| **Transformer** | Attention-based model for pattern recognition |
| **Per-Token Models** | Individual fine-tuned models for each trading pair |

### Training Controls

| Button | Action |
|--------|--------|
| Start 48h Training | Runs a full training session in the background |
| Stop | Halts training after current epoch |
| Evaluate Model | Runs test-set evaluation and shows accuracy |

### Training Phases

| Phase | What Happens |
|-------|-------------|
| 1 — Archive | Downloads up to 1 year of 1m/5m/15m/1h/4h candles for top 100 USDT pairs |
| 2 — Feature Engineering | Computes 18+ indicators: RSI, MACD, ATR, BB, OBV, VWAP, etc. |
| 2b — DEX Features | Injects on-chain features when CoinGecko API is active (see below) |
| 3 — LSTM Training | Trains LSTM + Transformer with Optuna HPO · Apple Silicon MPS acceleration |
| 4 — Per-Token | Fine-tunes individual models for each active trading pair |

### DEX On-Chain ML Features

When CoinGecko DEX API is configured and active, four additional features are injected
into each training row automatically (log-normalised, filled with 0 when API is inactive):

| Feature | Description |
|---------|-------------|
| `dex_volume_24h_usd_norm` | Log-normalised 24h on-chain trading volume |
| `dex_liquidity_usd_norm` | Log-normalised pool total liquidity |
| `dex_vol_liq_ratio` | Volume ÷ Liquidity ratio (liquidity utilisation rate) |
| `dex_pool_count_top5` | Number of qualifying top-5 pools for this token |

These features help the model distinguish tokens with deep DEX liquidity from
thin markets prone to manipulation.

### Continuous Learning

The **Continuous Learner** automatically retrains models every 24 hours using
the latest market data. A **data integrity check** runs every 25 minutes —
detecting gaps, OHLC violations, and stale data.

### Signal Stream

The live signal feed shows:
- **Source** — which model emitted the signal (LSTM, TokenML, Whale, Ensemble…)
- **Symbol** — trading pair
- **Signal** — BUY / SELL / HOLD
- **Confidence** — 0.0 to 1.0
- **Regime** — market conditions at signal time

### Whale Watcher

Large order detection monitors the Binance order book for:
- Block buy/sell orders above threshold USD value
- Volume spikes > 3σ above rolling average
- Smart money accumulation / distribution patterns

---

## 12. Risk Dashboard

**Navigate:** RISK (Ctrl+4)

### Circuit Breaker

Automatically halts all trading if daily drawdown exceeds threshold (default: 5%).
- Resets at UTC midnight
- Manual override available in Settings

### Position Sizing

Kelly Criterion-based position sizing:

```
size = (win_rate × avg_win − loss_rate × avg_loss) / avg_win
```

Capped at the maximum position size setting (default: 5% of portfolio).

### Monte Carlo Simulation

Runs 1,000 simulated portfolio paths based on historical trade statistics:
- Expected portfolio value range at 30 / 60 / 90 days
- 5th percentile (worst case) and 95th percentile (best case)
- Probability of reaching target return

### Walk-Forward Validation

Tests ML model performance on unseen data using rolling 30-day windows.
Shows actual vs expected accuracy to detect model overfitting.

### Regime Detector

Classifies current market regime every 60 seconds:

| Regime | Meaning |
|--------|---------|
| **TRENDING\_UP** | Strong upward momentum |
| **TRENDING\_DOWN** | Strong downward momentum |
| **RANGING** | Price bouncing within a range |
| **VOLATILE** | High volatility, no clear direction |
| **UNKNOWN** | Insufficient data |

---

## 13. Trade Journal

**Navigate:** JNL (Ctrl+6)

### Overview Stats

The top bar shows:
- Trades today / total · P&L today / total
- Win rate (all time) · Average trade duration
- Open positions count

### Open Trades Table

Shows all currently open positions:
- Entry price, current P&L, stop loss, take profit
- Time open, strategy used, ML confidence at entry

### Closed Trades Table

Full history of completed trades:
- Entry and exit prices and times
- Gross P&L, net P&L (after fees and tax)
- Exit reason (SL / TP / Signal / Manual)
- Market regime at time of trade
- Signal Council decision

### Signal Attribution

Shows win rate per ML signal source — which models predicted correctly.
Results feed back to auto-adjust ensemble weights.

### Export

Click **Export CSV** to download trade history for external analysis
or HMRC tax reporting.

---

## 14. Backtesting Engine

**Navigate:** BT (Ctrl+5)

### Configuration

| Setting | Description |
|---------|-------------|
| Symbol | Trading pair to test |
| Interval | Candle timeframe (1m to 1w) |
| Start date | Backtest period start |
| End date | Backtest period end |
| Capital | Starting portfolio value (USD) |
| Strategy | ML model or rule-based strategy |

### Running a Backtest

1. Select settings
2. Click **Run Backtest**
3. Progress bar shows download + simulation progress
4. Results appear automatically when complete

### Results

- **Equity curve** — portfolio value over time with drawdown overlay
- **Performance stats** — total return, CAGR, Sharpe ratio, max drawdown
- **Trade log** — every simulated trade with full context
- **Win rate analysis** — wins vs losses by direction, time of day, regime

---

## 15. Connections & Health

**Navigate:** CONN (Ctrl+8)

Shows live health status for all external dependencies:

| Service | Indicators |
|---------|-----------|
| Binance REST API | Ping latency, last successful call |
| Binance WebSocket | Connected / Reconnecting, message count |
| PostgreSQL | Connected, query latency |
| Redis | Connected, ping latency |
| REST API Server | Port, uptime |

Click **Check All** to force an immediate health check. Auto-checks run every **30 seconds**.

---

## 16. On-Chain Data APIs

Configure under **Settings (Ctrl+9) → On-Chain** tab.

### 16.0.1 MetaMask Live Data

Polls an EVM wallet address using **free public JSON-RPC endpoints** — no API key required.
Runs as a background thread updating every 30 seconds.

| Setting | Description |
|---------|-------------|
| Wallet address | Your 0x… EVM address |
| Network | ethereum / bsc / polygon / arbitrum / optimism / base |
| Poll interval | Seconds between polls (default: 30) |

Data collected each poll: native balance (ETH/BNB/MATIC), ERC-20 token balances
(USDT/USDC/WBTC/DAI/LINK/UNI/AAVE/WETH), gas price, block number, transaction count.

USD values are sourced from the live Binance price feed (no additional API calls).

### 16.0.2 CoinGecko DEX API v3

| Setting | Default | Description |
|---------|---------|-------------|
| API key | — | Free key from https://dashboard.coingecko.com |
| Plan | Demo | Demo / Analyst / Lite / Pro / Enterprise |
| Networks | eth, bsc, polygon_pos, arbitrum | Chains to monitor |
| Base URL | https://api.coingecko.com/api/v3 | Override for self-hosted |
| Timeout | 10 s | Per-request timeout |
| Enabled | Off | Master toggle |

**Budget calculation:** monthly quota ÷ days\_in\_month ÷ 24 = hourly budget.
A 12-slot hourly call plan runs in the background scheduler. One emergency
reservation slot is kept for high-confidence arbitrage confirmation.

**Free tier (Demo plan): 10,000 calls/month → ~13 calls/hr → 12 scheduled + 1 emergency.**

### 16.0.3 Codex GraphQL API

| Setting | Default | Description |
|---------|---------|-------------|
| API key | — | Free key from https://www.codex.io |
| Base URL | https://graph.codex.io/graphql | GraphQL endpoint |
| Enabled | Off | Master toggle |

**Free tier: ~500 calls/month → ~0.69 calls/hr (~1 call per 87 minutes).**
Used exclusively as an emergency confirmation gate — fires only after 0x
validates a high-confidence DEX_CEX_SPREAD opportunity.

### 16.0.4 0x Protocol Swap API v2

| Setting | Default | Description |
|---------|---------|-------------|
| API key | — | Free key from https://dashboard.0x.org |
| Plan | Free | Free / Standard / Custom |
| Chain | ethereum | Default chain for price queries |
| Base URL | https://api.0x.org | API base |
| Enabled | Off | Master toggle |

**Free tier: 1 req/s rate limit.** The arbitrage detector throttles to
1 call per 30 s per symbol, leaving ample headroom for other uses.

Supported chains: Ethereum · BSC · Polygon · Arbitrum · Optimism · Base

---

## 17. Settings & Layer Configuration

**Navigate:** SET (Ctrl+9)

### 17.1 API Keys

```
Binance API Key:    [your API key]
Binance Secret:     [your API secret]
□ Use Testnet       (paper trading on testnet.binance.vision)
```

**Never share your API secret.** Keys are stored AES-256-GCM encrypted on disk.

### 17.2 Trading Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Max daily loss | 2% | Circuit-breaker threshold |
| Max position size | 5% | Per-trade maximum as % of portfolio |
| Execution mode | SEMI\_AUTO | Autonomy level |
| Confidence threshold | 0.72 | Minimum confidence to auto-execute |
| Cooldown after SL | 15 min | Pause after a stop-loss hit |
| Order type | LIMIT | Default order type (LIMIT / MARKET) |

### 17.3 ML Settings

| Setting | Default | Description |
|---------|---------|-------------|
| LSTM lookback window | 60 | Input candles for LSTM |
| LSTM layers | 3 | Network depth |
| Learning rate | 0.001 | Training speed |
| Retrain interval | 24 h | Continuous learner frequency |
| Training hours | 48 | Full training session duration |
| Confidence threshold | 0.72 | Minimum to emit a signal |
| Top tokens | 100 | Pairs to include in training |

### 17.4 Tax Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Tax year start | 6 April | UK tax year |
| CGT rate (basic) | 10% | Capital gains rate for basic rate taxpayers |
| CGT rate (higher) | 20% | Capital gains rate for higher rate taxpayers |
| Annual exempt amount | £3,000 | CGT annual allowance (2024/25) |
| Report currency | GBP | Currency for HMRC reports |
| Email reports | On | Email monthly PDF on the 1st |

### 17.5 UI Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Theme | Dark | Dark / Light |
| Accent colour | Cyan `#00D4FF` | Highlight colour |
| Font size | 13 px | Base font size |
| Default interval | 1m | Default chart timeframe |
| Chart candle count | 200 | Visible candles on chart |

### 17.6 Layer Configuration Panel

Navigate to **Settings (Ctrl+9)** → **🧩 Layers** tab,
or use **Simulation > ⚙ Layer Settings** in the menu bar.

Each of the 10 layers has its own tab with controls for every module.

**Layer keyboard shortcuts:**

| Shortcut | Layer |
|----------|-------|
| `Shift+Alt+1` | Layer 1 – Infrastructure & Orchestration |
| `Shift+Alt+2` | Layer 2 – Market Data Ingestion |
| `Shift+Alt+3` | Layer 3 – Data Engineering & Storage |
| `Shift+Alt+4` | Layer 4 – Research & Quant |
| `Shift+Alt+5` | Layer 5 – Alpha & Signal |
| `Shift+Alt+6` | Layer 6 – Risk & Capital Management |
| `Shift+Alt+7` | Layer 7 – Execution |
| `Shift+Alt+8` | Layer 8 – Token & Contract Safety |
| `Shift+Alt+9` | Layer 9 – Monitoring & Reporting |
| `Shift+Alt+0` | Layer 10 – Governance & Oversight |

**Module controls** per panel:
- **Enabled toggle** — turn any module on/off without restart
- **Parameter sliders** — tune thresholds, periods, limits live
- **API key fields** — enter credentials securely (masked)
- **Dependency notification** — auto-activates required dependencies
  and shows *"⚡ Auto-activated: module\_name"*

---

## 18. Simulation Panel

**Navigate:** Simulation menu (`Ctrl+Shift+S`) or nav sidebar **SIM**

### 17.1 Live Simulation Twin (`Ctrl+Shift+T`)

A shadow engine running beside production — every live decision is replayed
across 6 parallel variants:

| Variant | Behaviour |
|---------|-----------|
| **size\_half** | Half position size |
| **size\_2x** | Double position size |
| **delayed\_5m** | Entry delayed 5 minutes |
| **tighter\_stop** | Stop loss 50% tighter |
| **wider\_stop** | Stop loss 50% wider |
| **skip** | Trade skipped entirely |

**Drift detection** alerts when live accuracy deviates from backtested baseline:
- **Minor drift** — > 5% deviation (monitor closely)
- **Severe drift** — > 15% deviation (model retraining recommended)

The **variant leaderboard** shows which alternative consistently beats live.

### 17.2 Strategy Mutation Lab (`Ctrl+Shift+M`)

Automated genetic evolution of strategy parameters:

| Stage | Description |
|-------|-------------|
| **Initialise** | Seed population from current strategy parameters |
| **Evaluate** | Backtest + walk-forward + regime stability in parallel |
| **Gate** | Hard reject: Sharpe < 0.5 OR drawdown > 20% OR < 30 trades |
| **Select** | Tournament selection from passed variants |
| **Breed** | Crossover + mutation of surviving parameter sets |
| **Promote** | Auto-register champions (fitness ≥ 0.65, regime stability ≥ 0.7) |

Configuration: population 5–100 · mutation rate 5–50% · max drawdown gate 5–50%

### 17.3 Safety Scanner (`Ctrl+Shift+F`)

Token & contract safety analysis for new token launches:

| Module | What It Checks |
|--------|----------------|
| **Contract Analyzer** | Mint authority, blacklist function, pausability, fee mutability |
| **Honeypot Detector** | Simulates buy + sell to confirm token is sellable |
| **Liquidity Lock** | Lock percentage, duration, verified locker contract |
| **Wallet Graph** | Deployer relationships, fresh wallets, multi-deployer patterns |
| **Rug-Pull Scorer** | Composite 0–100% probability with risk classification |

**Risk levels:**
- 🟢 Low (0–20%) — proceed with normal caution
- 🟡 Medium (20–45%) — reduce position size
- 🔴 High (45–70%) — avoid
- 💀 Critical (70–100%) — do not trade

---

## 19. REST API Reference

The embedded REST API starts automatically on `http://127.0.0.1:8765`.

All endpoints except `/health` require:

```
Authorization: Bearer <api_key_prefix>
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health — no auth required |
| GET | `/api/v1/status` | System status, engine mode, uptime |
| GET | `/api/v1/portfolio` | Portfolio snapshot (USDT + GBP values, per-asset breakdown) |
| GET | `/api/v1/signals` | Latest ML signals from all sources |
| GET | `/api/v1/trades` | Recent trades (`?limit=50&symbol=BTCUSDT`) |
| GET | `/api/v1/orderbook/{symbol}` | Live L1/L2 order book |
| GET | `/api/v1/ticker/{symbol}` | Live ticker (price, 24h change, volume) |
| POST | `/api/v1/order` | Place a limit order |
| DELETE | `/api/v1/order/{id}` | Cancel an open order |
| GET | `/api/v1/ml/status` | ML training status, model version, accuracy |
| POST | `/api/v1/ml/predict` | On-demand prediction for a symbol |
| GET | `/api/v1/tax/monthly` | Monthly CGT tax summary |
| GET | `/api/v1/log` | Recent Intel Log entries (`?limit=100`) |
| POST | `/api/v1/webhook/register` | Register a webhook endpoint |

### Example Requests

```bash
# Health check
curl http://localhost:8765/health

# Portfolio (GBP + USDT)
curl -H "Authorization: Bearer mytoken123" \
     http://localhost:8765/api/v1/portfolio

# Place a BTCUSDT limit buy
curl -X POST http://localhost:8765/api/v1/order \
  -H "Authorization: Bearer mytoken123" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"BUY","quantity":0.001,"price":65000}'

# On-demand ML prediction
curl -X POST http://localhost:8765/api/v1/ml/predict \
  -H "Authorization: Bearer mytoken123" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"ETHUSDT"}'

# Register webhook for all trade events
curl -X POST http://localhost:8765/api/v1/webhook/register \
  -H "Authorization: Bearer mytoken123" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://your-app.com/hook","events":["TRADE","SIGNAL","ERROR"]}'
```

### Webhook Payload (example)

```json
{
  "event": "TRADE",
  "timestamp": 1735900800.123,
  "data": {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "price": 65000,
    "quantity": 0.001,
    "status": "FILLED",
    "is_automated": true,
    "ml_signal": "BUY",
    "ml_confidence": 0.84
  }
}
```

---

## 20. UK Tax (CGT) Reporting

BinanceML Pro calculates UK Capital Gains Tax using HMRC rules:

### Matching Rules (applied in this order)

1. **Same-Day Rule** — if you buy and sell the same asset on the same day,
   those are matched against each other first.

2. **Bed-and-Breakfast Rule** — if you buy within 30 days after a sale,
   that purchase is matched to the sale (not the pool) to prevent tax avoidance.

3. **Section 104 Pool** — remaining acquisitions and disposals are pooled.
   The pool maintains a running average cost basis per asset.

### CGT Allowance (2024/25 onwards)

| Rate | Threshold |
|------|-----------|
| Annual exempt amount | £3,000 |
| Basic rate (gains within basic-rate band) | 10% |
| Higher/additional rate | 20% |

*The application defaults to 20% — adjust in Settings → Tax for your situation.*

### Reports

The Trade Journal generates:
- **Gain/Loss Summary** — per-disposal breakdown with cost basis shown
- **Annual Report** — total gains/losses for the full tax year
- **Section 104 Pool Statement** — running pool balance per asset

Reports are exported to CSV for use with HMRC's online Self Assessment.
Monthly PDF summaries can be emailed automatically on the 1st of each month.

### HMRC Filing

The annual CGT summary is designed to match the format required for
HMRC's Self Assessment (SA100 / SA108 forms). Consult a tax adviser
for your specific situation.

---

## 21. Keyboard Shortcuts

### Navigation

| Shortcut | Action |
|----------|--------|
| `Ctrl+1` | Trading Panel |
| `Ctrl+2` | AutoTrader |
| `Ctrl+3` | ML Training |
| `Ctrl+4` | Risk Dashboard |
| `Ctrl+5` | Backtesting |
| `Ctrl+6` | Trade Journal |
| `Ctrl+7` | Strategy Builder |
| `Ctrl+8` | Connections |
| `Ctrl+9` | Settings |
| `F1` | Help |
| `Ctrl+Shift+S` | Simulation Panel |
| `Ctrl+Shift+D` | System Status Dashboard |
| `Ctrl+L` | Toggle Intel Log dock |
| `Ctrl+B` | Toggle Order Book dock |

### Trading

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+B` | Market BUY current symbol |
| `Ctrl+Shift+X` | Cancel ALL open orders |
| `Ctrl+Shift+E` | Manual Exit (AutoTrader) |
| `Ctrl+Shift+A` | Take Aim — confirm recommended trade |
| `Ctrl+Shift+N` | Scan market now |

### ML & Data

| Shortcut | Action |
|----------|--------|
| `Ctrl+T` | Start ML training session |
| `Ctrl+Shift+T` | Stop ML training |
| `Ctrl+R` | Reload ML model |
| `Ctrl+I` | Run data integrity check |

### Simulation

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+T` | Open Simulation Twin tab |
| `Ctrl+Shift+M` | Open Mutation Lab tab |
| `Ctrl+Shift+F` | Open Safety Scanner tab |

### Layer Settings

| Shortcut | Layer |
|----------|-------|
| `Shift+Alt+1` | Layer 1 – Infrastructure |
| `Shift+Alt+2` | Layer 2 – Market Data |
| `Shift+Alt+3` | Layer 3 – Data Engineering |
| `Shift+Alt+4` | Layer 4 – Research & Quant |
| `Shift+Alt+5` | Layer 5 – Alpha & Signal |
| `Shift+Alt+6` | Layer 6 – Risk |
| `Shift+Alt+7` | Layer 7 – Execution |
| `Shift+Alt+8` | Layer 8 – Token Safety |
| `Shift+Alt+9` | Layer 9 – Monitoring |
| `Shift+Alt+0` | Layer 10 – Governance |

### Charts & Window

| Shortcut | Action |
|----------|--------|
| `Ctrl++` | Add chart tab |
| `Ctrl+W` | Close current chart tab |
| `Ctrl+Tab` | Next chart tab |
| `F11` | Toggle fullscreen |
| `Ctrl+,` | Open Settings |
| `Ctrl+Q` | Quit application |

---

## 22. Troubleshooting

### Application Won't Start

```bash
# Check Python version (must be 3.10+)
python3 --version

# Reinstall dependencies
pip install --upgrade -r trading_bot/requirements.txt

# Check PyQt6 is available
python -c "from PyQt6.QtWidgets import QApplication; print('PyQt6 OK')"

# Check torch
python -c "import torch; print('torch', torch.__version__)"
```

### "No module named X" Error

```bash
pip install <module_name>
# or
pip install -r trading_bot/requirements.txt
```

### Binance Connection Failed

1. Check API key permissions in Binance account settings
2. Verify the **Testnet** toggle matches your key type (testnet keys ≠ mainnet keys)
3. Check internet connectivity
4. Add your IP to the Binance IP whitelist, or disable IP restriction
5. Check the **Connections** panel for the specific error message

### PostgreSQL Not Available

The application runs without PostgreSQL (falls back to SQLite automatically).
To set up PostgreSQL:

```bash
# Create the database
sudo -u postgres createdb binanceml
# Then set DB host/port/name in Settings → Database
```

### Redis Not Available

Redis-backed features (real-time ticker cache, order-book cache) are disabled
automatically. The application continues to function without Redis.

### ML Model Not Loading

If no trained model exists, the predictor runs with uninitialised weights.
Go to **ML Training (Ctrl+3)** → **Start 48h Training** to build the initial model.

A training session requires at least 6 hours and 50 MB of downloaded historical data.

### Chart Not Updating

1. Check Binance WebSocket connection in the Connections panel
2. Try removing and re-adding the symbol
3. Restart the application

### GBP Values Look Wrong

Ensure the application has completed at least one portfolio refresh cycle
(30 seconds after startup). The GBP/USD rate is fetched live from
the `GBPUSDT` pair — before the first fetch it uses a default of £0.79 per USD.

### High CPU Usage

ML training and the continuous learner are CPU-intensive. To reduce load:
- Go to **ML Training** → **Stop** to halt background training temporarily
- In Settings → ML, increase the retrain interval (default: 24 h)
- Disable per-token model training in Layer 4 settings

### Config File Corruption

If the encrypted config is corrupted, delete it and restart:

```bash
rm ~/.binanceml/config.enc
python trading_bot/main.py    # Setup Wizard will open again
```

---

## 23. Architecture Overview — 10-Layer Stack

BinanceML Pro v2.0 implements a full institutional-grade trading stack
organised into 10 functional layers with 77 modules:

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1 – Infrastructure & Orchestration (Modules 1–6)         │
│  MasterOrchestrator · StrategyRegistry · SecretsManager         │
│  FeatureFlagController · ServiceHealthMonitor                   │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2 – Market Data Ingestion (Modules 7–18)                 │
│  ExchangeMDC · DEXMDC · OrderBookCollector · TradeTape          │
│  FundingBasis · OptionsVolSurface · OnChainTx · TokenMetadata   │
│  NewsEvents · SocialSentiment · DevActivity · MempoolCollector  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3 – Data Engineering & Storage (Modules 19–25)           │
│  TimeNormalizer · SymbolMapper · DataCleaner · FeatureStore     │
│  HistoricalArchive · RealtimeCache · DataQualityAuditor         │
├─────────────────────────────────────────────────────────────────┤
│  Layer 4 – Research & Quant (Modules 26–36)                     │
│  FactorResearch · RegimeDetector · Correlation · PortfolioOpt   │
│  WalkForward · MonteCarlo · Backtester · Scenario               │
│  StrategyEvolution · ModelTraining · ModelRegistry              │
├─────────────────────────────────────────────────────────────────┤
│  Layer 5 – Alpha & Signal (Modules 37–46)                       │
│  Momentum · MeanReversion · BasisCarry · Volatility · StatArb   │
│  OnChainSmartMoney · TokenLaunchSignal · Sentiment              │
│  EventDriven · EnsembleSignalCouncil                            │
├─────────────────────────────────────────────────────────────────┤
│  Layer 6 – Risk & Capital Management (Modules 47–54)            │
│  DynamicRisk · PositionSizing · ExposureEngine · DrawdownGuard  │
│  LiquidityRisk · CounterpartyRisk · TreasuryRisk · KillSwitch  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 7 – Execution (Modules 55–60)                            │
│  SmartOrderRouter · ExecutionAlgo · DEXRouter                   │
│  GasFeeEngine · MEVProtection · TradeReconciliation             │
├─────────────────────────────────────────────────────────────────┤
│  Layer 8 – Token & Contract Safety (Modules 61–65)              │
│  ContractAnalyzer · HoneypotDetector · LiquidityLockAnalyzer    │
│  WalletGraphAnalyzer · RugPullScorer                            │
├─────────────────────────────────────────────────────────────────┤
│  Layer 9 – Monitoring & Reporting (Modules 66–72)               │
│  PnLAttribution · ForecastTracker · TradeJournal · Alerting     │
│  Dashboard · ComplianceLog · PostMortemAnalyzer                 │
├─────────────────────────────────────────────────────────────────┤
│  Layer 10 – Governance & Oversight (Modules 73–77)              │
│  InvestmentCommittee · ResearchNotebook · ApprovalWorkflow      │
│  AccessControl · DisasterRecovery                               │
└─────────────────────────────────────────────────────────────────┘
              ↑
    Evolution Layer (above all layers)
    LiveSimulationTwin · StrategyMutationLab
```

### Data Flow

1. **Market Data** → ExchangeMDC / DEXMDC / MempoolCollector stream live data
2. **Data Engineering** → Time normalisation → Symbol mapping → Cleaning → Feature Store
3. **Research** → Regime detection → Factor research → Signal generation
4. **Signal Council** → Ensemble weighting → Conflict resolution → Final signal
5. **Risk** → Exposure check → Kelly position sizing → Drawdown guard → Kill switch check
6. **Execution** → Smart routing → Algo execution → MEV protection → Reconciliation
7. **Simulation Twin** → Shadows every decision → Drift detection → Variant comparison
8. **Governance** → Compliance log → Approval workflow → Access control

### Key Technical Properties

| Property | Detail |
|---|---|
| ORM compatibility | SQLAlchemy 2.0 `select()` API — ready for SQLAlchemy 3.0 |
| GBP conversion | Live GBPUSDT rate, correct USD→GBP multiplier (1/GBPUSDT ≈ 0.79) |
| Thread safety | Named locks on `_candle_cache`, `_open_trade_ids`, `_active_symbols` |
| Gas estimation | web3 RPC with graceful fallback to jittered default gwei values |
| Config | AES-256-GCM encrypted · PBKDF2 master key · 600 000 iterations |
| DEX scheduler | `DexCallScheduler` — 12-slot hourly plan + 1 emergency reserve |
| API budgeting | `ApiRateLimiter` — monthly quota ÷ days ÷ 24 = hourly token bucket |
| MetaMask live data | Free public JSON-RPC — no API key, no cost |
| 0x price validation | permit2/price endpoint · per-second rate limiter · 30 s per-symbol cooldown |
| Arbitrage types | STAT · TRIANGULAR · DEX_CEX_SPREAD (3 types) |

---

*BinanceML Pro is provided for educational and research purposes.
Trading cryptocurrencies involves significant financial risk.
Past performance does not guarantee future results.
Always start with Paper Trading mode and understand the risks before using real funds.*
