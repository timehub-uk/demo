"""
ML Layer Results Collector.

Collects current state/results from all ML services grouped by the
10-layer architecture.  Used by both the REST API and the Telegram bot
so that the formatting logic stays in one place.

Usage:
    from ml.layer_results import get_layer_results, LAYER_META

    data = get_layer_results(4, services)   # Layer 4 – Research & Quant
    all_layers = {n: get_layer_results(n, services) for n in range(1, 11)}
"""

from __future__ import annotations

from typing import Any

# ── Layer metadata ────────────────────────────────────────────────────────────

LAYER_META: dict[int, dict] = {
    1: {"name": "Infrastructure & Orchestration", "color": "#7B68EE"},
    2: {"name": "Market Data Ingestion",          "color": "#00CED1"},
    3: {"name": "Data Engineering & Storage",     "color": "#32CD32"},
    4: {"name": "Research & Quant",               "color": "#FF8C00"},
    5: {"name": "Alpha & Signal",                 "color": "#FF6B6B"},
    6: {"name": "Risk & Capital Management",      "color": "#DC143C"},
    7: {"name": "Execution",                      "color": "#1E90FF"},
    8: {"name": "Token & Contract Safety",        "color": "#FFD700"},
    9: {"name": "Monitoring & Reporting",         "color": "#98FB98"},
   10: {"name": "Governance & Oversight",         "color": "#9370DB"},
}


# ── Per-layer collectors ──────────────────────────────────────────────────────

def _layer1(services: dict) -> dict:
    """Infrastructure – health / config snapshot."""
    result: dict[str, Any] = {"tools": {}}
    try:
        from utils.threading_manager import get_thread_manager
        result["tools"]["thread_manager"] = get_thread_manager().system_stats()
    except Exception:
        pass
    return result


def _layer2(services: dict) -> dict:
    """Market Data – whale watcher snapshot (live feed indicator)."""
    result: dict[str, Any] = {"tools": {}}
    ww = services.get("whale_watcher")
    if ww:
        try:
            result["tools"]["whale_watcher"] = {
                "status": "running" if getattr(ww, "_running", False) else "idle",
                "recent_events": [
                    {
                        "symbol": getattr(e, "symbol", ""),
                        "type":   getattr(e, "event_type", ""),
                        "volume_usd": float(getattr(e, "volume_usd", 0)),
                        "confidence": float(getattr(e, "confidence", 0)),
                    }
                    for e in (getattr(ww, "recent_events", None) or [])[-10:]
                ],
            }
        except Exception:
            pass

    sent = services.get("sentiment")
    if sent:
        try:
            snap = sent.get_snapshot() if hasattr(sent, "get_snapshot") else {}
            result["tools"]["sentiment_analyser"] = snap or {"status": "running"}
        except Exception:
            pass

    return result


def _layer3(services: dict) -> dict:
    """Data Engineering – cache/DB health indicators."""
    result: dict[str, Any] = {"tools": {}}
    try:
        from db.redis_client import RedisClient
        rc = RedisClient()
        result["tools"]["redis_cache"] = {
            "status": "connected" if rc.ping() else "disconnected"
        }
    except Exception:
        pass
    return result


def _layer4(services: dict) -> dict:
    """Research & Quant – regime, monte carlo, walk-forward, backtest, port-opt, mutation."""
    result: dict[str, Any] = {"tools": {}}

    # Regime detector
    rd = services.get("regime_detector")
    if rd:
        try:
            snap = rd.get_regime() if hasattr(rd, "get_regime") else None
            if snap:
                result["tools"]["regime_detector"] = {
                    "regime":     getattr(snap, "regime", str(snap)),
                    "confidence": float(getattr(snap, "confidence", 0)),
                }
        except Exception:
            pass

    # Monte Carlo
    mc = services.get("monte_carlo")
    if mc:
        try:
            r = mc.last_result if hasattr(mc, "last_result") else None
            if r:
                result["tools"]["monte_carlo"] = {
                    "p10": float(getattr(r, "p10", 0)),
                    "p50": float(getattr(r, "p50", 0)),
                    "p90": float(getattr(r, "p90", 0)),
                    "risk_of_ruin_pct": float(getattr(r, "risk_of_ruin_pct", 0)),
                }
        except Exception:
            pass

    # Walk-forward
    wf = services.get("walk_forward")
    if wf:
        try:
            r = wf.last_report if hasattr(wf, "last_report") else None
            if r:
                result["tools"]["walk_forward"] = {
                    "oos_sharpe":   float(getattr(r, "oos_sharpe", 0)),
                    "oos_win_rate": float(getattr(r, "oos_win_rate", 0)),
                    "passed":       bool(getattr(r, "passed", False)),
                }
        except Exception:
            pass

    # Portfolio optimiser
    po = services.get("port_opt")
    if po:
        try:
            lr = getattr(po, "_last_result", None)
            if lr:
                result["tools"]["portfolio_optimiser"] = {
                    "method":               lr.method,
                    "sharpe_ratio":         round(lr.sharpe_ratio, 3),
                    "expected_return_pct":  round(lr.expected_return_pct, 2),
                    "expected_vol_pct":     round(lr.expected_volatility_pct, 2),
                    "rebalance_needed":     lr.rebalance_needed,
                    "top_weights": dict(
                        sorted(lr.weights.items(), key=lambda x: -x[1])[:5]
                    ),
                }
        except Exception:
            pass

    # Strategy mutation lab
    sml = services.get("mutation_lab")
    if sml:
        try:
            stats = sml.get_stats() if hasattr(sml, "get_stats") else {}
            result["tools"]["strategy_mutation_lab"] = stats or {"status": "running"}
        except Exception:
            pass

    return result


