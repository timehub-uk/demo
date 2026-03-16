"""
System Status Widget – Grafana-style live monitoring dashboard.

Shows real-time time-series graphs for:
  • CPU usage %
  • Memory usage %
  • Database (PostgreSQL) latency / status
  • Redis latency / status
  • Network I/O (bytes sent/recv)
  • P&L over session

Designed to be embedded as a tab in the Settings page or opened
as a standalone popup dialog (via SystemStatusDialog).
"""

from __future__ import annotations

import collections
import time
import os
import threading
from typing import Deque

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPainterPath, QLinearGradient,
    QFont, QFontMetrics,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QDialog, QScrollArea, QSizePolicy, QPushButton, QGridLayout,
)

from ui.styles import (
    ACCENT, ACCENT2, GREEN, RED, YELLOW, ORANGE, PURPLE,
    BG0, BG1, BG2, BG3, BG4, BG5,
    BORDER, BORDER2, FG0, FG1, FG2, GLOW,
)

# ── Constants ─────────────────────────────────────────────────────────────────

_HISTORY  = 60          # data points to keep (1 point per second = 60 s window)
_TICK_MS  = 1_000       # fast tick – CPU / mem / net-io (non-blocking)
_PROBE_MS = 10_000      # slow tick – DB / Redis / network probes (background thread)


# ── Tiny sparkline / area-chart widget ────────────────────────────────────────

