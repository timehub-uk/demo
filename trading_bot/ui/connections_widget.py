"""
Connections Widget – Live health dashboard for all external services.

Shows real-time status, latency, and control actions for:
  • Binance REST API + WebSocket
  • PostgreSQL database
  • Redis cache
  • Telegram bot
  • REST API server
  • Voice alerts

Each row shows: SVG status dot | Service name | Status text | Latency | Action button
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFrame, QScrollArea, QGridLayout, QSizePolicy,
    QProgressBar,
)

from ui.styles import (
    ACCENT, ACCENT2, GREEN, GREEN2, RED, ORANGE, YELLOW,
    BG0, BG2, BG3, BG4, BG5, BORDER, BORDER2, FG0, FG1, FG2, GLOW,
)
from ui.icons import svg_pixmap


# ── Service row widget ────────────────────────────────────────────────────────

class ServiceRow(QFrame):
    """Single connection row: icon | name | status | latency | action."""

    reconnect_requested = pyqtSignal(str)   # service name

    def __init__(self, service_id: str, icon_name: str, display_name: str, parent=None) -> None:
        super().__init__(parent)
        self.service_id = service_id
        self._icon_name = icon_name
        self.setFixedHeight(56)
        self.setStyleSheet(f"""
            ServiceRow {{
                background: {BG3};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
            ServiceRow:hover {{
                border-color: {BORDER2};
                background: {BG4};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(12)

        # Status dot
        self.dot_lbl = QLabel()
        self.dot_lbl.setFixedSize(14, 14)
        self._set_dot("grey")
        layout.addWidget(self.dot_lbl)

        # Service icon
        icon_lbl = QLabel()
        icon_lbl.setPixmap(svg_pixmap(icon_name, FG2, 18))
        icon_lbl.setFixedSize(20, 20)
        layout.addWidget(icon_lbl)

        # Name
        name_lbl = QLabel(display_name)
        name_lbl.setStyleSheet(f"color:{FG0}; font-weight:700; font-size:12px;")
        name_lbl.setFixedWidth(150)
        layout.addWidget(name_lbl)

        # Status text
        self.status_lbl = QLabel("Checking…")
        self.status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        self.status_lbl.setMinimumWidth(160)
        layout.addWidget(self.status_lbl)

        # Latency bar
        self.latency_bar = QProgressBar()
        self.latency_bar.setFixedWidth(100)
        self.latency_bar.setFixedHeight(6)
        self.latency_bar.setRange(0, 500)
        self.latency_bar.setValue(0)
        self.latency_bar.setTextVisible(False)
        layout.addWidget(self.latency_bar)

        # Latency label
        self.latency_lbl = QLabel("—")
        self.latency_lbl.setStyleSheet(f"color:{FG2}; font-size:10px; font-family:monospace; min-width:55px;")
        layout.addWidget(self.latency_lbl)

        layout.addStretch()

        # Last checked
        self.checked_lbl = QLabel("")
        self.checked_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        layout.addWidget(self.checked_lbl)

        # Action button
        self.action_btn = QPushButton("Reconnect")
        self.action_btn.setFixedSize(90, 26)
        self.action_btn.setStyleSheet(f"""
            QPushButton {{
                background:{BG5}; color:{FG2}; border:1px solid {BORDER};
                border-radius:4px; font-size:10px; font-weight:600;
            }}
            QPushButton:hover {{ color:{ACCENT}; border-color:{ACCENT}; background:{GLOW}; }}
        """)
        self.action_btn.clicked.connect(lambda: self.reconnect_requested.emit(self.service_id))
        layout.addWidget(self.action_btn)

    def _set_dot(self, state: str) -> None:
        """state: 'green' | 'yellow' | 'red' | 'grey'"""
        pix = svg_pixmap(f"dot_{state}", size=14)
        self.dot_lbl.setPixmap(pix)

    def set_connected(self, latency_ms: float | None = None) -> None:
        self._set_dot("green")
        self.status_lbl.setText("Connected")
        self.status_lbl.setStyleSheet(f"color:{GREEN}; font-size:11px; font-weight:600;")
        if latency_ms is not None:
            self.latency_bar.setValue(min(500, int(latency_ms)))
            col = GREEN if latency_ms < 100 else YELLOW if latency_ms < 300 else RED
            self.latency_lbl.setText(f"{latency_ms:.0f} ms")
            self.latency_lbl.setStyleSheet(f"color:{col}; font-size:10px; font-family:monospace; min-width:55px;")
        self.checked_lbl.setText(_now())

    def set_warning(self, msg: str = "Degraded") -> None:
        self._set_dot("yellow")
        self.status_lbl.setText(msg)
        self.status_lbl.setStyleSheet(f"color:{YELLOW}; font-size:11px; font-weight:600;")
        self.checked_lbl.setText(_now())

    def set_disconnected(self, msg: str = "Disconnected") -> None:
        self._set_dot("red")
        self.status_lbl.setText(msg)
        self.status_lbl.setStyleSheet(f"color:{RED}; font-size:11px; font-weight:600;")
        self.latency_bar.setValue(0)
        self.latency_lbl.setText("—")
        self.latency_lbl.setStyleSheet(f"color:{FG2}; font-size:10px; font-family:monospace; min-width:55px;")
        self.checked_lbl.setText(_now())

    def set_checking(self) -> None:
        self._set_dot("yellow")
        self.status_lbl.setText("Checking…")
        self.status_lbl.setStyleSheet(f"color:{YELLOW}; font-size:11px;")


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ── Stat card ─────────────────────────────────────────────────────────────────

class StatCard(QFrame):
    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(72)
        self.setStyleSheet(f"""
            StatCard {{
                background: {BG3};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(2)

        self.val_lbl = QLabel("—")
        self.val_lbl.setStyleSheet(f"color:{ACCENT}; font-size:22px; font-weight:700; font-family:monospace;")
        layout.addWidget(self.val_lbl)

        key_lbl = QLabel(label)
        key_lbl.setStyleSheet(f"color:{FG2}; font-size:10px; letter-spacing:1px; text-transform:uppercase;")
        layout.addWidget(key_lbl)

    def set_value(self, val: str, color: str = ACCENT) -> None:
        self.val_lbl.setText(val)
        self.val_lbl.setStyleSheet(
            f"color:{color}; font-size:22px; font-weight:700; font-family:monospace;"
        )


# ── Main widget ───────────────────────────────────────────────────────────────

class ConnectionsWidget(QWidget):
    """
    Live connection health panel.
    Auto-checks all services every 30 seconds, or on demand.
    """

    _results_ready = pyqtSignal(dict)

    def __init__(
        self,
        binance_client=None,
        engine=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._client = binance_client
        self._engine = engine
        self._setup_ui()

        self._results_ready.connect(self._apply_results)
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._check_all)
        self._check_timer.start(30_000)
        QTimer.singleShot(500, self._check_all)

    # ── UI construction ────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(16)

        # ── Header ────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("CONNECTION HEALTH")
        title.setStyleSheet(f"color:{ACCENT}; font-size:13px; font-weight:700; letter-spacing:3px;")
        hdr.addWidget(title)
        hdr.addStretch()

        self.check_all_btn = QPushButton("⟳  Check All")
        self.check_all_btn.setObjectName("btn_primary")
        self.check_all_btn.setFixedSize(120, 30)
        self.check_all_btn.clicked.connect(self._check_all)
        hdr.addWidget(self.check_all_btn)

        self.last_check_lbl = QLabel("Last check: —")
        self.last_check_lbl.setStyleSheet(f"color:{FG2}; font-size:10px;")
        hdr.addWidget(self.last_check_lbl)
        root.addLayout(hdr)

        # ── Stat cards ────────────────────────────────────────────────
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        self.card_online    = StatCard("Services Online")
        self.card_offline   = StatCard("Offline")
        self.card_latency   = StatCard("Avg Latency")
        self.card_uptime    = StatCard("Session Uptime")
        for c in (self.card_online, self.card_offline, self.card_latency, self.card_uptime):
            cards_row.addWidget(c)
        root.addLayout(cards_row)

        # ── Service rows ──────────────────────────────────────────────
        services_grp = QGroupBox("External Services")
        sg_layout = QVBoxLayout(services_grp)
        sg_layout.setSpacing(6)

        self.row_binance  = ServiceRow("binance",  "chart",    "Binance REST API")
        self.row_ws       = ServiceRow("ws",       "bolt",     "Binance WebSocket")
        self.row_postgres = ServiceRow("postgres", "database", "PostgreSQL")
        self.row_redis    = ServiceRow("redis",    "redis",    "Redis Cache")
        self.row_telegram = ServiceRow("telegram", "telegram", "Telegram Bot")
        self.row_api      = ServiceRow("api",      "api",      "REST API Server")
        self.row_voice    = ServiceRow("voice",    "bolt",     "Voice Alerts")

        for row in (self.row_binance, self.row_ws, self.row_postgres, self.row_redis,
                    self.row_telegram, self.row_api, self.row_voice):
            row.reconnect_requested.connect(self._on_reconnect)
            sg_layout.addWidget(row)

        root.addWidget(services_grp)

        # ── AI Provider status ─────────────────────────────────────────
        ai_grp = QGroupBox("AI Providers  (optional — features degrade gracefully when disabled)")
        ai_layout = QVBoxLayout(ai_grp)
        ai_layout.setSpacing(6)

        self.row_claude     = ServiceRow("claude",      "bolt",  "Claude (Anthropic)")
        self.row_openai     = ServiceRow("openai",      "bolt",  "ChatGPT (OpenAI)")
        self.row_gemini     = ServiceRow("gemini",      "bolt",  "Gemini (Google)")
        self.row_elevenlabs = ServiceRow("elevenlabs",  "bolt",  "ElevenLabs TTS")

        for row in (self.row_claude, self.row_openai, self.row_gemini, self.row_elevenlabs):
            row.action_btn.setText("Configure")
            row.reconnect_requested.connect(self._on_reconnect)
            ai_layout.addWidget(row)

        root.addWidget(ai_grp)

        # ── API endpoint display ───────────────────────────────────────
        endpoint_grp = QGroupBox("API Endpoints")
        eg_layout = QGridLayout(endpoint_grp)
        eg_layout.setSpacing(8)

        endpoints = [
            ("REST Base URL",    "rest_url"),
            ("WebSocket URL",    "ws_url"),
            ("PostgreSQL DSN",   "pg_dsn"),
            ("Redis URL",        "redis_url"),
        ]
        self._endpoint_labels: dict[str, QLabel] = {}
        for row_idx, (label, key) in enumerate(endpoints):
            k = QLabel(label)
            k.setStyleSheet(f"color:{FG2}; font-size:11px;")
            v = QLabel("—")
            v.setStyleSheet(f"color:{FG1}; font-size:11px; font-family:monospace;")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            eg_layout.addWidget(k, row_idx, 0)
            eg_layout.addWidget(v, row_idx, 1)
            self._endpoint_labels[key] = v

        root.addWidget(endpoint_grp)

        # Populate endpoint display from settings
        self._populate_endpoints()

        root.addStretch()
        self._start_time = time.time()
        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._update_uptime)
        self._uptime_timer.start(1000)

    def _populate_endpoints(self) -> None:
        try:
            from config import get_settings
            s = get_settings()
            self._endpoint_labels["rest_url"].setText(
                "https://api.binance.com" if not s.binance.testnet
                else "https://testnet.binance.vision"
            )
            self._endpoint_labels["ws_url"].setText(
                "wss://stream.binance.com:9443/ws"
            )
            self._endpoint_labels["pg_dsn"].setText(
                f"postgresql://{s.database.host}:{s.database.port}/{s.database.name}"
            )
            self._endpoint_labels["redis_url"].setText(
                f"redis://{s.redis.host}:{s.redis.port}/{s.redis.db}"
            )
        except Exception:
            pass

    # ── Check logic ────────────────────────────────────────────────────

    def _check_all(self) -> None:
        self.check_all_btn.setEnabled(False)
        for row in (self.row_binance, self.row_ws, self.row_postgres,
                    self.row_redis, self.row_telegram, self.row_api, self.row_voice,
                    self.row_claude, self.row_openai, self.row_gemini, self.row_elevenlabs):
            row.set_checking()
        threading.Thread(target=self._run_checks, daemon=True).start()

    def _run_checks(self) -> None:
        results = {}
        results["binance"]     = self._check_binance()
        results["ws"]          = self._check_ws()
        results["postgres"]    = self._check_postgres()
        results["redis"]       = self._check_redis()
        results["telegram"]    = self._check_telegram()
        results["api"]         = self._check_api_server()
        results["voice"]       = self._check_voice()
        results["claude"]      = self._check_ai_key("claude_api_key",      "Sentiment scoring · Signal Council")
        results["openai"]      = self._check_ai_key("openai_api_key",      "Sentiment scoring (fallback)")
        results["gemini"]      = self._check_ai_key("gemini_api_key",      "Sentiment scoring (fallback)")
        results["elevenlabs"]  = self._check_ai_key("elevenlabs_api_key",  "Voice alerts TTS")
        self._results_ready.emit(results)

    def _apply_results(self, results: dict) -> None:
        row_map = {
            "binance":    self.row_binance,
            "ws":         self.row_ws,
            "postgres":   self.row_postgres,
            "redis":      self.row_redis,
            "telegram":   self.row_telegram,
            "api":        self.row_api,
            "voice":      self.row_voice,
            "claude":     self.row_claude,
            "openai":     self.row_openai,
            "gemini":     self.row_gemini,
            "elevenlabs": self.row_elevenlabs,
        }
        AI_PROVIDERS = {"claude", "openai", "gemini", "elevenlabs"}
        online = 0
        offline = 0
        latencies = []
        for svc, row in row_map.items():
            ok, msg, latency = results.get(svc, (False, "Unknown", None))
            if ok:
                row.set_connected(latency)
                online += 1
                if latency:
                    latencies.append(latency)
            elif svc in AI_PROVIDERS:
                # Unconfigured AI providers are amber (warning), not red
                row.set_warning(msg)
            else:
                row.set_disconnected(msg)
                offline += 1

        self.card_online.set_value(str(online), GREEN)
        self.card_offline.set_value(str(offline), RED if offline > 0 else FG2)
        avg = sum(latencies) / len(latencies) if latencies else 0
        col = GREEN if avg < 100 else YELLOW if avg < 300 else RED
        self.card_latency.set_value(f"{avg:.0f}ms", col)
        self.last_check_lbl.setText(f"Last check: {_now()}")
        self.check_all_btn.setEnabled(True)

    def _check_binance(self) -> tuple[bool, str, float | None]:
        try:
            t0 = time.time()
            if self._client:
                self._client.ping()
                return True, "Connected", (time.time() - t0) * 1000
            # Fall back to HTTP ping
            import urllib.request
            urllib.request.urlopen("https://api.binance.com/api/v3/ping", timeout=5)
            return True, "Connected", (time.time() - t0) * 1000
        except Exception as e:
            return False, f"Error: {str(e)[:40]}", None

    def _check_ws(self) -> tuple[bool, str, float | None]:
        try:
            if self._engine and hasattr(self._engine, "_ws_connected"):
                ok = bool(self._engine._ws_connected)
                return (ok, "Stream active" if ok else "Stream down", None)
        except Exception:
            pass
        return True, "Not monitored", None

    def _check_postgres(self) -> tuple[bool, str, float | None]:
        try:
            t0 = time.time()
            from db.postgres import get_db
            with get_db() as db:
                db.execute(__import__("sqlalchemy").text("SELECT 1"))
            return True, "Connected", (time.time() - t0) * 1000
        except Exception as e:
            return False, f"Error: {str(e)[:40]}", None

    def _check_redis(self) -> tuple[bool, str, float | None]:
        try:
            t0 = time.time()
            from db.redis_client import RedisClient
            rc = RedisClient()
            rc.ping()
            return True, "Connected", (time.time() - t0) * 1000
        except Exception as e:
            return False, f"Error: {str(e)[:40]}", None

    def _check_telegram(self) -> tuple[bool, str, float | None]:
        try:
            from config import get_settings
            s = get_settings()
            if not getattr(s, "telegram", None) and not getattr(s.ai, "claude_api_key", ""):
                return True, "Not configured", None
        except Exception:
            pass
        return True, "Not monitored", None

    def _check_api_server(self) -> tuple[bool, str, float | None]:
        try:
            from api.server import get_api_server
            srv = get_api_server()
            if getattr(srv, "_running", False):
                return True, f"Listening on {srv.base_url}", None
            return False, "Not started", None
        except Exception:
            return False, "Not started", None

    def _check_voice(self) -> tuple[bool, str, float | None]:
        return True, "Not monitored", None

    def _check_ai_key(self, key_attr: str, features: str) -> tuple[bool, str, float | None]:
        """Returns (configured, status_text, None). Uses warning dot when not configured."""
        try:
            from config import get_settings
            ai = get_settings().ai
            key = getattr(ai, key_attr, None)
            if key:
                return True, f"Configured  ·  {features}", None
            return False, f"No API key  ·  {features}  ·  DISABLED", None
        except Exception:
            return False, "Config unavailable", None

    def _on_reconnect(self, service_id: str) -> None:
        from utils.logger import get_intel_logger
        get_intel_logger().system("Connections", f"Reconnect requested: {service_id}")
        self._check_all()

    def _update_uptime(self) -> None:
        elapsed = int(time.time() - self._start_time)
        h, rem = divmod(elapsed, 3600)
        m, s   = divmod(rem, 60)
        self.card_uptime.set_value(f"{h:02d}:{m:02d}:{s:02d}", ACCENT)