def _layer5(services: dict) -> dict:
    """Alpha & Signal – predictor, ensemble, signal council, MTF filter, scanners."""
    result: dict[str, Any] = {"tools": {}}

    # ML Predictor
    pred = services.get("predictor")
    if pred:
        try:
            from db.redis_client import RedisClient
            rc = RedisClient()
            # Grab top signals from Redis cache
            signals = {}
            syms = getattr(pred, "_symbols", []) or []
            for sym in list(syms)[:10]:
                s = rc.get_ml_signal(sym)
                if s:
                    signals[sym] = s
            result["tools"]["ml_predictor"] = {
                "tracked_symbols": len(syms),
                "latest_signals": signals,
            }
        except Exception:
            result["tools"]["ml_predictor"] = {"status": "running"}

    # Ensemble
    ens = services.get("ensemble")
    if ens:
        try:
            weights = ens.get_weights() if hasattr(ens, "get_weights") else {}
            last    = ens.last_signal  if hasattr(ens, "last_signal")  else None
            result["tools"]["ensemble"] = {
                "adaptive_weights": weights,
                "last_signal": last,
            }
        except Exception:
            pass

    # Signal Council
    sc = services.get("signal_council")
    if sc:
        try:
            snap = sc.get_summary() if hasattr(sc, "get_summary") else {}
            result["tools"]["signal_council"] = snap or {"status": "active"}
        except Exception:
            pass

    # MTF Filter
    mtf = services.get("mtf_filter")
    if mtf:
        try:
            snap = mtf.get_confluence() if hasattr(mtf, "get_confluence") else {}
            result["tools"]["mtf_filter"] = snap or {"status": "active"}
        except Exception:
            pass

    # Accumulation detector
    acc = services.get("accumulation_detector")
    if acc:
        try:
            top = acc.get_all() if hasattr(acc, "get_all") else []
            result["tools"]["accumulation_detector"] = {
                "alerts": [
                    {
                        "symbol": getattr(r, "symbol", ""),
                        "score":  round(float(getattr(r, "score", 0)), 3),
                        "tier":   getattr(r, "tier", ""),
                    }
                    for r in (top or [])[:5]
                ]
            }
        except Exception:
            pass

    # Liquidity depth analyzer
    liq = services.get("liquidity_analyzer")
    if liq:
        try:
            top = liq.get_all() if hasattr(liq, "get_all") else []
            result["tools"]["liquidity_analyzer"] = {
                "results": [
                    {
                        "symbol": getattr(r, "symbol", ""),
                        "score":  round(float(getattr(r, "score", 0)), 3),
                    }
                    for r in (top or [])[:5]
                ]
            }
        except Exception:
            pass

    # Breakout detector
    brk = services.get("breakout_detector")
    if brk:
        try:
            top = brk.get_all() if hasattr(brk, "get_all") else []
            result["tools"]["breakout_detector"] = {
                "breakouts": [
                    {
                        "symbol": getattr(r, "symbol", ""),
                        "stage":  getattr(r, "stage", 0),
                        "score":  round(float(getattr(r, "score", 0)), 3),
                    }
                    for r in (top or [])[:5]
                ]
            }
        except Exception:
            pass

    # Trend scanner
    ts = services.get("trend_scanner")
    if ts:
        try:
            snaps = ts.get_all() if hasattr(ts, "get_all") else {}
            result["tools"]["trend_scanner"] = {
                "symbols": {
                    sym: {
                        "trend":     getattr(s, "trend", ""),
                        "strength":  round(float(getattr(s, "strength", 0)), 3),
                    }
                    for sym, s in list((snaps or {}).items())[:5]
                }
            }
        except Exception:
            pass

    # Pair scanner
    ps = services.get("pair_scanner")
    if ps:
        try:
            pairs = ps.get_pairs() if hasattr(ps, "get_pairs") else []
            result["tools"]["pair_scanner"] = {
                "active_pairs": list(pairs or [])[:10]
            }
        except Exception:
            pass

    return result