class _MiniGraph(QWidget):
    """
    A single Grafana-style panel: dark card with a filled area chart,
    a live value badge, title and unit label.
    """

    def __init__(
        self,
        title: str,
        unit: str = "%",
        color: str = ACCENT,
        max_val: float = 100.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._title    = title
        self._unit     = unit
        self._color    = QColor(color)
        self._max_val  = max_val
        self._data: Deque[float] = collections.deque([0.0] * _HISTORY, maxlen=_HISTORY)
        self._cur_val  = 0.0
        self._status   = ""         # optional status string (ONLINE / OFFLINE)
        self._status_ok = True

        self.setMinimumSize(220, 130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def push(self, value: float, status: str = "", ok: bool = True) -> None:
        """Add a new data point and trigger repaint."""
        self._cur_val   = value
        self._status    = status
        self._status_ok = ok
        self._data.append(min(value, self._max_val))
        self.update()

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Card background
        p.fillRect(0, 0, w, h, QColor(BG3))

        # Thin border
        pen = QPen(QColor(BORDER2))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawRect(0, 0, w - 1, h - 1)

        # Title
        title_font = QFont("monospace", 9)
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(QColor(FG1))
        p.drawText(10, 18, self._title)

        # Value badge (top-right)
        val_text = f"{self._cur_val:.1f}{self._unit}"
        val_color = self._value_color()
        val_font = QFont("monospace", 12)
        val_font.setBold(True)
        p.setFont(val_font)
        p.setPen(QColor(val_color))
        fm = QFontMetrics(val_font)
        vw = fm.horizontalAdvance(val_text)
        p.drawText(w - vw - 10, 18, val_text)

        # Status text (below title) if present
        if self._status:
            st_font = QFont("monospace", 8)
            p.setFont(st_font)
            st_col = GREEN if self._status_ok else RED
            p.setPen(QColor(st_col))
            p.drawText(10, 32, f"● {self._status}")

        # Graph area
        graph_top    = 38
        graph_bottom = h - 14
        graph_h      = graph_bottom - graph_top
        graph_left   = 6
        graph_right  = w - 6
        graph_w      = graph_right - graph_left

        if graph_h < 10:
            p.end()
            return

        data = list(self._data)
        n = len(data)
        if n < 2:
            p.end()
            return

        # Compute x/y positions
        def _x(i: int) -> float:
            return graph_left + (i / (n - 1)) * graph_w

        def _y(v: float) -> float:
            ratio = v / self._max_val if self._max_val else 0
            return graph_bottom - ratio * graph_h

        # Filled gradient area
        path = QPainterPath()
        path.moveTo(_x(0), graph_bottom)
        for i, v in enumerate(data):
            path.lineTo(_x(i), _y(v))
        path.lineTo(_x(n - 1), graph_bottom)
        path.closeSubpath()

        grad = QLinearGradient(0, graph_top, 0, graph_bottom)
        c = QColor(self._color)
        c.setAlphaF(0.35)
        grad.setColorAt(0, c)
        c2 = QColor(self._color)
        c2.setAlphaF(0.04)
        grad.setColorAt(1, c2)
        p.fillPath(path, QBrush(grad))

        # Line
        line_pen = QPen(self._color)
        line_pen.setWidth(2)
        p.setPen(line_pen)
        for i in range(1, n):
            p.drawLine(
                int(_x(i - 1)), int(_y(data[i - 1])),
                int(_x(i)),     int(_y(data[i])),
            )

        # Last-point dot
        last_x = int(_x(n - 1))
        last_y = int(_y(data[-1]))
        dot_pen = QPen(self._color)
        dot_pen.setWidth(1)
        p.setPen(dot_pen)
        dot_color = QColor(self._color)
        dot_color.setAlphaF(0.9)
        p.setBrush(QBrush(dot_color))
        p.drawEllipse(last_x - 4, last_y - 4, 8, 8)

        # Horizontal grid lines (25%, 50%, 75%)
        grid_pen = QPen(QColor(BORDER))
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        grid_pen.setWidth(1)
        p.setPen(grid_pen)
        grid_font = QFont("monospace", 7)
        p.setFont(grid_font)
        p.setPen(QColor(FG2))
        for pct in (0.25, 0.50, 0.75):
            gy = int(graph_bottom - pct * graph_h)
            p.setPen(grid_pen)
            p.drawLine(graph_left, gy, graph_right, gy)
            # label
            p.setPen(QColor(FG2))
            label = f"{pct * self._max_val:.0f}"
            p.drawText(graph_left + 2, gy - 2, label)

        # Time axis label
        p.setPen(QColor(FG2))
        p.drawText(graph_left + 2, h - 2, "60s")
        p.drawText(graph_right - 24, h - 2, "now")

        p.end()

    def _value_color(self) -> str:
        if self._unit == "%":
            if self._cur_val > 85:
                return RED
            if self._cur_val > 60:
                return YELLOW
            return GREEN
        if "ms" in self._unit:
            if self._cur_val > 200:
                return RED
            if self._cur_val > 80:
                return YELLOW
            return GREEN
        if self._unit == "":
            return GREEN if self._status_ok else RED
        return ACCENT


# ── Status LED strip ──────────────────────────────────────────────────────────

class _StatusRow(QFrame):
    """A row of LED-style status indicators."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setStyleSheet(f"background:{BG4}; border:1px solid {BORDER2}; border-radius:6px;")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(12, 4, 12, 4)
        self._layout.setSpacing(20)
        self._indicators: dict[str, QLabel] = {}

    def add_indicator(self, key: str, label: str) -> None:
        lbl = QLabel(f"◉ {label}: —")
        lbl.setStyleSheet(f"color:{FG2}; font-size:11px; font-family:monospace;")
        self._layout.addWidget(lbl)
        self._indicators[key] = lbl
        self._layout.addStretch()

    def set_status(self, key: str, ok: bool, detail: str = "") -> None:
        lbl = self._indicators.get(key)
        if not lbl:
            return
        col  = GREEN if ok else RED
        text = "ONLINE" if ok else "OFFLINE"
        if detail:
            text = f"{text}  {detail}"
        lbl.setText(f"◉ {key.upper()}: {text}")
        lbl.setStyleSheet(f"color:{col}; font-size:11px; font-family:monospace;")


# ── Main dashboard widget ─────────────────────────────────────────────────────

class SystemStatusWidget(QWidget):
    """
    Grafana-inspired live system status dashboard.
    Embed in a tab or open via SystemStatusDialog.
    """

    # Signal to deliver blocking-probe results back onto the UI thread
    _probe_done = pyqtSignal(bool, bool, float, bool, float)  # net, db_ok, db_ms, rds_ok, rds_ms

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._prev_net = self._read_net_counters()
        self._probe_done.connect(self._apply_probe_results)

        # Fast timer – non-blocking updates only (CPU, mem, net I/O counters)
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        # Slow timer – dispatches blocking I/O probes to a background thread
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(_PROBE_MS)
        self._probe_timer.timeout.connect(self._dispatch_probes)
        self._probe_timer.start()
        # Run once immediately so the status row has values on first open
        QTimer.singleShot(0, self._dispatch_probes)

    # ── UI setup ──────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("⬡  SYSTEM STATUS")
        title.setStyleSheet(
            f"color:{ACCENT}; font-size:14px; font-weight:bold; font-family:monospace;"
        )
        hdr.addWidget(title)
        hdr.addStretch()

        self._uptime_lbl = QLabel("Uptime: —")
        self._uptime_lbl.setStyleSheet(f"color:{FG1}; font-size:10px; font-family:monospace;")
        hdr.addWidget(self._uptime_lbl)

        self._refresh_btn = QPushButton("↺  Refresh")
        self._refresh_btn.setFixedHeight(26)
        self._refresh_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{ACCENT}; border:1px solid {BORDER2};"
            f" border-radius:4px; font-size:10px; padding:0 10px; }}"
            f"QPushButton:hover {{ background:{BG5}; }}"
        )
        self._refresh_btn.clicked.connect(self._tick)
        hdr.addWidget(self._refresh_btn)
        root.addLayout(hdr)

        # ── LED status row ────────────────────────────────────────────────────
        self._status_row = _StatusRow()
        for key, label in [
            ("network", "Network"),
            ("db",      "PostgreSQL"),
            ("redis",   "Redis"),
            ("api",     "Binance API"),
        ]:
            self._status_row.add_indicator(key, label)
        root.addWidget(self._status_row)

        # ── Graph grid ────────────────────────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(8)

        self._cpu_graph  = _MiniGraph("CPU",     "%",  ACCENT,   100)
        self._mem_graph  = _MiniGraph("MEMORY",  "%",  ACCENT2,  100)
        self._db_graph   = _MiniGraph("DB LATENCY",  "ms", GREEN,  500, )
        self._rds_graph  = _MiniGraph("REDIS LATENCY", "ms", YELLOW, 500)
        self._net_tx_graph = _MiniGraph("NET TX",  "KB/s", PURPLE, 10_000)
        self._net_rx_graph = _MiniGraph("NET RX",  "KB/s", "#FF6D00", 10_000)

        grid.addWidget(self._cpu_graph,     0, 0)
        grid.addWidget(self._mem_graph,     0, 1)
        grid.addWidget(self._db_graph,      1, 0)
        grid.addWidget(self._rds_graph,     1, 1)
        grid.addWidget(self._net_tx_graph,  2, 0)
        grid.addWidget(self._net_rx_graph,  2, 1)

        root.addLayout(grid, 1)

        # ── DEX API quota panel ───────────────────────────────────────────────
        self._dex_panel = self._build_dex_quota_panel()
        root.addWidget(self._dex_panel)

        # ── Footer / legend ───────────────────────────────────────────────────
        footer = QLabel(
            "⬤ Live  •  1 s refresh  •  60 s window  •  Grafana-style monitoring"
        )
        footer.setStyleSheet(f"color:{FG2}; font-size:9px; font-family:monospace;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(footer)

        # track startup time for uptime
        self._start_ts = time.time()

    def _build_dex_quota_panel(self) -> QFrame:
        """Build the DEX API quota / call schedule status panel."""
        panel = QFrame()
        panel.setFixedHeight(70)
        panel.setStyleSheet(
            f"QFrame {{ background:{BG3}; border:1px solid {BORDER2}; border-radius:6px; }}"
        )
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(20)

        title = QLabel("DEX API")
        title.setStyleSheet(
            f"color:{ACCENT}; font-size:10px; font-weight:bold; font-family:monospace;"
        )
        layout.addWidget(title)

        self._dex_cg_lbl  = QLabel("CoinGecko: —")
        self._dex_cx_lbl  = QLabel("Codex: —")
        self._dex_sched_lbl = QLabel("Scheduler: —")
        self._dex_emerg_lbl = QLabel("Emergency: —")

        for lbl in [self._dex_cg_lbl, self._dex_cx_lbl,
                    self._dex_sched_lbl, self._dex_emerg_lbl]:
            lbl.setStyleSheet(
                f"color:{FG1}; font-size:10px; font-family:monospace;"
            )
            layout.addWidget(lbl)

        layout.addStretch()
        return panel

    # ── Data collection ───────────────────────────────────────────────────────

    def _tick(self) -> None:
        """Fast non-blocking tick: uptime, CPU, memory, net I/O counters only."""
        # Uptime
        up = int(time.time() - self._start_ts)
        h, rem = divmod(up, 3600)
        m, s   = divmod(rem, 60)
        self._uptime_lbl.setText(f"Uptime: {h:02d}:{m:02d}:{s:02d}")

        # CPU / Memory
        cpu_pct, mem_pct = self._read_cpu_mem()
        self._cpu_graph.push(cpu_pct)
        self._mem_graph.push(mem_pct)

        # Network I/O counters (reads /proc — non-blocking)
        tx_kb, rx_kb = self._read_net_delta()
        self._net_tx_graph.push(tx_kb)
        self._net_rx_graph.push(rx_kb)

        # DEX quota panel (in-memory state — free)
        self._update_dex_quota_panel()

    def _dispatch_probes(self) -> None:
        """Dispatch blocking network / DB / Redis probes to a background thread."""
        def _run():
            net_ok        = self._check_network()
            db_ok, db_ms  = self._check_postgres()
            rds_ok, rds_ms = self._check_redis()
            self._probe_done.emit(net_ok, db_ok, db_ms, rds_ok, rds_ms)

        threading.Thread(target=_run, daemon=True, name="sysstat-probe").start()

    def _apply_probe_results(
        self, net_ok: bool, db_ok: bool, db_ms: float, rds_ok: bool, rds_ms: float
    ) -> None:
        """Receive probe results on the UI thread and update widgets."""
        self._status_row.set_status("network", net_ok,
                                    "Internet reachable" if net_ok else "No route to host")

        self._db_graph.push(
            db_ms if db_ok else self._db_graph._max_val,
            status="ONLINE" if db_ok else "OFFLINE",
            ok=db_ok,
        )
        self._status_row.set_status("db", db_ok,
                                    f"{db_ms:.0f} ms" if db_ok else "")

        self._rds_graph.push(
            rds_ms if rds_ok else self._rds_graph._max_val,
            status="ONLINE" if rds_ok else "OFFLINE",
            ok=rds_ok,
        )
        self._status_row.set_status("redis", rds_ok,
                                    f"{rds_ms:.0f} ms" if rds_ok else "")

        api_ok = self._check_api()
        self._status_row.set_status("api", api_ok)

    def _update_dex_quota_panel(self) -> None:
        """Refresh DEX API quota / scheduler labels from in-memory state."""
        try:
            from core.dex_data_provider import get_dex_provider, get_dex_scheduler
            dex   = get_dex_provider()
            sched = get_dex_scheduler()

            # CoinGecko quota
            if dex.coingecko_active:
                cg = dex.coingecko_quota_info
                rem = cg["tokens_remaining"]
                bud = cg["hourly_budget"]
                pct = rem / bud if bud else 0
                col = GREEN if pct > 0.5 else YELLOW if pct > 0.2 else RED
                self._dex_cg_lbl.setText(f"CoinGecko: {rem}/{bud}/hr")
                self._dex_cg_lbl.setStyleSheet(
                    f"color:{col}; font-size:10px; font-family:monospace;"
                )
            else:
                self._dex_cg_lbl.setText("CoinGecko: disabled")
                self._dex_cg_lbl.setStyleSheet(
                    f"color:{FG2}; font-size:10px; font-family:monospace;"
                )

            # Codex quota
            if dex.codex_active:
                cx = dex.codex_quota_info
                rem = cx["tokens_remaining"]
                bud = cx["hourly_budget"]
                col = GREEN if rem > 0 else RED
                self._dex_cx_lbl.setText(f"Codex: {rem}/{bud}/hr")
                self._dex_cx_lbl.setStyleSheet(
                    f"color:{col}; font-size:10px; font-family:monospace;"
                )
            else:
                self._dex_cx_lbl.setText("Codex: disabled")
                self._dex_cx_lbl.setStyleSheet(
                    f"color:{FG2}; font-size:10px; font-family:monospace;"
                )

            # Scheduler: count valid cached slots
            snap = sched.cache_snapshot()
            valid = sum(1 for v in snap.values() if v["valid"])
            total = len(snap)
            self._dex_sched_lbl.setText(
                f"Cache: {valid}/{total} slots warm  •  12 slots/hr"
            )
            self._dex_sched_lbl.setStyleSheet(
                f"color:{ACCENT}; font-size:10px; font-family:monospace;"
            )

            # Emergency slot
            avail = sched.emergency_available
            self._dex_emerg_lbl.setText(
                f"Emergency: {'available' if avail else 'used this hour'}"
            )
            self._dex_emerg_lbl.setStyleSheet(
                f"color:{GREEN if avail else YELLOW}; font-size:10px; font-family:monospace;"
            )

        except Exception:
            pass   # DEX provider not yet initialised — silently skip

    # ── System helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _read_cpu_mem() -> tuple[float, float]:
        try:
            import psutil
            return psutil.cpu_percent(interval=None), psutil.virtual_memory().percent
        except Exception:
            pass
        # Fallback: parse /proc/stat for CPU, /proc/meminfo for memory
        try:
            cpu = SystemStatusWidget._proc_cpu()
            mem = SystemStatusWidget._proc_mem()
            return cpu, mem
        except Exception:
            return 0.0, 0.0

    _prev_cpu: tuple[float, float] | None = None

    @staticmethod
    def _proc_cpu() -> float:
        try:
            with open("/proc/stat") as f:
                line = f.readline()
            fields = list(map(float, line.split()[1:]))
            idle  = fields[3]
            total = sum(fields)
            prev  = SystemStatusWidget._prev_cpu
            SystemStatusWidget._prev_cpu = (idle, total)
            if prev is None:
                return 0.0
            d_idle  = idle  - prev[0]
            d_total = total - prev[1]
            return max(0.0, 100.0 * (1.0 - d_idle / d_total)) if d_total else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _proc_mem() -> float:
        try:
            info: dict[str, int] = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        info[parts[0].rstrip(":")] = int(parts[1])
            total = info.get("MemTotal", 0)
            avail = info.get("MemAvailable", info.get("MemFree", 0))
            if not total:
                return 0.0
            return 100.0 * (total - avail) / total
        except Exception:
            return 0.0

    @staticmethod
    def _read_net_counters() -> tuple[int, int]:
        """Return (bytes_sent, bytes_recv) from /proc/net/dev."""
        try:
            tx, rx = 0, 0
            with open("/proc/net/dev") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 10 or parts[0].startswith(("lo", "Inter", "|")):
                        continue
                    rx += int(parts[1])
                    tx += int(parts[9])
            return tx, rx
        except Exception:
            return 0, 0

    def _read_net_delta(self) -> tuple[float, float]:
        """Return (tx_kb/s, rx_kb/s) since last call."""
        cur = self._read_net_counters()
        prev = self._prev_net
        self._prev_net = cur
        tx_kb = max(0.0, (cur[0] - prev[0]) / 1024)
        rx_kb = max(0.0, (cur[1] - prev[1]) / 1024)
        return tx_kb, rx_kb

    @staticmethod
    def _check_network() -> bool:
        """Quick connectivity check via /proc/net/route default gateway."""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.settimeout(1)
                sock.connect(("8.8.8.8", 53))
                return True
            finally:
                sock.close()
        except Exception:
            pass
        # Fallback: check default route
        try:
            with open("/proc/net/route") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[1] == "00000000" and parts[2] != "00000000":
                        return True
        except Exception:
            pass
        return False

    @staticmethod
    def _check_postgres() -> tuple[bool, float]:
        try:
            from db.postgres import get_db
            from sqlalchemy import text
            t0 = time.perf_counter()
            with get_db() as db:
                db.execute(text("SELECT 1"))
            ms = (time.perf_counter() - t0) * 1000
            return True, ms
        except Exception:
            return False, 0.0

    @staticmethod
    def _check_redis() -> tuple[bool, float]:
        try:
            from db.redis_client import get_redis
            t0 = time.perf_counter()
            get_redis().ping()
            ms = (time.perf_counter() - t0) * 1000
            return True, ms
        except Exception:
            return False, 0.0

    @staticmethod
    def _check_api() -> bool:
        try:
            from config import get_settings
            s = get_settings()
            return bool(getattr(s, "binance_api_key", "") and
                        getattr(s, "binance_api_secret", ""))
        except Exception:
            return False

    def stop(self) -> None:
        """Stop polling – call when widget is hidden/closed."""
        self._timer.stop()

    def start(self) -> None:
        """Resume polling."""
        self._timer.start()


# ── Popup dialog wrapper ──────────────────────────────────────────────────────

class SystemStatusDialog(QDialog):
    """
    Standalone popup dialog that wraps SystemStatusWidget.
    Open via:  SystemStatusDialog(parent).exec()
    or non-modally with .show()
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("System Status  —  BinanceML Pro")
        self.setMinimumSize(780, 620)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setStyleSheet(
            f"QDialog {{ background:{BG1}; border:1px solid {BORDER2}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._status_widget = SystemStatusWidget(self)
        layout.addWidget(self._status_widget)

        # Close button
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(10, 4, 10, 10)
        btn_row.addStretch()
        close_btn = QPushButton("✕  Close")
        close_btn.setFixedHeight(28)
        close_btn.setStyleSheet(
            f"QPushButton {{ background:{BG4}; color:{FG1}; border:1px solid {BORDER2};"
            f" border-radius:4px; font-size:10px; padding:0 16px; }}"
            f"QPushButton:hover {{ background:{BG5}; color:{FG0}; }}"
        )
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._status_widget.stop()
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        self._status_widget.start()
        super().showEvent(event)
