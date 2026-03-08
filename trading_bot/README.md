# BinanceML Pro

**Professional AI-Powered Binance Trading Platform — v2.0**

> Fully automated crypto trading with LSTM + Transformer ML · 10-layer architecture ·
> UK HMRC CGT reporting · Institutional-grade risk management · SQLAlchemy 3.0 ready

---

## Features

| Category | Details |
|---|---|
| **Trading** | Automated, manual & hybrid modes · Binance Spot · LIMIT / MARKET / STOP-LIMIT / OCO orders |
| **ML Engine** | LSTM + Transformer ensemble · 48 h initial training · 24 h continuous retraining · per-token fine-tuned models |
| **Signal Pipeline** | Regime detector → MTF confluence → Signal Council deliberation → Dynamic risk sizing |
| **Pair Discovery** | 1 000+ pairs scanned across USDT / BTC / ETH / BNB / SOL quote assets every 15 min |
| **Detection Suite** | Stealth accumulation · Liquidity depth grading · 4-stage volume breakout · Multi-TF trend scanner |
| **Charts** | Candlestick, Heikin-Ashi, OHLC · EMA/SMA/VWAP/BB/Ichimoku overlays · RSI, MACD, ATR, ADX sub-panels · AI forecast cone |
| **AutoTrader** | SEMI\_AUTO (confirm-to-trade) or FULL\_AUTO · Ping-Pong range trader · Statistical + triangular arbitrage |
| **Risk** | Kelly position sizing · Circuit-breaker drawdown guard · Monte Carlo simulation · Walk-forward validation |
| **Order Book** | Real-time L1/L2 depth · Bid-ask spread · Volume imbalance bar |
| **Trade Journal** | Full trade history · Signal attribution · Entry/exit annotation on charts |
| **Backtesting** | Symbol + interval + date range · Equity curve · Sharpe / CAGR / max-drawdown · Trade-by-trade log |
| **Simulation** | Live Simulation Twin (6 shadow variants) · Strategy Mutation Lab (genetic evolution) |
| **Safety** | Token contract analysis · Honeypot detection · Liquidity lock check · Rug-pull scoring |
| **Intel Log** | Real-time dockable activity log · Filter by level · Search · Export |
| **Tax** | UK HMRC CGT · Section 104 pool · 30-day bed-and-breakfast rule · Monthly PDF reports · email delivery |
| **API** | REST API on `127.0.0.1:8765` · 15+ endpoints · Bearer token auth · Webhooks |
| **MetaMask** | Optional profit-sweeping to any EVM address · BSC / Ethereum / Polygon / Arbitrum |
| **Security** | AES-256-GCM encrypted config · OS keychain integration · PBKDF2 master key · bcrypt auth |
| **Performance** | Apple Silicon MPS GPU · Thread pools · Redis caching · connection pool tuned for 20 GB RAM |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/timehub-uk/demo.git
cd demo

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate.bat     # Windows

# 3. Install dependencies
pip install --upgrade pip
pip install -r trading_bot/requirements.txt

# 4. Optional: start PostgreSQL + Redis
brew install postgresql@16 redis   # macOS
brew services start postgresql@16 redis
# Ubuntu: sudo apt install postgresql redis-server