def _layer6(services: dict) -> dict:
    """Risk & Capital Management – dynamic risk engine."""
    result: dict[str, Any] = {"tools": {}}
    drm = services.get("dynamic_risk")
    if drm:
        try:
            snap = drm.get_status() if hasattr(drm, "get_status") else None
            result["tools"]["dynamic_risk"] = snap or {
                "status": "running",
                "circuit_breaker": getattr(drm, "circuit_breaker_active", False),
                "current_risk_pct": float(getattr(drm, "current_risk_pct", 0)),
            }
        except Exception:
            pass
    return result


def _layer7(services: dict) -> dict:
    """Execution – auto-trader, arbitrage detector."""
    result: dict[str, Any] = {"tools": {}}
    at = services.get("auto_trader")
    if at:
        try:
            result["tools"]["auto_trader"] = {
                "mode":    str(getattr(at, "mode", "UNKNOWN")),
                "running": getattr(at, "_running", False),
            }
        except Exception:
            pass
    arb = services.get("arb_detector")
    if arb:
        try:
            opps = arb.get_opportunities() if hasattr(arb, "get_opportunities") else []
            result["tools"]["arbitrage_detector"] = {
                "open_opportunities": len(opps or []),
                "top": [
                    {
                        "pair":   getattr(o, "pair", ""),
                        "spread": round(float(getattr(o, "spread_pct", 0)), 4),
                    }
                    for o in (opps or [])[:3]
                ],
            }
        except Exception:
            pass
    return result


def _layer8(services: dict) -> dict:
    """Token & Contract Safety – contract analyzer, honeypot, rug-pull."""
    result: dict[str, Any] = {"tools": {}}
    for key, label in [
        ("contract_analyzer",    "contract_analyzer"),
        ("honeypot_detector",    "honeypot_detector"),
        ("liq_lock_analyzer",    "liquidity_lock_analyzer"),
        ("wallet_graph_analyzer","wallet_graph_analyzer"),
        ("rugpull_scorer",       "rugpull_scorer"),
    ]:
        svc = services.get(key)
        if svc:
            try:
                snap = svc.get_summary() if hasattr(svc, "get_summary") else {}
                result["tools"][label] = snap or {"status": "ready"}
            except Exception:
                result["tools"][label] = {"status": "ready"}
    return result


def _layer9(services: dict) -> dict:
    """Monitoring & Reporting – forecast tracker, trade journal."""
    result: dict[str, Any] = {"tools": {}}

    ft = services.get("forecast_tracker")
    if ft:
        try:
            acc = ft.get_accuracy() if hasattr(ft, "get_accuracy") else {}
            result["tools"]["forecast_tracker"] = acc or {"status": "tracking"}
        except Exception:
            pass

    tj = services.get("trade_journal")
    if tj:
        try:
            snap = tj.get_summary() if hasattr(tj, "get_summary") else {}
            result["tools"]["trade_journal"] = snap or {"status": "running"}
        except Exception:
            pass

    return result


def _layer10(services: dict) -> dict:
    """Governance & Oversight – no live data endpoints."""
    return {"tools": {"status": "Governance layer — managed via Settings panel"}}


_COLLECTORS = {
    1: _layer1,  2: _layer2,  3: _layer3,  4: _layer4,
    5: _layer5,  6: _layer6,  7: _layer7,  8: _layer8,
    9: _layer9, 10: _layer10,
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_layer_results(layer: int, services: dict) -> dict:
    """
    Return current ML results for *layer* (1-10).

    Returns a dict:
        {
            "layer": int,
            "name":  str,
            "color": str,
            "tools": { tool_name: {...result...}, ... }
        }
    """
    meta = LAYER_META.get(layer, {"name": f"Layer {layer}", "color": "#FFFFFF"})
    collector = _COLLECTORS.get(layer, lambda _: {"tools": {}})
    try:
        data = collector(services)
    except Exception:
        data = {"tools": {}}
    return {
        "layer": layer,
        "name":  meta["name"],
        "color": meta["color"],
        **data,
    }


def format_layer_text(layer: int, services: dict) -> str:
    """
    Return a human-readable Telegram/plain-text summary for one layer.
    """
    data = get_layer_results(layer, services)
    tools = data.get("tools", {})
    lines = [f"<b>Layer {layer} – {data['name']}</b>"]
    if not tools:
        lines.append("  No live results available.")
        return "\n".join(lines)

    for tool_name, result in tools.items():
        lines.append(f"\n<b>{tool_name.replace('_', ' ').title()}</b>")
        if isinstance(result, dict):
            for k, v in result.items():
                if isinstance(v, (list, dict)):
                    if v:
                        lines.append(f"  {k}: {_truncate(str(v), 80)}")
                elif v is not None:
                    lines.append(f"  {k}: {v}")
        else:
            lines.append(f"  {result}")

    return "\n".join(lines)


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 3] + "..."
