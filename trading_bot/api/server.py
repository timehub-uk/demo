"""
Embedded REST API server (Flask-based) running in a background thread.
Allows external apps, dashboards, and automation tools to interact
with BinanceML Pro via HTTP.

Endpoints:
  GET  /api/v1/status           – System status
  GET  /api/v1/portfolio        – Current portfolio
  GET  /api/v1/signals          – Latest ML signals
  GET  /api/v1/trades           – Recent trades
  GET  /api/v1/orderbook/{sym}  – Live order book
  GET  /api/v1/ticker/{sym}     – Live ticker
  POST /api/v1/order            – Place an order
  DELETE /api/v1/order/{id}     – Cancel an order
  GET  /api/v1/ml/status        – ML training status
  POST /api/v1/ml/predict       – On-demand prediction
  GET  /api/v1/tax/monthly      – Monthly tax summary
  GET  /api/v1/log              – Recent Intel Log entries
  POST /api/v1/webhook/register – Register a webhook endpoint
"""

from __future__ import annotations

import threading
import time
from functools import wraps
from typing import Any, Callable, Optional

from flask import Flask, jsonify, request, abort
from loguru import logger
from sqlalchemy import select

from config import get_settings
from db.redis_client import RedisClient
from utils.logger import get_intel_logger

_api_server: "APIServer | None" = None


def _json_ok(data: Any, status: int = 200):
    return jsonify({"ok": True, "data": data}), status


def _json_err(msg: str, status: int = 400):
    return jsonify({"ok": False, "error": msg}), status


