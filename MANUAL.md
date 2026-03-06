# BinanceML Pro — Installation, Setup & User Manual

**Version 1.0 · Professional AI Trading Platform for Binance**

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
16. [Settings](#16-settings)
17. [Keyboard Shortcuts](#17-keyboard-shortcuts)
18. [UK Tax (CGT) Reporting](#18-uk-tax-cgt-reporting)
19. [Troubleshooting](#19-troubleshooting)
20. [Architecture Overview](#20-architecture-overview)

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
python3 -m venv venv
source venv/bin/activate          # Linux / macOS
# venv\Scripts\activate.bat       # Windows
```

### 2.3 Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Key packages installed:
- `PyQt6` — desktop GUI framework
- `pyqtgraph` — real-time charting
- `numpy`, `scipy`, `scikit-learn` — ML and statistics
- `torch` — LSTM / Transformer neural networks
- `python-binance` — Binance REST + WebSocket client
- `loguru` — structured logging
- `redis`, `psycopg2-binary` — database clients
- `aiohttp` — async REST API server
- `cryptography` — config encryption
- `pandas`, `matplotlib` — data analysis

### 2.4 Optional: Install PostgreSQL and Redis

PostgreSQL and Redis are **optional**.  The application runs in offline/demo mode without them.

**Ubuntu:**
```bash
sudo apt install postgresql redis-server
sudo systemctl start postgresql redis-server
```

**macOS (Homebrew):**
```bash
brew install postgresql redis
brew services start postgresql redis
```

### 2.5 Start the Application

```bash
cd demo/trading_bot
python main.py
```

On first launch the Setup Wizard will open automatically.

---

## 3. First-Run Setup Wizard

The Setup Wizard guides you through initial configuration:

1. **Binance API Keys** — Enter your Binance API Key and Secret.
   - Create keys at: Binance → Account → API Management
   - Required permissions: **Read Info**, **Enable Spot & Margin Trading**
   - **Do not** enable withdrawals
   - Tick **Testnet** if you want to start in paper-trading mode

2. **Trading Mode** — Choose between:
   - **Paper Trading** — simulates orders without real money (recommended to start)
   - **Live Trading** — places real orders on Binance

3. **Risk Settings** — Configure:
   - Maximum daily loss limit (default: 2% of portfolio)
   - Maximum position size (default: 5% per trade)
   - Circuit-breaker drawdown threshold (default: 5%)

4. **Database** — Optionally enter PostgreSQL connection string.
   If left blank the application uses SQLite.

5. **Telegram Alerts** — Optional.  Enter your bot token and chat ID to
   receive trade alerts on your phone.

6. **Complete** — Saves encrypted config to `~/.binanceml_pro/config.enc`

---

## 4. Application Overview

### Navigation

The left sidebar contains 10 navigation buttons:

| Button | Page | Shortcut |
|--------|------|----------|
| TRADE | Trading Panel | Ctrl+1 |
| AT | AutoTrader | Ctrl+2 |
| ML | ML Training | Ctrl+3 |
| RISK | Risk Dashboard | Ctrl+4 |
| BT | Backtesting | Ctrl+5 |
| JNL | Trade Journal | Ctrl+6 |
| STRAT | Strategy Manager | Ctrl+7 |
| CONN | Connections | Ctrl+8 |
| SET | Settings | Ctrl+9 |
| HELP | Help | F1 |

Hover any nav button for **5 seconds** to see a tooltip.
Hover for **10 seconds** to see the full help popup for that panel.

### Intel Log

The dockable Intel Log at the bottom of the screen shows real-time
system events, trade signals, ML decisions, and alerts.
Toggle it with **Ctrl+L**.

### Status Bar

The bottom status bar shows:
- Trading mode (PAPER / LIVE)
- AutoTrader state
- Today's trade count and P&L
- API, database, and Redis health indicators
- CPU usage

---

## 5. Trading Panel

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
- **LIMIT** — specify price and quantity
- **MARKET** — fills immediately at best price
- **STOP-LIMIT** — triggers when stop price is hit
- **OCO** — One-Cancels-Other (limit + stop)

All orders include:
- **Stop Loss** — automatic loss limit
- **Take Profit** — automatic profit target
- **Position sizing** — auto-calculated from risk %

### Active Orders Table

Shows all open orders with:
- Symbol, type, side, price, quantity, status
- One-click **Cancel** button per order
- Binance order ID for reference

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

**Mouse controls also work:**
- Scroll wheel — zoom in/out
- Click + drag — pan
- Right-click → View All — fit view

### AI Forecast Overlay

Toggle the **AI FORECAST** pill to show an ML price projection:
- Choose horizon: 5b / 10b / 20b / 50b / 100b bars ahead
- Cone width represents uncertainty (wider = less certain)
- Green cone = bullish signal, Red cone = bearish
- **ACC badge** shows historical forecast accuracy for this symbol + interval

---

## 7. AutoTrader Panel

The AutoTrader automates the full scan → analyse → enter → monitor → exit cycle.

### Modes

| Mode | Behaviour |
|------|-----------|
| **SEMI_AUTO** | Recommends trades; press **Take Aim** to confirm |
| **FULL_AUTO** | Executes automatically when confidence ≥ threshold |
| **PAUSED** | Monitoring only, no new trades |

### Top Opportunities Table

Displays the top 5 profit and top 5 R:R opportunities from the market scanner,
updated every 5 minutes.

### Active Trade Panel

Shows currently open trades with:
- Entry price, current price, unrealised P&L
- Stop-loss and take-profit levels (green/red dotted reference lines)
- Time in trade

### Signal Quality Indicators

The AutoTrader uses multiple signal sources:
- **LSTM Predictor** — recurrent neural network on OHLCV data
- **Token ML** — per-symbol fine-tuned models
- **Ensemble Aggregator** — votes weighted by historical accuracy
- **Regime Detector** — adjusts strategy to market conditions
- **MTF Confluence** — multi-timeframe confirmation
- **Signal Council** — final deliberation (veto power)
- **Whale Watcher** — large-order flow detection
- **Sentiment Analyser** — news/social media scoring

---

## 8. Ping-Pong Range Trader

The Ping-Pong trader buys at the low and sells at the high of a ranging market.

**Activate:** AutoTrader panel → **Ping-Pong** tab

### How It Works

1. Detects a ranging market using Bollinger Bands (20-bar, 2σ) + Donchian Channel
2. Calculates range high and low
3. **Buy Zone** — bottom 25% of the range
4. **Sell Zone** — top 25% of the range
5. Opens BUY when price enters Buy Zone; closes BUY and opens SELL when price
   reaches Sell Zone (or vice versa)
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
  - Green = in Buy Zone
  - Amber = middle of range
  - Red = in Sell Zone
- **Regime** — current market regime (RANGING / TRENDING / VOLATILE)
- **Consecutive Losses** — count since last reset

---

## 9. ML Strategy Selector

The ML Strategy Selector automatically chooses the best-performing trading
strategy for current market conditions.

**Activate:** AutoTrader panel → **Strategies** tab

### Available Strategies

| Strategy | Best Regime | Description |
|----------|-------------|-------------|
| trend_follow | TRENDING | EMA crossover + MACD momentum |
| mean_revert | RANGING | Buy dips, sell rallies in a range |
| ping_pong | RANGING / VOLATILE | Tight buy/sell between channel bounds |
| momentum | VOLATILE / TRENDING | Breakout + volume confirmation |
| sentiment | ANY | News/social sentiment-driven trades |
| ml_pure | ANY | Pure ML ensemble signal, no overlay |

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

The arbitrage engine finds opportunities to simultaneously buy one asset and
sell another for a near-instant profit.

**Activate:** AutoTrader panel → **Arbitrage** tab

### Strategy Types

#### Statistical Arbitrage
Two assets that normally move together (cointegrated) have temporarily
diverged. The engine:
1. Computes a rolling **hedge ratio (β)** via OLS regression
2. Measures how far the current spread is from its mean (z-score)
3. When `|z| ≥ 2.0`: opens a position (BUY underpriced leg, SELL overpriced leg)
4. When `|z| ≤ 0.5`: closes position (spread has reverted — profit taken)
5. Emergency close if `|z| ≥ 3.8` (spread still widening — stop loss)

Default monitored pairs:
- BTC/ETH, BTC/BNB, ETH/BNB, SOL/AVAX, XRP/ADA, DOGE/SHIB

#### Triangular Arbitrage
Exploits price inconsistencies between three currency pairs.
Example: BTC → ETH → BNB → BTC
If this round-trip returns more than 100% + fees, a signal is emitted.

### Opportunity Score

Each opportunity is scored 0–1:

```
score = z_magnitude   × 0.35
      + cointegration × 0.30   (half-life of mean reversion)
      + net_profit    × 0.20   (after 0.1% Binance fees per leg)
      + confidence    × 0.15   (pair historical win rate)
```

Only opportunities with `score ≥ 0.50` and `confidence ≥ 0.55` are shown.

### Controls

| Control | Description |
|---------|-------------|
| Auto-Trade | Automatically execute opportunities when found |
| Paper Mode | Simulate trades without real orders (default: ON) |
| Budget (USDT) | Amount allocated per arb leg (default: $100) |
| Min score | Filter: only show opportunities above this score |
| Add pair | Add a custom pair to the scanner |

### Active Positions

The **Active Positions** tab shows:
- Both legs of each open arb trade
- Live unrealised P&L per leg
- Entry z-score and time held
- **Close Selected** / **Close ALL** buttons

### Pair Statistics

The **Pair Statistics** tab shows per-pair ML learning:
- Total trades, wins, losses
- Win rate (used to adjust confidence for future signals)
- Recent 10-trade win rate (faster adaptation)
- Cumulative P&L

### Safety Rules

- Maximum **1 position per pair** at any time
- Hard stop if spread z-score reaches **3.8** (runaway position)
- Force-close any position open longer than **1 hour**
- Paper mode is enabled by default — toggle to Live only when confident

---

## 11. ML Training Panel

The ML Training panel manages the neural network models that power price prediction.

**Navigate:** ML (Ctrl+3)

### Model Types

- **LSTM Predictor** — Long Short-Term Memory network trained on OHLCV sequences
- **Transformer** — Attention-based model for pattern recognition
- **Per-Token Models** — Individual fine-tuned models for each trading pair

### Training Controls

| Button | Action |
|--------|--------|
| Start 48h Training | Runs a full training session in background |
| Stop | Halts training after current epoch |
| Evaluate Model | Runs test set evaluation and shows accuracy |

### Continuous Learning

The **Continuous Learner** automatically retrains models every 24 hours using
the latest market data.  This keeps models adapted to changing conditions.

### Signal Stream

The live signal feed shows:
- **Source** — which model emitted the signal (LSTM, TokenML, Whale, etc.)
- **Symbol** — trading pair
- **Signal** — BUY / SELL / HOLD
- **Confidence** — 0.0 to 1.0
- **Regime** — market conditions at signal time

### Whale Watcher

Large order detection monitors the Binance order book for:
- Block buy/sell orders > threshold USD value
- Volume spikes > 3σ above average
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

Runs 1,000 simulated portfolio paths based on historical trade statistics.
Shows:
- Expected portfolio value range at 30/60/90 days
- 5th percentile (worst case) and 95th percentile (best case)
- Probability of reaching target return

### Walk-Forward Validation

Tests ML model performance on unseen data using rolling 30-day windows.
Shows actual vs expected accuracy to detect model overfitting.

### Regime Detector

Classifies current market regime every 60 seconds:
- **TRENDING_UP** — strong upward momentum
- **TRENDING_DOWN** — strong downward momentum
- **RANGING** — price bouncing within a range
- **VOLATILE** — high volatility, no clear direction
- **UNKNOWN** — insufficient data

---

## 13. Trade Journal

**Navigate:** JNL (Ctrl+6)

### Overview Stats

The top bar shows:
- Trades today / total
- P&L today / total
- Win rate (all time)
- Average trade duration
- Open positions count

### Open Trades Table

Shows all currently open positions:
- Entry price, current P&L, stop loss, take profit
- Time open, strategy used, ML confidence at entry

### Closed Trades Table

Full history of completed trades with:
- Entry and exit prices and times
- Gross P&L, net P&L (after fees and tax)
- Exit reason (SL / TP / Signal / Manual)
- Market regime at time of trade
- Signal Council decision

### Signal Attribution

Shows win rate per ML signal source:
- Which models predicted correctly
- Used to auto-adjust ensemble weights

### Export

Click **Export CSV** to download the trade history for external analysis
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

| Service | Status Indicators |
|---------|-------------------|
| Binance REST API | Ping latency, last successful call |
| Binance WebSocket | Connected / Reconnecting, message count |
| PostgreSQL | Connected, query latency |
| Redis | Connected, ping latency |
| Telegram Bot | Online / Offline |
| REST API Server | Port, uptime |

Click **Check All** to force an immediate health check.

Auto-checks run every **30 seconds**.

---

## 16. Settings

**Navigate:** SET (Ctrl+9)

### API Keys

```
Binance API Key:    [your API key]
Binance Secret:     [your API secret]
□ Use Testnet       (paper trading on testnet.binance.vision)
```

**Never share your API secret.**  Keys are stored encrypted on disk.

### Trading

| Setting | Default | Description |
|---------|---------|-------------|
| Max daily loss | 2% | Circuit-breaker threshold |
| Max position size | 5% | Per-trade maximum |
| Execution mode | SEMI_AUTO | Autonomy level |
| Confidence threshold | 0.70 | Minimum to auto-execute |
| Cooldown after SL | 15 min | Pause after stop-loss |

### ML

| Setting | Default | Description |
|---------|---------|-------------|
| LSTM sequence length | 60 | Input bars for LSTM |
| LSTM layers | 3 | Network depth |
| Learning rate | 0.001 | Training speed |
| Retrain interval | 24h | Continuous learner frequency |
| Training hours | 48 | Full training session duration |

### Tax

| Setting | Default | Description |
|---------|---------|-------------|
| Tax year start | April 6 | UK tax year |
| CGT rate | 20% | Capital gains tax rate |
| Annual exempt amount | £3,000 | CGT annual allowance |
| Report currency | GBP | Report currency for HMRC |

### UI

| Setting | Default | Description |
|---------|---------|-------------|
| Theme | Dark | Dark / Light |
| Accent colour | Cyan #00D4FF | Highlight colour |
| Font size | 13px | Base font size |

---

## 17. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+1 | Trading Panel |
| Ctrl+2 | AutoTrader |
| Ctrl+3 | ML Training |
| Ctrl+4 | Risk Dashboard |
| Ctrl+5 | Backtesting |
| Ctrl+6 | Trade Journal |
| Ctrl+7 | Strategy Manager |
| Ctrl+8 | Connections |
| Ctrl+9 | Settings |
| F1 | Help |
| Ctrl+L | Toggle Intel Log |
| Ctrl+, | Settings (alias) |
| Ctrl+N | New chart tab |
| Ctrl+W | Close chart tab |
| Ctrl+Q | Quit application |
| Ctrl+Space | Toggle AutoTrader |
| Escape | Close dialogs |

---

## 18. UK Tax (CGT) Reporting

BinanceML Pro calculates UK Capital Gains Tax using HMRC rules:

### Same-Day Rule
If you buy and sell the same asset on the same day, those are matched first.

### Bed-and-Breakfast Rule
Buy within 30 days of a sale → matched to that sale before the pool.

### Section 104 Pool
Remaining shares are pooled; average cost basis used for gains.

### Reports

The Trade Journal generates:
- **Gain/Loss Summary** — per-disposal breakdown with cost basis
- **Annual Report** — total gains/losses for the tax year
- **HMRC Section 104 Pool** — running pool balance per asset

Reports export to CSV for use with HMRC's online self-assessment.

### CGT Allowance (2025/26)

Annual CGT exempt amount: **£3,000**
Basic rate taxpayer: **10%** on gains within basic rate band
Higher rate taxpayer: **20%** on all gains

*The application defaults to 20% — adjust in Settings for your situation.*

---

## 19. Troubleshooting

### Application Won't Start

```bash
# Check Python version
python3 --version    # must be 3.10+

# Reinstall dependencies
pip install --upgrade -r requirements.txt

# Check for PyQt6
python -c "from PyQt6.QtWidgets import QApplication; print('OK')"
```

### "No module named X" Error

```bash
pip install <module_name>
```

### Binance Connection Failed

1. Check API key permissions in Binance account settings
2. Verify testnet toggle matches your key type
3. Check internet connectivity
4. Binance IP whitelisting: add your IP or disable IP restriction
5. Check **Connections** panel for specific error

### PostgreSQL Not Available

The application runs without PostgreSQL (uses SQLite instead).
To use PostgreSQL:
```bash
sudo -u postgres createdb binanceml_pro
# Then set DB URL in Settings
```

### Redis Not Available

Caching and Redis-backed features are disabled automatically.
The application continues to function without Redis.

### ML Model Not Loading

If no trained model exists, the predictor runs with default weights.
Go to **ML Training** → **Start 48h Training** to build the initial model.

### Chart Not Updating

1. Check Binance WebSocket connection in Connections panel
2. Try changing symbol and back
3. Restart the application

### High CPU Usage

The ML training and continuous learner are CPU-intensive.
Go to **ML Training** → **Stop** to halt background training temporarily.

---

## 20. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    PyQt6 UI Layer                        │
│  MainWindow → TradingPanel, AutoTrader, MLPage, Risk    │
│              Chart, PingPong, Strategy, Arbitrage, etc. │
└─────────────────────┬───────────────────────────────────┘
                      │  signals / callbacks
┌─────────────────────▼───────────────────────────────────┐
│                  Core Services                           │
│  TradingEngine ← OrderManager ← BinanceClient           │
│  PortfolioManager  RiskManager  DynamicRiskManager       │
│  TradeJournal  AutoTrader  PingPongTrader                │
│  StrategyManager  ArbitrageDetector  ArbitrageAutoTrader│
└──────────────┬──────────────────┬───────────────────────┘
               │                  │
┌──────────────▼──────┐  ┌───────▼────────────────────────┐
│    ML / AI Layer    │  │       Data Layer                │
│  MLPredictor        │  │  PostgreSQL (trade history)     │
│  ContinuousLearner  │  │  Redis (real-time cache)        │
│  EnsembleAggregator │  │  SQLite (fallback)              │
│  RegimeDetector     │  │  JSON backup (trade journal)    │
│  MTFConfluence      │  └────────────────────────────────┘
│  SignalCouncil      │
│  WhaleWatcher       │
│  SentimentAnalyser  │
│  ForecastTracker    │
│  ArbitrageDetector  │
└─────────────────────┘
```

### Data Flow

1. **Binance WebSocket** → streams live price, order book, and trade data
2. **TradingEngine** → caches data, fires signal events
3. **ML Pipeline** → predictor → ensemble → council → final signal
4. **AutoTrader** → receives signal, checks risk, places order via OrderManager
5. **TradingEngine** → confirms fill, updates portfolio
6. **TradeJournal** → records everything with full context
7. **UI** → refreshes from data every 5 seconds, shows live state

---

*BinanceML Pro is provided for educational and research purposes.
Trading cryptocurrencies involves significant financial risk.
Past performance does not guarantee future results.
Always start with Paper Trading mode and understand the risks before
using real funds.*
