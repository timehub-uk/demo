# BinanceML Pro

**Professional AI-Powered Binance Trading Platform**
Optimised for Apple Silicon (Mac Mini M4) · Python · PyQt6 · PostgreSQL · Redis

---

## Features

| Category | Details |
|---|---|
| **Trading** | Automated & manual · Binance Spot · LIMIT / MARKET / STOP / OCO orders |
| **ML Engine** | LSTM + Transformer · 48h initial training · Continuous background learning |
| **Signals** | BUY / SELL / HOLD with confidence scores · Risk/reward evaluation |
| **Charts** | Candlestick · EMA 20/50/200 · Bollinger Bands · VWAP · RSI · MACD · VWAP |
| **Order Book** | Real-time L1/L2 depth · Bid-ask spread · Imbalance bar |
| **Intel Log** | Live dynamic activity log · All events · Filter · Search · Export |
| **Data Integrity** | Automatic checks every 25 min · OHLC validation · Gap detection |
| **Tax** | UK HMRC CGT · Section 104 pool · Monthly PDF reports · Email delivery |
| **API** | REST API server · Webhooks · Bearer token auth · 15+ endpoints |
| **Security** | AES-256-GCM encryption · OS keychain · bcrypt password hashing |
| **Performance** | Apple Silicon MPS GPU · Thread pools · Redis caching · 20GB memory aware |

---

## Quick Start

```bash
# 1. Install dependencies
bash trading_bot/scripts/setup.sh

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Launch (first run shows setup wizard)
python trading_bot/main.py
```

### Prerequisites

- macOS 14+ (Apple Silicon) or Linux
- Python 3.11+
- PostgreSQL 16+ (`brew install postgresql@16`)
- Redis 7+ (`brew install redis`)

---

## Architecture

```
trading_bot/
├── main.py                  ← Entry point
├── config/                  ← Settings + AES-256 encryption
├── core/                    ← Binance client, trading engine, orders, risk
├── ml/                      ← LSTM/Transformer trainer, predictor, continuous learner
│   ├── trading_fundamentals ← Candlestick & chart pattern knowledge
│   └── continuous_learner   ← 25-min data integrity checks + retraining
├── db/                      ← PostgreSQL (SQLAlchemy) + Redis
├── tax/                     ← UK HMRC CGT calculator + PDF/email reports
├── api/                     ← REST API server (Flask) + webhook dispatcher
├── ui/                      ← PyQt6 professional dark trading UI
│   ├── chart_widget         ← Candlestick charts + technical indicators
│   ├── orderbook_widget     ← L1/L2 order book
│   ├── trading_panel        ← Order entry + trade history + portfolio
│   ├── ml_training_widget   ← Training progress + signals
│   ├── intel_log_widget     ← Live dynamic activity log
│   └── main_window          ← Main application window
└── utils/                   ← Threading, memory, Intel logger
```

---

## REST API

The embedded REST API starts automatically on `http://127.0.0.1:8765`.

```bash
# Check status
curl http://localhost:8765/health

# Get portfolio (auth required)
curl -H "Authorization: Bearer <api_key_prefix>" http://localhost:8765/api/v1/portfolio

# Place an order
curl -X POST http://localhost:8765/api/v1/order \
  -H "Authorization: Bearer <api_key_prefix>" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"BUY","quantity":0.001,"price":50000}'

# Register a webhook
curl -X POST http://localhost:8765/api/v1/webhook/register \
  -H "Authorization: Bearer <api_key_prefix>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://your-app.com/hook","events":["TRADE","SIGNAL"]}'
```

---

## UK Tax Reporting

- Implements **Section 104 pool** cost basis
- **30-day bed-and-breakfast** rule
- CGT annual allowance (£3,000 for 2024/25)
- Monthly PDF reports emailed automatically on the 1st of each month
- Annual CGT return summary for HMRC Self Assessment

---

## ML Training

1. **Initial 48h training** runs on first launch
2. Downloads top 100 USDT tokens by volume
3. Fetches 1 year of historical data across 5 intervals (1m / 5m / 15m / 1h / 4h)
4. Computes 18 technical indicators per candle
5. Trains LSTM + Transformer ensemble
6. **Continuous retraining** every 24h while the app is running
7. **Data integrity checks every 25 minutes** – results shown in Intel Log and Data Integrity panel

---

## Security

- All API keys encrypted with **AES-256-GCM** before storage
- Keys stored in **OS keychain** (Keychain on macOS, libsecret on Linux)
- Master password derived via **PBKDF2-HMAC-SHA256** (600,000 iterations)
- **bcrypt** password hashing for user authentication
- Database connections use SSL (`sslmode=prefer`)

---

## ⚠ Disclaimer

Trading cryptocurrencies involves significant financial risk. This software is provided for educational and research purposes. Past ML performance does not guarantee future results. Always use the Testnet for initial testing. Never trade with money you cannot afford to lose. This is not financial advice.