# 5. Launch (first run opens Setup Wizard)
python trading_bot/main.py
```

### Prerequisites

| Dependency | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.10 minimum |
| PostgreSQL | 16+ | Optional — app runs with SQLite fallback |
| Redis | 7+ | Optional — caching disabled without it |
| PyTorch | 2.x | CPU or Apple Silicon MPS |
| PyQt6 | 6.x | Desktop UI |

---

## Navigation

The left sidebar has 9 numbered panels + F1 Help:

| Shortcut | Panel |
|---|---|
| `Ctrl+1` | Trading (charts, order entry, portfolio) |
| `Ctrl+2` | AutoTrader (scan → analyse → trade) |
| `Ctrl+3` | ML Training (train, monitor, signals) |
| `Ctrl+4` | Risk Dashboard (circuit breaker, Monte Carlo) |
| `Ctrl+5` | Backtesting |
| `Ctrl+6` | Trade Journal |
| `Ctrl+7` | Strategy Builder / Manager |
| `Ctrl+8` | Connections & Health |
| `Ctrl+9` | Settings |
| `F1` | Help & Shortcuts |
| `Ctrl+Shift+S` | Simulation Panel |
| `Ctrl+L` | Toggle Intel Log |

---

## Architecture

```
trading_bot/
├── main.py                         ← Entry point · startup sequence
├── config/
│   ├── settings.py                 ← Typed settings (9 config groups, 60+ options)
│   └── encryption.py               ← AES-256-GCM config encryption
├── core/
│   ├── trading_engine.py           ← Signal pipeline · thread-safe candle cache + locks
│   ├── binance_client.py           ← REST + WebSocket client
│   ├── order_manager.py            ← Order lifecycle · PostgreSQL persistence
│   ├── portfolio.py                ← Live balances · GBP/USD conversion · P&L
│   ├── risk_manager.py             ← Stop-loss, take-profit, position sizing
│   ├── gas_fee_engine.py           ← On-chain gas estimation (web3 + fallback)
│   └── metamask_wallet.py          ← EVM profit-sweep integration
├── ml/
│   ├── trainer.py                  ← LSTM + Transformer training · Optuna HPO · MPS GPU
│   ├── predictor.py                ← Real-time BUY/SELL/HOLD signals with confidence
│   ├── continuous_learner.py       ← 24 h auto-retraining · 25 min data-integrity checks
│   ├── pair_scanner.py             ← 1 000+ pair ranking (volume, activity, momentum)
│   ├── pair_ml_analyzer.py         ← Tradability Score from 6 ML tools per pair
│   ├── accumulation_detector.py    ← Stealth accumulation: NONE/WATCH/ALERT/STRONG
│   ├── liquidity_depth_analyzer.py ← Order-book depth: DEEP/ADEQUATE/THIN/ILLIQUID
│   └── volume_breakout_detector.py ← 4-stage breakout: LAUNCH→PUMP→CONSOLIDATION→BREAKOUT
├── db/
│   ├── models.py                   ← SQLAlchemy 2.0/3.0-ready ORM models
│   ├── postgres.py                 ← Connection pool · get_db() session manager
│   └── redis_client.py             ← Ticker, orderbook, portfolio cache
├── tax/
│   └── uk_tax.py                   ← HMRC CGT · Section 104 · bed-and-breakfast rule
├── api/
│   └── server.py                   ← Flask REST API · Bearer auth · webhooks
├── ui/                             ← 32 PyQt6 widget modules
│   ├── main_window.py              ← Main window, sidebar, Intel Log dock
│   ├── trading_panel.py            ← Order entry, active orders, daily P&L bar chart
│   ├── chart_widget.py             ← Candlestick charts + all indicators
│   ├── orderbook_widget.py         ← Real-time L1/L2 order book
│   ├── auto_trader_widget.py       ← AutoTrader (Pairs/Trend/Arb tabs)
│   ├── ml_training_widget.py       ← Training progress charts and signal stream
│   ├── risk_dashboard.py           ← Circuit breaker, Kelly, Monte Carlo
│   ├── backtest_widget.py          ← Backtesting engine UI
│   ├── trade_journal_widget.py     ← Trade history and signal attribution
│   ├── intel_log_widget.py         ← Live dockable activity log
│   ├── pair_scanner_widget.py      ← Pair scanner results and filters
│   ├── accumulation_widget.py      ← Accumulation detector results
│   ├── liquidity_widget.py         ← Liquidity depth grades per pair
│   ├── breakout_widget.py          ← Volume breakout stage tracker
│   ├── arbitrage_widget.py         ← Arb opportunities + active positions
│   ├── ping_pong_widget.py         ← Ping-pong range trader
│   ├── simulation_twin_widget.py   ← Live Simulation Twin (6 shadow variants)
│   ├── mutation_lab_widget.py      ← Genetic strategy evolution
│   ├── safety_widget.py            ← Token contract + rug-pull scanner
│   ├── metamask_widget.py          ← EVM wallet sweep
│   ├── strategy_builder.py         ← Strategy construction
│   ├── strategy_manager_widget.py  ← Strategy manager + ML auto-selection
│   ├── alert_panel.py              ← Alert history table
│   ├── help_widget.py              ← Shortcuts, documentation, about
│   ├── connections_widget.py       ← Service health monitor
│   ├── system_settings_widget.py   ← System configuration
│   ├── layers_settings_panel.py    ← 10-layer configuration (77 modules)
│   └── setup_wizard.py             ← First-run configuration wizard
└── utils/
    ├── logger.py                   ← Loguru structured logging + Intel Log bridge
    └── thread_manager.py           ← Named thread pools
