"""
Layers Configuration Panel
===========================
Settings >> Configuration >> Layers

Shows all 10 system layers with sub-tabs for each module.
Each module has: toggle on/off, parameter sliders, API key fields,
and dependency notifications.

Keyboard shortcuts:
  Shift+Alt+1  → Layer 1: Infrastructure & Orchestration
  Shift+Alt+2  → Layer 2: Market Data Ingestion
  Shift+Alt+3  → Layer 3: Data Engineering & Storage
  Shift+Alt+4  → Layer 4: Research & Quant
  Shift+Alt+5  → Layer 5: Alpha & Signal
  Shift+Alt+6  → Layer 6: Risk & Capital Management
  Shift+Alt+7  → Layer 7: Execution
  Shift+Alt+8  → Layer 8: Token & Contract Safety
  Shift+Alt+9  → Layer 9: Monitoring & Reporting
  Shift+Alt+0  → Layer 10: Governance & Oversight
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
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


# ── Layer definitions ─────────────────────────────────────────────────────────

LAYERS: List[Tuple[int, str, str, List[dict]]] = [
    # (number, name, color, modules)
    (1, "Infrastructure & Orchestration", "#7B68EE", [
        {"id": "orchestrator", "name": "1. Master Orchestrator", "flag": "ml_trading",
         "desc": "Coordinates all services, scheduling, dependencies, and failover.",
         "params": [
             {"label": "Health poll interval (s)", "type": "spin", "min": 5, "max": 120, "default": 30, "key": "poll_interval"},
             {"label": "Max service restarts", "type": "spin", "min": 1, "max": 20, "default": 5, "key": "max_restarts"},
         ]},
        {"id": "strategy_registry", "name": "2. Strategy Registry", "flag": "ml_trading",
         "desc": "Stores all active, inactive, experimental, and archived strategies.",
         "params": []},
        {"id": "config_manager", "name": "3. Configuration Manager", "flag": "ml_trading",
         "desc": "Central source for parameters, exchange configs, wallet settings, and model flags.",
         "params": []},
        {"id": "secrets_manager", "name": "4. Secrets Manager", "flag": "ml_trading",
         "desc": "Handles API keys, signing keys, RPC credentials, and secure secrets rotation.",
         "params": [
             {"label": "Binance API Key", "type": "secret", "key": "BINANCE_API_KEY"},
             {"label": "Binance Secret Key", "type": "secret", "key": "BINANCE_SECRET_KEY"},
             {"label": "ETH RPC URL", "type": "text", "key": "ETH_RPC_URL"},
             {"label": "BSC RPC URL", "type": "text", "key": "BSC_RPC_URL"},
         ]},
        {"id": "feature_flags", "name": "5. Feature Flag Controller", "flag": "ml_trading",
         "desc": "Turns modules on and off safely without redeploying.",
         "params": []},
        {"id": "health_monitor", "name": "6. Service Health Monitor", "flag": "ml_trading",
         "desc": "Tracks process uptime, queue health, memory, CPU, and API availability.",
         "params": [
             {"label": "CPU alert threshold (%)", "type": "slider", "min": 50, "max": 99, "default": 90, "key": "cpu_threshold"},
             {"label": "Memory alert threshold (%)", "type": "slider", "min": 50, "max": 99, "default": 90, "key": "mem_threshold"},
         ]},
    ]),
    (2, "Market Data Ingestion", "#00CED1", [
        {"id": "exchange_mdc", "name": "7. Exchange Market Data", "flag": "ml_trading",
         "desc": "Streams spot, perp, futures, and options market data from exchanges.",
         "params": [
             {"label": "Poll interval (s)", "type": "spin", "min": 1, "max": 60, "default": 5, "key": "poll_interval"},
             {"label": "Max symbols", "type": "spin", "min": 1, "max": 200, "default": 50, "key": "max_symbols"},
         ]},
        {"id": "dex_mdc", "name": "8. DEX Market Data", "flag": "dex_execution",
         "desc": "Collects pool pricing, swaps, LP changes from on-chain venues.",
         "auto_enables": ["ETH_RPC_URL"],
         "params": [
             {"label": "Poll interval (s)", "type": "spin", "min": 5, "max": 120, "default": 15, "key": "poll_interval"},
         ]},
        {"id": "orderbook", "name": "9. Order Book Collector", "flag": "ml_trading",
         "desc": "Captures depth, spread, imbalance, cancellations, and microstructure changes.",
         "params": [
             {"label": "Depth levels", "type": "spin", "min": 5, "max": 100, "default": 20, "key": "depth_levels"},
         ]},
        {"id": "trade_tape", "name": "10. Trade Tape Collector", "flag": "ml_trading",
         "desc": "Captures prints, aggressor side, block trades, sweep behavior.",
         "params": []},
        {"id": "funding_basis", "name": "11. Funding & Basis Collector", "flag": "ml_trading",
         "desc": "Tracks perp funding, spot-perp basis, and cash-and-carry conditions.",
         "params": [
             {"label": "Extreme funding alert (%)", "type": "dspin", "min": 10.0, "max": 200.0, "default": 50.0, "key": "extreme_pct"},
         ]},
        {"id": "options_vol", "name": "12. Options Vol Surface", "flag": "options_surface",
         "desc": "Builds implied vol surfaces, skew, term structure, and gamma pockets.",
         "params": []},
        {"id": "onchain_tx", "name": "13. On-Chain Transaction", "flag": "ml_trading",
         "desc": "Watches transfers, large wallet moves, approvals, and bridge flows.",
         "params": [
             {"label": "Whale threshold ($)", "type": "spin", "min": 10000, "max": 10000000, "default": 500000, "key": "whale_usd"},
         ]},
        {"id": "token_metadata", "name": "14. Token Metadata", "flag": "contract_safety",
         "desc": "Tracks supply, unlocks, emission schedules, tax logic, and contract metadata.",
         "params": []},
        {"id": "news_events", "name": "15. News & Event Collector", "flag": "sentiment_signals",
         "desc": "Aggregates exchange listings, governance votes, protocol changes.",
         "params": []},
        {"id": "social_sentiment", "name": "16. Social Sentiment", "flag": "sentiment_signals",
         "desc": "Ingests posts, channel activity, influencer spikes, narrative bursts.",
         "params": [
             {"label": "Sentiment lookback (h)", "type": "spin", "min": 1, "max": 72, "default": 4, "key": "lookback_hours"},
         ]},
        {"id": "dev_activity", "name": "17. Developer Activity", "flag": "ml_trading",
         "desc": "Tracks GitHub commits, releases, repo activity, contributor expansion.",
         "params": []},
        {"id": "mempool", "name": "18. Mempool Collector", "flag": "mempool_watch",
         "desc": "Captures pending transactions for early detection of large swaps and MEV.",
         "auto_enables": ["mev_protection"],
         "params": [
             {"label": "Large tx threshold ($)", "type": "spin", "min": 1000, "max": 1000000, "default": 50000, "key": "large_tx_usd"},
             {"label": "ETH RPC URL", "type": "text", "key": "ETH_RPC_URL"},
         ]},
    ]),
    (3, "Data Engineering & Storage", "#32CD32", [
        {"id": "time_normalizer", "name": "19. Time Normalisation Engine", "flag": "ml_trading",
         "desc": "Synchronises timestamps across exchanges, chains, and external feeds.",
         "params": []},
        {"id": "symbol_mapper", "name": "20. Symbol & Contract Mapper", "flag": "ml_trading",
         "desc": "Maps assets across tickers, wrapped assets, chains, and exchange naming.",
         "params": []},
        {"id": "data_cleaner", "name": "21. Data Cleaner", "flag": "ml_trading",
         "desc": "Removes bad ticks, duplicate trades, stale candles, and malformed records.",
         "params": [
             {"label": "Max price Z-score", "type": "dspin", "min": 2.0, "max": 10.0, "default": 5.0, "key": "max_zscore"},
             {"label": "Min volume filter", "type": "dspin", "min": 0.0, "max": 1.0, "default": 0.0, "key": "min_volume"},
         ]},
        {"id": "feature_store", "name": "22. Feature Store", "flag": "ml_trading",
         "desc": "Stores reusable engineered features for model training and live inference.",
         "params": [
             {"label": "Max history per symbol", "type": "spin", "min": 100, "max": 100000, "default": 10000, "key": "max_history"},
         ]},
        {"id": "historical_archive", "name": "23. Historical Archive", "flag": "ml_trading",
         "desc": "Maintains long-term tick, bar, order book, funding, and chain data.",
         "params": []},
        {"id": "realtime_cache", "name": "24. Real-Time Cache", "flag": "ml_trading",
         "desc": "Low-latency access layer for recent market state.",
         "params": [
             {"label": "Redis Host", "type": "text", "key": "REDIS_HOST"},
             {"label": "Redis Port", "type": "spin", "min": 1, "max": 65535, "default": 6379, "key": "REDIS_PORT"},
         ]},
        {"id": "data_quality", "name": "25. Data Quality Auditor", "flag": "ml_trading",
         "desc": "Scores feed reliability, missingness, drift, and source confidence.",
         "params": [
             {"label": "Stale threshold (s)", "type": "spin", "min": 30, "max": 3600, "default": 300, "key": "stale_seconds"},
             {"label": "Min completeness (%)", "type": "slider", "min": 50, "max": 100, "default": 80, "key": "min_completeness"},
         ]},
    ]),
    (4, "Research & Quant", "#FF8C00", [
        {"id": "factor_research", "name": "26. Factor Research Engine", "flag": "ml_trading",
         "desc": "Builds momentum, mean reversion, carry, basis, volatility, and liquidity factors.",
         "params": []},
        {"id": "regime_detector", "name": "27. Regime Detection Engine", "flag": "regime_detection",
         "desc": "Classifies trending, ranging, panic, illiquid, mean-reverting, and event-driven states.",
         "params": [
             {"label": "Lookback bars", "type": "spin", "min": 20, "max": 500, "default": 100, "key": "lookback"},
         ]},
        {"id": "correlation", "name": "28. Correlation & Clustering", "flag": "ml_trading",
         "desc": "Finds asset groups, sector linkages, contagion pathways, and hidden beta exposure.",
         "params": []},
        {"id": "portfolio_opt", "name": "29. Portfolio Optimisation", "flag": "ml_trading",
         "desc": "Allocates capital across strategies and assets under risk and correlation constraints.",
         "params": []},
        {"id": "walk_forward", "name": "30. Walk-Forward Validation", "flag": "walk_forward",
         "desc": "Tests whether a strategy remains stable out of sample.",
         "params": [
             {"label": "Train window (bars)", "type": "spin", "min": 100, "max": 5000, "default": 500, "key": "train_bars"},
             {"label": "Test window (bars)", "type": "spin", "min": 50, "max": 1000, "default": 100, "key": "test_bars"},
             {"label": "Folds", "type": "spin", "min": 3, "max": 20, "default": 5, "key": "folds"},
         ]},
        {"id": "monte_carlo", "name": "31. Monte Carlo Simulation", "flag": "monte_carlo",
         "desc": "Stress-tests returns, slippage, tail events, and path dependency.",
         "params": [
             {"label": "Simulations", "type": "spin", "min": 100, "max": 10000, "default": 1000, "key": "n_sims"},
         ]},
        {"id": "backtester", "name": "32. Backtesting Engine", "flag": "ml_trading",
         "desc": "Runs event-accurate simulation with fills, fees, partial liquidity.",
         "params": [
             {"label": "Slippage model (%)", "type": "dspin", "min": 0.0, "max": 2.0, "default": 0.05, "key": "slippage_pct"},
             {"label": "Fee (%)", "type": "dspin", "min": 0.0, "max": 1.0, "default": 0.075, "key": "fee_pct"},
         ]},
        {"id": "scenario", "name": "33. Scenario Engine", "flag": "monte_carlo",
         "desc": "Simulates exchange outages, stablecoin depegs, liquidation cascades.",
         "params": []},
        {"id": "strategy_evolution", "name": "34. Strategy Evolution Engine", "flag": "strategy_mutation",
         "desc": "Automated search and mutation to discover improved parameter sets.",
         "params": [
             {"label": "Population size", "type": "spin", "min": 5, "max": 100, "default": 20, "key": "population_size"},
             {"label": "Mutation rate (%)", "type": "slider", "min": 5, "max": 50, "default": 20, "key": "mutation_rate"},
             {"label": "Max generations", "type": "spin", "min": 5, "max": 200, "default": 50, "key": "max_generations"},
             {"label": "Max drawdown gate (%)", "type": "spin", "min": 5, "max": 50, "default": 20, "key": "max_dd_pct"},
         ]},
        {"id": "model_training", "name": "35. Model Training Engine", "flag": "ml_trading",
         "desc": "Trains ML models for classification, forecasting, ranking, and anomaly detection.",
         "params": [
             {"label": "Training epochs", "type": "spin", "min": 10, "max": 500, "default": 100, "key": "epochs"},
             {"label": "Batch size", "type": "spin", "min": 16, "max": 512, "default": 64, "key": "batch_size"},
         ]},
        {"id": "model_registry", "name": "36. Model Registry", "flag": "ml_trading",
         "desc": "Stores versioned models, validation stats, deployment status, and rollback points.",
         "params": []},
    ]),
    (5, "Alpha & Signal", "#FF6B6B", [
        {"id": "momentum_signal", "name": "37. Momentum Signal Engine", "flag": "ml_trading",
         "desc": "Finds persistent directional trends.",
         "params": [
             {"label": "Fast period", "type": "spin", "min": 5, "max": 50, "default": 12, "key": "fast_period"},
             {"label": "Slow period", "type": "spin", "min": 20, "max": 200, "default": 26, "key": "slow_period"},
             {"label": "Signal threshold", "type": "dspin", "min": 0.0, "max": 2.0, "default": 0.5, "key": "threshold"},
         ]},
        {"id": "mean_reversion", "name": "38. Mean Reversion Signal", "flag": "ml_trading",
         "desc": "Looks for temporary deviations from fair value or local equilibrium.",
         "params": [
             {"label": "Lookback period", "type": "spin", "min": 10, "max": 200, "default": 50, "key": "lookback"},
             {"label": "Z-score entry", "type": "dspin", "min": 0.5, "max": 4.0, "default": 2.0, "key": "z_entry"},
         ]},
        {"id": "basis_carry", "name": "39. Basis & Carry Signal", "flag": "ml_trading",
         "desc": "Trades funding, term structure, and spot-perp dislocations.",
         "params": [
             {"label": "Min carry rate (%/yr)", "type": "dspin", "min": 5.0, "max": 100.0, "default": 20.0, "key": "min_carry"},
         ]},
        {"id": "vol_signal", "name": "40. Volatility Signal Engine", "flag": "ml_trading",
         "desc": "Targets realized vs implied vol, squeeze setups, and gamma-sensitive zones.",
         "params": []},
        {"id": "stat_arb", "name": "41. Statistical Arbitrage", "flag": "ml_trading",
         "desc": "Builds pair trades, baskets, spreads, and market-neutral relative value signals.",
         "params": []},
        {"id": "onchain_smart_money", "name": "42. On-Chain Smart Money", "flag": "ml_trading",
         "desc": "Tracks whale wallets, fund flows, VC wallets, treasury behavior.",
         "params": [
             {"label": "Whale threshold ($)", "type": "spin", "min": 50000, "max": 10000000, "default": 500000, "key": "whale_usd"},
         ]},
        {"id": "token_launch_signal", "name": "43. Token Launch Signal", "flag": "ml_trading",
         "desc": "Detects new pools, launch conditions, and early momentum.",
         "auto_enables": ["contract_safety", "honeypot_check", "rugpull_score"],
         "params": [
             {"label": "Min liquidity ($)", "type": "spin", "min": 1000, "max": 1000000, "default": 10000, "key": "min_liq_usd"},
             {"label": "Min lock (%)", "type": "slider", "min": 0, "max": 100, "default": 50, "key": "min_lock_pct"},
             {"label": "Max rug probability", "type": "dspin", "min": 0.1, "max": 1.0, "default": 0.45, "key": "max_rug_prob"},
         ]},
        {"id": "sentiment_narrative", "name": "44. Sentiment & Narrative", "flag": "sentiment_signals",
         "desc": "Transforms social, news, and discourse shifts into tradable signals.",
         "params": []},
        {"id": "event_driven", "name": "45. Event-Driven Signal", "flag": "ml_trading",
         "desc": "Trades listings, unlocks, governance outcomes, token burns, airdrops.",
         "params": []},
        {"id": "signal_council", "name": "46. Ensemble Signal Council", "flag": "ml_trading",
         "desc": "Combines multiple signals with confidence weighting and conflict resolution.",
         "params": [
             {"label": "Min council votes", "type": "spin", "min": 1, "max": 10, "default": 3, "key": "min_votes"},
             {"label": "Confidence threshold", "type": "dspin", "min": 0.3, "max": 1.0, "default": 0.6, "key": "confidence_threshold"},
         ]},
    ]),
    (6, "Risk & Capital Management", "#DC143C", [
        {"id": "dynamic_risk", "name": "47. Dynamic Risk Engine", "flag": "ml_trading",
         "desc": "Adjusts limits based on volatility, liquidity, drawdown, and regime changes.",
         "params": [
             {"label": "Max risk per trade (%)", "type": "dspin", "min": 0.1, "max": 5.0, "default": 1.0, "key": "max_risk_pct"},
         ]},
        {"id": "position_sizing", "name": "48. Position Sizing Engine", "flag": "ml_trading",
         "desc": "Handles notional sizing, volatility scaling, conviction weighting.",
         "params": [
             {"label": "Max position size (%)", "type": "dspin", "min": 1.0, "max": 100.0, "default": 10.0, "key": "max_pos_pct"},
             {"label": "Kelly fraction", "type": "dspin", "min": 0.1, "max": 1.0, "default": 0.25, "key": "kelly_fraction"},
         ]},
        {"id": "exposure_engine", "name": "49. Exposure Engine", "flag": "ml_trading",
         "desc": "Measures directional, sector, chain, exchange, and factor exposure.",
         "params": [
             {"label": "Max single asset (%)", "type": "dspin", "min": 5.0, "max": 50.0, "default": 20.0, "key": "max_single_pct"},
             {"label": "Max sector (%)", "type": "dspin", "min": 10.0, "max": 80.0, "default": 40.0, "key": "max_sector_pct"},
             {"label": "Max gross exposure (%)", "type": "dspin", "min": 50.0, "max": 300.0, "default": 150.0, "key": "max_gross_pct"},
         ]},
        {"id": "drawdown_guard", "name": "50. Drawdown Guard", "flag": "ml_trading",
         "desc": "Triggers de-risking, cool-down windows, or strategy shutdown during loss clusters.",
         "params": [
             {"label": "L1 Warn (%)", "type": "dspin", "min": 1.0, "max": 30.0, "default": 5.0, "key": "l1_pct"},
             {"label": "L2 Reduce (%)", "type": "dspin", "min": 2.0, "max": 40.0, "default": 10.0, "key": "l2_pct"},
             {"label": "L3 Pause (%)", "type": "dspin", "min": 5.0, "max": 50.0, "default": 15.0, "key": "l3_pct"},
             {"label": "L4 Halt (%)", "type": "dspin", "min": 10.0, "max": 60.0, "default": 20.0, "key": "l4_pct"},
         ]},
        {"id": "liquidity_risk", "name": "51. Liquidity Risk Engine", "flag": "ml_trading",
         "desc": "Estimates slippage, exit capacity, pool fragility, and market impact.",
         "params": []},
        {"id": "counterparty_risk", "name": "52. Counterparty Risk Engine", "flag": "ml_trading",
         "desc": "Scores exchange solvency, custody concentration, and operational dependency.",
         "params": []},
        {"id": "treasury_risk", "name": "53. Treasury & Stablecoin Risk", "flag": "ml_trading",
         "desc": "Monitors stablecoin mix, bridge dependencies, wallet concentration.",
         "params": []},
        {"id": "kill_switch", "name": "54. Kill Switch Controller", "flag": "ml_trading",
         "desc": "Hard stops for strategies, venues, wallets, or the entire trading system.",
         "params": []},
    ]),
    (7, "Execution", "#1E90FF", [
        {"id": "smart_router", "name": "55. Smart Order Router", "flag": "auto_trader",
         "desc": "Chooses venue, route, slice size, and execution style.",
         "params": [
             {"label": "Max slippage (%)", "type": "dspin", "min": 0.05, "max": 2.0, "default": 0.5, "key": "max_slippage"},
         ]},
        {"id": "exec_algo", "name": "56. Execution Algorithm Engine", "flag": "auto_trader",
         "desc": "Supports TWAP, VWAP, POV, iceberg, sniper, passive maker execution.",
         "params": [
             {"label": "Default algo", "type": "combo",
              "options": ["market", "limit", "twap", "vwap", "iceberg", "sniper", "passive_maker"],
              "default": "limit", "key": "default_algo"},
             {"label": "TWAP duration (min)", "type": "spin", "min": 5, "max": 240, "default": 30, "key": "twap_duration"},
             {"label": "TWAP slices", "type": "spin", "min": 3, "max": 50, "default": 10, "key": "twap_slices"},
         ]},
        {"id": "dex_router", "name": "57. DEX Execution Router", "flag": "dex_execution",
         "desc": "Optimises multi-hop swaps, aggregator paths, and gas-aware execution.",
         "params": []},
        {"id": "gas_engine", "name": "58. Gas & Priority Fee Engine", "flag": "dex_execution",
         "desc": "Estimates fee levels for on-chain speed and cost control.",
         "params": [
             {"label": "Default gas urgency", "type": "combo",
              "options": ["slow", "standard", "fast", "instant"],
              "default": "standard", "key": "default_urgency"},
             {"label": "Gas cap (Gwei)", "type": "dspin", "min": 1.0, "max": 1000.0, "default": 100.0, "key": "gas_cap_gwei"},
         ]},
        {"id": "mev_protection", "name": "59. MEV Protection Engine", "flag": "mev_protection",
         "desc": "Detects sandwich risk, frontrunning exposure, and private relay opportunities.",
         "auto_enables": ["mempool_watch"],
         "params": [
             {"label": "Max sandwich cost (%)", "type": "dspin", "min": 0.1, "max": 5.0, "default": 1.0, "key": "max_sandwich_pct"},
         ]},
        {"id": "reconciliation", "name": "60. Trade Reconciliation Engine", "flag": "auto_trader",
         "desc": "Verifies intended order versus actual fill, fee, slippage, and settlement.",
         "params": [
             {"label": "Max slippage alert (%)", "type": "dspin", "min": 0.1, "max": 5.0, "default": 1.0, "key": "max_slippage_pct"},
         ]},
    ]),
    (8, "Token & Contract Safety", "#FFD700", [
        {"id": "contract_analyzer", "name": "61. Contract Analyzer", "flag": "contract_safety",
         "desc": "Checks mint authority, blacklist logic, trading lockouts, pausability.",
         "params": [
             {"label": "Danger score threshold", "type": "slider", "min": 30, "max": 100, "default": 70, "key": "danger_threshold"},
         ]},
        {"id": "honeypot_detector", "name": "62. Honeypot Detector", "flag": "honeypot_check",
         "desc": "Tests whether a token can actually be sold.",
         "params": [
             {"label": "Max sell tax (%)", "type": "dspin", "min": 5.0, "max": 50.0, "default": 25.0, "key": "max_sell_tax"},
         ]},
        {"id": "liq_lock", "name": "63. Liquidity Lock Analyzer", "flag": "contract_safety",
         "desc": "Verifies lock duration, lock concentration, LP ownership, and unlock timing.",
         "params": [
             {"label": "Min lock % required", "type": "slider", "min": 0, "max": 100, "default": 80, "key": "min_lock_pct"},
             {"label": "Min lock days", "type": "spin", "min": 0, "max": 365, "default": 30, "key": "min_lock_days"},
         ]},
        {"id": "wallet_graph", "name": "64. Wallet Graph Analyzer", "flag": "contract_safety",
         "desc": "Builds relationships among deployer wallets, treasury wallets, and insiders.",
         "params": [
             {"label": "Max graph depth", "type": "spin", "min": 1, "max": 5, "default": 2, "key": "max_depth"},
         ]},
        {"id": "rugpull_score", "name": "65. Rug-Pull Probability Engine", "flag": "rugpull_score",
         "desc": "Scores launches based on contract risk, wallet behavior, and liquidity profile.",
         "params": [
             {"label": "Max rug prob to trade", "type": "dspin", "min": 0.1, "max": 1.0, "default": 0.4, "key": "max_rug_prob"},
         ]},
    ]),
    (9, "Monitoring & Reporting", "#98FB98", [
        {"id": "pnl_attribution", "name": "66. PnL Attribution Engine", "flag": "ml_trading",
         "desc": "Explains returns by strategy, asset, venue, signal family, and execution quality.",
         "params": []},
        {"id": "forecast_tracker", "name": "67. Forecast Tracker", "flag": "ml_trading",
         "desc": "Measures predicted versus realized move, hit rate, calibration, and decay.",
         "params": []},
        {"id": "trade_journal", "name": "68. Trade Journal Engine", "flag": "ml_trading",
         "desc": "Records rationale, market regime, model confidence, and post-trade review.",
         "params": []},
        {"id": "alerting", "name": "69. Alerting Engine", "flag": "telegram_alerts",
         "desc": "Pushes risk alerts, fill alerts, exchange errors, and anomaly notifications.",
         "params": [
             {"label": "Telegram Bot Token", "type": "secret", "key": "TELEGRAM_BOT_TOKEN"},
             {"label": "Telegram Chat ID", "type": "text", "key": "TELEGRAM_CHAT_ID"},
         ]},
        {"id": "dashboard", "name": "70. Dashboard & Reporting", "flag": "ml_trading",
         "desc": "Live positions, exposures, PnL, error states, and operator controls.",
         "params": []},
        {"id": "compliance_log", "name": "71. Compliance Log Engine", "flag": "ml_trading",
         "desc": "Maintains audit trails, decision logs, approvals, and model-change records.",
         "params": []},
        {"id": "post_mortem", "name": "72. Post-Mortem Analyzer", "flag": "ml_trading",
         "desc": "Investigates losses, outages, bad fills, and missed opportunities.",
         "params": []},
    ]),
    (10, "Governance & Oversight", "#9370DB", [
        {"id": "investment_committee", "name": "73. Investment Committee Interface", "flag": "ml_trading",
         "desc": "Manual review panel for enabling, disabling, or resizing strategies.",
         "params": []},
        {"id": "research_notebook", "name": "74. Research Notebook Environment", "flag": "ml_trading",
         "desc": "Controlled environment for quant research and reproducibility.",
         "params": []},
        {"id": "approval_workflow", "name": "75. Approval Workflow Engine", "flag": "ml_trading",
         "desc": "Requires sign-off for new strategies, leverage changes, wallet permissions.",
         "params": [
             {"label": "Approval expiry (h)", "type": "spin", "min": 1, "max": 168, "default": 24, "key": "expire_hours"},
         ]},
        {"id": "access_control", "name": "76. Access Control Layer", "flag": "ml_trading",
         "desc": "Defines operator, researcher, trader, and admin privileges.",
         "params": []},
        {"id": "disaster_recovery", "name": "77. Disaster Recovery Controller", "flag": "ml_trading",
         "desc": "Backup RPCs, backup exchanges, backup signing flow, and recovery runbooks.",
         "params": [
             {"label": "Backup ETH RPC URL", "type": "text", "key": "BACKUP_ETH_RPC"},
         ]},
    ]),
]


class ModulePanel(QWidget):
    """Settings sub-panel for a single module."""

    def __init__(self, module: dict, flags_controller=None, parent=None):
        super().__init__(parent)
        self._module = module
        self._flags = flags_controller
        self._setup_ui()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        # Module header with toggle
        hdr = QHBoxLayout()
        name_lbl = QLabel(self._module["name"])
        name_lbl.setStyleSheet("font-weight:bold; font-size:12px; color:#D0D0F0;")
        hdr.addWidget(name_lbl)
        hdr.addStretch()

        # Toggle
        flag_key = self._module.get("flag", "")
        is_on = True
        if self._flags and flag_key:
            is_on = self._flags.is_enabled(flag_key)
        self._toggle = QCheckBox("Enabled")
        self._toggle.setChecked(is_on)
        self._toggle.setStyleSheet(f"color:{ACCENT_BLUE};")
        self._toggle.stateChanged.connect(self._on_toggle)
        hdr.addWidget(self._toggle)
        lay.addLayout(hdr)

        # Description
        desc_lbl = QLabel(self._module.get("desc", ""))
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color:{TEXT_MUTED}; font-size:10px;")
        lay.addWidget(desc_lbl)

        # Auto-enables notification
        auto_enables = self._module.get("auto_enables", [])
        if auto_enables:
            ae_lbl = QLabel(
                f"⚡ Enabling this module will also activate: {', '.join(auto_enables)}"
            )
            ae_lbl.setWordWrap(True)
            ae_lbl.setStyleSheet(f"color:#FFA500; font-size:10px; font-style:italic;")
            lay.addWidget(ae_lbl)

        # Parameters
        params = self._module.get("params", [])
        if params:
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            form.setSpacing(6)
            for param in params:
                widget = self._make_param_widget(param)
                if widget:
                    lbl = QLabel(param["label"])
                    lbl.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
                    form.addRow(lbl, widget)
            lay.addLayout(form)

        lay.addStretch()

    def _make_param_widget(self, param: dict) -> Optional[QWidget]:
        ptype = param.get("type", "text")
        if ptype == "spin":
            w = QSpinBox()
            w.setRange(param.get("min", 0), param.get("max", 9999))
            w.setValue(param.get("default", 0))
            w.setFixedWidth(100)
            return w
        elif ptype == "dspin":
            w = QDoubleSpinBox()
            w.setRange(param.get("min", 0.0), param.get("max", 100.0))
            w.setValue(param.get("default", 0.0))
            w.setDecimals(3)
            w.setFixedWidth(100)
            return w
        elif ptype == "slider":
            container = QWidget()
            hlay = QHBoxLayout(container)
            hlay.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(param.get("min", 0), param.get("max", 100))
            slider.setValue(param.get("default", 50))
            slider.setFixedWidth(120)
            val_lbl = QLabel(str(param.get("default", 50)))
            val_lbl.setStyleSheet(f"color:{ACCENT_BLUE}; min-width:35px;")
            slider.valueChanged.connect(lambda v, l=val_lbl: l.setText(str(v)))
            hlay.addWidget(slider)
            hlay.addWidget(val_lbl)
            return container
        elif ptype == "combo":
            w = QComboBox()
            for opt in param.get("options", []):
                w.addItem(opt)
            default = param.get("default", "")
            idx = w.findText(default)
            if idx >= 0:
                w.setCurrentIndex(idx)
            w.setFixedWidth(160)
            return w
        elif ptype in ("text", "secret"):
            w = QLineEdit()
            w.setPlaceholderText(f"Enter {param['label']}")
            if ptype == "secret":
                w.setEchoMode(QLineEdit.EchoMode.Password)
            w.setStyleSheet(
                "background:#1A1A2E; color:#E0E0FF; border:1px solid #3A3A5A; "
                "border-radius:3px; padding:4px; font-family:monospace; font-size:11px;"
            )
            w.setFixedWidth(280)
            return w
        return None

    def _on_toggle(self, state: int):
        flag_key = self._module.get("flag", "")
        enabled = state == Qt.CheckState.Checked.value
        if self._flags and flag_key:
            if enabled:
                self._flags.enable(flag_key)
            else:
                self._flags.disable(flag_key)

        # Auto-enable dependencies
        auto_enables = self._module.get("auto_enables", [])
        if enabled and auto_enables and self._flags:
            for dep_flag in auto_enables:
                if not self._flags.is_enabled(dep_flag):
                    self._flags.enable(dep_flag)
                    # Show notification
                    notif = QLabel(f"✓ Auto-activated: {dep_flag}")
                    notif.setStyleSheet(f"color:#FFA500; font-size:10px;")
                    self.layout().addWidget(notif)
                    QTimer.singleShot(5000, notif.deleteLater)


class LayerPanel(QWidget):
    """Full panel for one layer with sub-tabs per module."""

    def __init__(self, layer_num: int, layer_name: str, color: str,
                 modules: list, flags_controller=None, parent=None):
        super().__init__(parent)
        self._num = layer_num
        self._name = layer_name
        self._color = color
        self._modules = modules
        self._flags = flags_controller
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Layer header
        hdr = QLabel(f"Layer {self._num}: {self._name}")
        hdr.setStyleSheet(
            f"color:{self._color}; font-size:15px; font-weight:bold; padding:4px 0;"
        )
        root.addWidget(hdr)

        shortcut_lbl = QLabel(
            f"Keyboard shortcut: Shift+Alt+{'0' if self._num == 10 else self._num}"
        )
        shortcut_lbl.setStyleSheet(f"color:{TEXT_MUTED}; font-size:10px;")
        root.addWidget(shortcut_lbl)

        # Module tabs (scrollable)
        module_tabs = QTabWidget()
        module_tabs.setStyleSheet(
            f"QTabBar::tab {{ color:{TEXT_MUTED}; background:#1A1A2E; "
            f"padding:5px 10px; font-size:10px; }}"
            f"QTabBar::tab:selected {{ color:{self._color}; "
            f"border-bottom:2px solid {self._color}; }}"
            "QTabWidget::pane { border:1px solid #2A2A4A; }"
        )

        for mod in self._modules:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            panel = ModulePanel(mod, self._flags)
            scroll.setWidget(panel)
            scroll.setStyleSheet("border:none;")
            # Short name for tab label
            short_name = mod["name"].split(". ", 1)[-1]
            if len(short_name) > 22:
                short_name = short_name[:20] + "…"
            module_tabs.addTab(scroll, short_name)

        root.addWidget(module_tabs, stretch=1)


class LayersSettingsPanel(QWidget):
    """
    Main 'Settings >> Configuration >> Layers' panel.
    Shows all 10 layers with Shift+Alt+N keyboard access.
    """

    def __init__(self, flags_controller=None, parent=None):
        super().__init__(parent)
        self._flags = flags_controller
        self._layer_tabs: Dict[int, int] = {}  # layer_num → tab index
        self._setup_ui()
        self._setup_shortcuts()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Title
        title = QLabel("⚙  Configuration  ·  System Layers")
        title.setStyleSheet(
            f"color:{ACCENT_BLUE}; font-size:17px; font-weight:bold; padding:10px 12px 4px;"
        )
        root.addWidget(title)

        sub = QLabel(
            "Each layer groups related modules. Use Shift+Alt+1…0 to jump directly to any layer."
        )
        sub.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px; padding:0 12px 8px;")
        root.addWidget(sub)

        # Layer tabs
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.West)
        self._tabs.setStyleSheet(
            "QTabBar::tab { color:#8888AA; background:#0D0D1A; "
            "padding:8px 6px; font-size:11px; min-width:180px; }"
            "QTabBar::tab:selected { color:#00D4FF; background:#12121E; "
            "border-left:3px solid #00D4FF; font-weight:bold; }"
            "QTabWidget::pane { border:none; background:#0A0A12; }"
        )

        for i, (num, name, color, modules) in enumerate(LAYERS):
            panel = LayerPanel(num, name, color, modules, self._flags)
            tab_name = f"{num}. {name}"
            self._tabs.addTab(panel, tab_name)
            self._layer_tabs[num] = i

        root.addWidget(self._tabs, stretch=1)

    def _setup_shortcuts(self):
        """Shift+Alt+1…0 to jump to each layer."""
        for num in range(1, 11):
            key = "0" if num == 10 else str(num)
            sc = QShortcut(QKeySequence(f"Shift+Alt+{key}"), self)
            sc.activated.connect(lambda n=num: self._jump_to_layer(n))

    def _jump_to_layer(self, layer_num: int):
        idx = self._layer_tabs.get(layer_num, 0)
        self._tabs.setCurrentIndex(idx)
        # Make parent visible if hidden
        parent = self.parent()
        if parent and hasattr(parent, "show"):
            parent.show()
        self.show()
        self.raise_()