def require_token(f: Callable):
    """Bearer-token auth for all API endpoints.

    Token resolution order:
      1. Settings → Notifications → API Key  (if set)
      2. First 16 chars of the Binance API key  (fallback)

    Set your own key in Settings → Notifications → API Key to use a
    dedicated token instead of the derived Binance key fragment.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        settings = get_settings()
        expected = settings.effective_api_key()
        if not auth.startswith("Bearer ") or auth[7:] != expected:
            abort(401)
        return f(*args, **kwargs)
    return decorated


def create_app(engine=None, portfolio=None, predictor=None,
               order_manager=None, tax_calc=None, services: dict | None = None) -> Flask:
    """Factory – creates Flask app with all routes bound to live services."""
    app = Flask("BinanceMLPro-API")
    app.config["JSON_SORT_KEYS"] = False
    redis_client = RedisClient()
    intel = get_intel_logger()
    _services = services or {}

    # ── Status ─────────────────────────────────────────────────────────
    @app.route("/api/v1/status")
    def status():
        from utils.threading_manager import get_thread_manager
        stats = get_thread_manager().system_stats()
        intel.api("APIServer", "GET /api/v1/status")
        return _json_ok({
            "service": "BinanceML Pro",
            "version": "1.0.0",
            "engine_mode": str(engine.mode) if engine else "offline",
            "system": stats,
            "timestamp": time.time(),
        })

    # ── Portfolio ───────────────────────────────────────────────────────
    @app.route("/api/v1/portfolio")
    @require_token
    def get_portfolio():
        data = redis_client.get_portfolio() or {}
        if portfolio:
            snap = portfolio.refresh()
            data = {
                "total_usdt": float(getattr(snap, "total_usdt", 0)),
                "total_gbp": float(getattr(snap, "total_gbp", 0)),
                "unrealized_pnl": float(getattr(snap, "unrealized_pnl", 0)),
            }
        intel.api("APIServer", "GET /api/v1/portfolio")
        return _json_ok(data)

    # ── Signals ─────────────────────────────────────────────────────────
    @app.route("/api/v1/signals")
    @require_token
    def get_signals():
        symbol = request.args.get("symbol")
        signals = []
        if predictor and symbol:
            sig = redis_client.get_ml_signal(symbol) or predictor.predict(symbol)
            signals = [sig] if sig else []
        intel.api("APIServer", f"GET /api/v1/signals symbol={symbol}")
        return _json_ok(signals)

    # ── Trades ──────────────────────────────────────────────────────────
    @app.route("/api/v1/trades")
    @require_token
    def get_trades():
        from db.postgres import get_db
        from db.models import Trade
        limit = int(request.args.get("limit", 50))
        symbol = request.args.get("symbol")
        try:
            with get_db() as db:
                q = select(Trade).order_by(Trade.created_at.desc()).limit(limit)
                if symbol:
                    q = q.where(Trade.symbol == symbol)
                trades = db.execute(q).scalars().all()
            rows = [
                {
                    "id": str(t.id),
                    "symbol": t.symbol,
                    "side": t.side,
                    "status": t.status,
                    "quantity": float(t.quantity),
                    "price": float(t.price),
                    "created_at": t.created_at.isoformat(),
                    "is_automated": t.is_automated,
                    "ml_signal": t.ml_signal,
                    "ml_confidence": t.ml_confidence,
                }
                for t in trades
            ]
        except Exception as exc:
            return _json_err(str(exc))
        intel.api("APIServer", f"GET /api/v1/trades count={len(rows)}")
        return _json_ok(rows)

    # ── Order book ──────────────────────────────────────────────────────
    @app.route("/api/v1/orderbook/<symbol>")
    @require_token
    def get_orderbook(symbol: str):
        data = redis_client.get_orderbook(symbol.upper())
        if data is None:
            return _json_err("Order book not available", 404)
        intel.api("APIServer", f"GET /api/v1/orderbook/{symbol}")
        return _json_ok(data)

    # ── Ticker ──────────────────────────────────────────────────────────
    @app.route("/api/v1/ticker/<symbol>")
    def get_ticker(symbol: str):
        data = redis_client.get_ticker(symbol.upper())
        if data is None:
            return _json_err("Ticker not available", 404)
        return _json_ok(data)

    # ── Place order ─────────────────────────────────────────────────────
    @app.route("/api/v1/order", methods=["POST"])
    @require_token
    def place_order():
        body = request.get_json(silent=True) or {}
        required = ["symbol", "side", "quantity"]
        for field in required:
            if field not in body:
                return _json_err(f"Missing field: {field}")
        if not order_manager:
            return _json_err("Order manager not available", 503)
        from decimal import Decimal
        settings = get_settings()
        order = order_manager.place_limit_order(
            symbol=body["symbol"].upper(),
            side=body["side"].upper(),
            quantity=Decimal(str(body["quantity"])),
            price=Decimal(str(body.get("price", 0))),
            user_id=body.get("user_id", "api"),
            is_automated=False,
        )
        if order:
            intel.api("APIServer", f"POST /api/v1/order {body['symbol']} {body['side']}", body)
            return _json_ok(order, 201)
        return _json_err("Order placement failed", 500)

    # ── Cancel order ────────────────────────────────────────────────────
    @app.route("/api/v1/order/<order_id>", methods=["DELETE"])
    @require_token
    def cancel_order(order_id: str):
        symbol = request.args.get("symbol", "")
        if not order_manager:
            return _json_err("Order manager not available", 503)
        ok = order_manager.cancel_order(symbol, order_id)
        intel.api("APIServer", f"DELETE /api/v1/order/{order_id}")
        return _json_ok({"cancelled": ok})

    # ── ML Status ───────────────────────────────────────────────────────
    @app.route("/api/v1/ml/status")
    def ml_status():
        prog = redis_client.get_training_progress()
        return _json_ok(prog or {"status": "idle"})

    # ── ML Predict ─────────────────────────────────────────────────────
    @app.route("/api/v1/ml/predict", methods=["POST"])
    @require_token
    def ml_predict():
        body = request.get_json(silent=True) or {}
        symbol = body.get("symbol", "")
        if not symbol:
            return _json_err("Missing symbol")
        if not predictor:
            return _json_err("Predictor not available", 503)
        sig = predictor.predict(symbol.upper())
        intel.api("APIServer", f"POST /api/v1/ml/predict {symbol}")
        return _json_ok(sig)

    # ── ML Layer list ───────────────────────────────────────────────────
    @app.route("/api/v1/ml/layers")
    @require_token
    def ml_layers():
        """List all 10 layers with name and available tool count."""
        from ml.layer_results import LAYER_META, get_layer_results
        result = []
        for n, meta in LAYER_META.items():
            data = get_layer_results(n, _services)
            result.append({
                "layer": n,
                "name":  meta["name"],
                "color": meta["color"],
                "tool_count": len(data.get("tools", {})),
            })
        intel.api("APIServer", "GET /api/v1/ml/layers")
        return _json_ok(result)

    # ── ML Layer results ────────────────────────────────────────────────
    @app.route("/api/v1/ml/layer/<int:layer_n>")
    @require_token
    def ml_layer(layer_n: int):
        """Return current results for all ML tools in the given layer (1-10)."""
        if layer_n < 1 or layer_n > 10:
            return _json_err("Layer must be 1–10", 400)
        from ml.layer_results import get_layer_results
        data = get_layer_results(layer_n, _services)
        intel.api("APIServer", f"GET /api/v1/ml/layer/{layer_n}")
        return _json_ok(data)

    # ── Tax summary ─────────────────────────────────────────────────────
    @app.route("/api/v1/tax/monthly")
    @require_token
    def tax_monthly():
        year = int(request.args.get("year", time.localtime().tm_year))
        month = int(request.args.get("month", time.localtime().tm_mon))
        if not tax_calc:
            return _json_err("Tax calculator not available", 503)
        data = tax_calc.monthly_summary(year, month)
        intel.api("APIServer", f"GET /api/v1/tax/monthly {year}-{month:02d}")
        return _json_ok(data)

    # ── Intel Log ───────────────────────────────────────────────────────
    @app.route("/api/v1/log")
    @require_token
    def intel_log():
        n = int(request.args.get("n", 100))
        cat = request.args.get("category")
        entries = intel.recent(n=n, category=cat)
        return _json_ok([e.to_dict() for e in entries])

    # ── Webhook registration ────────────────────────────────────────────
    @app.route("/api/v1/webhook/register", methods=["POST"])
    @require_token
    def register_webhook():
        body = request.get_json(silent=True) or {}
        url = body.get("url")
        events = body.get("events", ["TRADE", "SIGNAL"])
        if not url:
            return _json_err("Missing webhook URL")
        from .webhooks import get_webhook_manager
        wm = get_webhook_manager()
        wm.register(url, events)
        intel.webhook("APIServer", f"Webhook registered: {url} events={events}")
        return _json_ok({"registered": True, "url": url, "events": events}, 201)

    @app.route("/api/v1/webhook/list")
    @require_token
    def list_webhooks():
        from .webhooks import get_webhook_manager
        return _json_ok(get_webhook_manager().list_webhooks())

    # ── Health ──────────────────────────────────────────────────────────
    @app.route("/health")
    def health():
        return _json_ok({"healthy": True})

    return app


class APIServer:
    """Runs the Flask API in a background daemon thread."""

    def __init__(self) -> None:
        self._app: Optional[Flask] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._host = "127.0.0.1"
        self._port = 8765

    def start(self, host: str = "127.0.0.1", port: int = 8765,
              services: dict | None = None, **kwargs) -> None:
        if self._running:
            return
        self._host = host
        self._port = port
        self._app = create_app(services=services, **kwargs)
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="api-server"
        )
        self._thread.start()
        logger.info(f"API server started at http://{host}:{port}")

    def _run(self) -> None:
        import logging
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.ERROR)
        self._app.run(host=self._host, port=self._port, threaded=True, use_reloader=False)

    def stop(self) -> None:
        self._running = False

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"


_api_server_singleton: APIServer | None = None


def get_api_server() -> APIServer:
    global _api_server_singleton
    if _api_server_singleton is None:
        _api_server_singleton = APIServer()
    return _api_server_singleton