```

### 10-Layer Stack

```
Layer  1  Infrastructure & Orchestration   MasterOrchestrator · StrategyRegistry · SecretsManager
Layer  2  Market Data Ingestion            ExchangeMDC · DEX MDC · OrderBook · TradeTape · Sentiment
Layer  3  Data Engineering & Storage       TimeNormalizer · FeatureStore · HistoricalArchive · Redis
Layer  4  Research & Quant                 RegimeDetector · WalkForward · MonteCarlo · Backtester
Layer  5  Alpha & Signal                   Momentum · MeanReversion · StatArb · Ensemble · Council
Layer  6  Risk & Capital Management        DynamicRisk · PositionSizing · DrawdownGuard · KillSwitch
Layer  7  Execution                        SmartOrderRouter · ExecutionAlgo · GasFeeEngine · MEV
Layer  8  Token & Contract Safety          ContractAnalyzer · HoneypotDetector · RugPullScorer
Layer  9  Monitoring & Reporting           PnLAttribution · TradeJournal · ForecastTracker · Alerts
Layer 10  Governance & Oversight           InvestmentCommittee · ApprovalWorkflow · AccessControl
──────── Evolution Layer                   LiveSimulationTwin · StrategyMutationLab
```

---

## REST API

Auto-starts on `http://127.0.0.1:8765`. All endpoints except `/health` require:

```
Authorization: Bearer <api_key_prefix>
```

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health (no auth required) |
| `GET` | `/api/v1/status` | System status and engine mode |
| `GET` | `/api/v1/portfolio` | Portfolio snapshot (USDT + GBP values) |
| `GET` | `/api/v1/signals` | Latest ML signals |
| `GET` | `/api/v1/trades?limit=50&symbol=BTCUSDT` | Recent trades |
| `GET` | `/api/v1/orderbook/{symbol}` | Live L1/L2 order book |
| `GET` | `/api/v1/ticker/{symbol}` | Live ticker |
| `POST` | `/api/v1/order` | Place a limit order |
| `DELETE` | `/api/v1/order/{id}` | Cancel an order |
| `GET` | `/api/v1/ml/status` | ML training status |
| `POST` | `/api/v1/ml/predict` | On-demand prediction for a symbol |
| `GET` | `/api/v1/tax/monthly` | Monthly CGT tax summary |
| `GET` | `/api/v1/log?limit=100` | Recent Intel Log entries |
| `POST` | `/api/v1/webhook/register` | Register a webhook endpoint |

```bash
# Place an order
curl -X POST http://localhost:8765/api/v1/order \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"BUY","quantity":0.001,"price":65000}'

# Register a webhook for TRADE + SIGNAL events
curl -X POST http://localhost:8765/api/v1/webhook/register \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://your-app.com/hook","events":["TRADE","SIGNAL"]}'
```

---

## UK Tax Reporting

- **Section 104 pool** cost basis (HMRC-compliant)
- **30-day bed-and-breakfast** rule
- **Same-day** matching rule
- CGT annual allowance: **£3,000** (2024/25 onwards)
- Basic rate: **10%** · Higher rate: **20%**
- Monthly PDF reports emailed on the 1st of each month
- Annual CGT return summary for HMRC Self Assessment

---

## Security

| Protection | Implementation |
|---|---|
| Config encryption | AES-256-GCM |
| Key storage | OS keychain (Keychain on macOS, libsecret on Linux) |
| Master key derivation | PBKDF2-HMAC-SHA256 · 600 000 iterations |
| User password hashing | bcrypt |
| Database connections | SSL (`sslmode=prefer`) |
| API authentication | Bearer token (stored encrypted) |

---

## Database Compatibility

All ORM queries use the **SQLAlchemy 2.0 `select()` API** — compatible with
SQLAlchemy 2.x and ready for SQLAlchemy 3.0 (which removes the legacy `.query()` API).

```python
# Pattern used throughout the codebase
from sqlalchemy import select
result = db.execute(
    select(Trade).where(Trade.symbol == symbol)
).scalar_one_or_none()
```

---

## Configuration

Settings are stored in `~/.binanceml/config.enc` (AES-256-GCM encrypted).

| Group | Key Options |
|---|---|
| `binance` | api\_key, api\_secret, testnet, recv\_window |
| `database` | host, port, name, user, password, pool\_size, ssl\_mode |
| `redis` | host, port, db, password, max\_connections |
| `ml` | training\_hours, top\_tokens, lookback\_window, lstm\_layers, confidence\_threshold |
| `trading` | mode (manual/auto/hybrid), max\_open\_trades, risk\_per\_trade\_pct, order\_type |
| `tax` | jurisdiction, cgt\_annual\_allowance, basic\_rate\_pct, higher\_rate\_pct, email\_reports |
| `ui` | theme, accent\_color, font\_size, chart\_candle\_count, default\_interval |
| `ai` | provider (claude/openai/gemini), api keys, voice\_enabled |

---

## ⚠ Disclaimer

Trading cryptocurrencies involves significant financial risk. This software is provided
for educational and research purposes only. Past ML performance does not guarantee future
results. Always use Paper Trading mode first. Never trade with money you cannot afford to
lose. This is not financial advice.
