"""
Email Notifier – full SMTP support.

Sends HTML emails for trade alerts, daily reports, and tax reports.
Configure in Settings → Notifications → Email (SMTP).

Supports:
  - STARTTLS (port 587, the default)
  - SSL/TLS direct (port 465)
  - Plain/unauthenticated relay (set smtp_password = "")
  - Multiple recipients (comma-separated in settings.notifications.email_to)
"""

from __future__ import annotations

import queue
import smtplib
import threading
import time
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from loguru import logger
from utils.logger import get_intel_logger


@dataclass
class EmailMessage:
    subject: str
    html_body: str
    text_body: str = ""


class EmailNotifier:
    """Queued SMTP email sender."""

    MAX_QUEUE = 50
    RATE_LIMIT_SEC = 2.0

    def __init__(self) -> None:
        self._intel = get_intel_logger()
        self._cfg = None
        self._queue: queue.Queue[EmailMessage] = queue.Queue(maxsize=self.MAX_QUEUE)
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        try:
            from config import get_settings
            settings = get_settings()
            self._cfg = settings.notifications
        except Exception:
            pass

        if not self._cfg or not self._cfg.smtp_host:
            self._intel.system("Email", "Email not configured – skipping")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="email-notifier"
        )
        self._thread.start()
        self._intel.system("Email", f"Email notifier started (SMTP: {self._cfg.smtp_host}:{self._cfg.smtp_port})")

    def stop(self) -> None:
        self._running = False

    @property
    def enabled(self) -> bool:
        return bool(self._cfg and self._cfg.smtp_host and self._running)

    def test_connection(self) -> tuple[bool, str]:
        """Verify SMTP credentials without sending a message. Returns (ok, message)."""
        if not self._cfg:
            return False, "Not configured"
        try:
            self._send_smtp(EmailMessage(
                subject="BinanceML Pro – SMTP Test",
                html_body="<p>SMTP connection test successful.</p>",
                text_body="SMTP connection test successful.",
            ))
            return True, "Connection OK – test email sent"
        except Exception as exc:
            return False, str(exc)

    # ── Alert helpers ──────────────────────────────────────────────────

    def send_trade_alert(self, action: str, symbol: str, price: float,
                         qty: float, pnl: Optional[float] = None) -> None:
        if not self.enabled or not (self._cfg and self._cfg.email_trade_alerts):
            return
        pnl_row = f"<tr><td>P&L</td><td><b>{pnl:+,.2f} USDT</b></td></tr>" if pnl is not None else ""
        color = "#00C853" if action == "BUY" else "#D50000"
        self._enqueue(EmailMessage(
            subject=f"[BinanceML Pro] {action} {symbol}",
            html_body=_wrap_email(f"""
                <h2 style="color:{color}">{action} {symbol}</h2>
                <table style="border-collapse:collapse">
                  <tr><td style="padding:4px 12px">Price</td>
                      <td style="padding:4px 12px"><b>{price:,.4f} USDT</b></td></tr>
                  <tr><td style="padding:4px 12px">Quantity</td>
                      <td style="padding:4px 12px"><b>{qty:.6f}</b></td></tr>
                  {pnl_row}
                </table>
            """),
            text_body=f"{action} {symbol} | Price: {price:,.4f} | Qty: {qty:.6f}"
                      + (f" | PnL: {pnl:+,.2f}" if pnl else ""),
        ))

    def send_daily_report(self, daily_pnl: float, trades: int, win_rate: float,
                          extra_html: str = "") -> None:
        if not self.enabled or not (self._cfg and self._cfg.email_daily_report):
            return
        color = "#00C853" if daily_pnl >= 0 else "#D50000"
        self._enqueue(EmailMessage(
            subject=f"[BinanceML Pro] Daily Report – {daily_pnl:+,.2f} USDT",
            html_body=_wrap_email(f"""
                <h2>Daily P&amp;L Report</h2>
                <table style="border-collapse:collapse">
                  <tr><td style="padding:4px 12px">P&amp;L</td>
                      <td style="padding:4px 12px;color:{color}"><b>{daily_pnl:+,.2f} USDT</b></td></tr>
                  <tr><td style="padding:4px 12px">Trades</td>
                      <td style="padding:4px 12px"><b>{trades}</b></td></tr>
                  <tr><td style="padding:4px 12px">Win Rate</td>
                      <td style="padding:4px 12px"><b>{win_rate:.0%}</b></td></tr>
                </table>
                {extra_html}
            """),
            text_body=f"Daily PnL: {daily_pnl:+,.2f} USDT | Trades: {trades} | Win Rate: {win_rate:.0%}",
        ))

    def send_tax_report(self, year: int, month: int, report_html: str,
                        report_text: str = "") -> None:
        if not self.enabled or not (self._cfg and self._cfg.email_tax_reports):
            return
        import calendar
        month_name = calendar.month_name[month]
        self._enqueue(EmailMessage(
            subject=f"[BinanceML Pro] Tax Report – {month_name} {year}",
            html_body=_wrap_email(f"<h2>Tax Report: {month_name} {year}</h2>{report_html}"),
            text_body=report_text or f"Tax Report: {month_name} {year}",
        ))

    def send_layer_results(self, layer: int, results: dict) -> None:
        """Email ML layer results."""
        if not self.enabled:
            return
        tools = results.get("tools", {})
        rows = []
        for name, data in tools.items():
            rows.append(f"<tr><td colspan='2' style='padding:8px;background:#1a1a2e;color:#00D4FF'>"
                        f"<b>{name.replace('_', ' ').title()}</b></td></tr>")
            if isinstance(data, dict):
                for k, v in list(data.items())[:5]:
                    if not isinstance(v, (dict, list)):
                        rows.append(f"<tr><td style='padding:4px 12px'>{k}</td>"
                                    f"<td style='padding:4px 12px'>{v}</td></tr>")
        self._enqueue(EmailMessage(
            subject=f"[BinanceML Pro] Layer {layer} – {results.get('name', '')}",
            html_body=_wrap_email(
                f"<h2>Layer {layer} – {results.get('name', '')}</h2>"
                f"<table style='border-collapse:collapse;width:100%'>{''.join(rows)}</table>"
            ),
            text_body=f"Layer {layer}: {results.get('name', '')}",
        ))

    def send_text(self, subject: str, message: str) -> None:
        if not self.enabled:
            return
        self._enqueue(EmailMessage(
            subject=subject,
            html_body=_wrap_email(f"<p>{message}</p>"),
            text_body=message,
        ))

    # ── Internal ───────────────────────────────────────────────────────

    def _enqueue(self, msg: EmailMessage) -> None:
        try:
            self._queue.put_nowait(msg)
        except queue.Full:
            pass

    def _worker(self) -> None:
        while self._running:
            try:
                msg = self._queue.get(timeout=1.0)
                self._send_smtp(msg)
                self._queue.task_done()
                time.sleep(self.RATE_LIMIT_SEC)
            except queue.Empty:
                continue
            except Exception as exc:
                logger.debug(f"Email send error: {exc}")

    def _send_smtp(self, msg: EmailMessage) -> None:
        cfg = self._cfg
        recipients = [r.strip() for r in cfg.email_to.split(",") if r.strip()]
        if not recipients:
            return

        mime = MIMEMultipart("alternative")
        mime["Subject"] = msg.subject
        mime["From"]    = cfg.email_from or cfg.smtp_username
        mime["To"]      = ", ".join(recipients)

        if msg.text_body:
            mime.attach(MIMEText(msg.text_body, "plain"))
        mime.attach(MIMEText(msg.html_body, "html"))

        # Port 465 → SSL/TLS; anything else → STARTTLS
        if cfg.smtp_port == 465:
            with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=15) as server:
                if cfg.smtp_username and cfg.smtp_password:
                    server.login(cfg.smtp_username, cfg.smtp_password)
                server.sendmail(mime["From"], recipients, mime.as_string())
        else:
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as server:
                if cfg.smtp_use_tls:
                    server.starttls()
                if cfg.smtp_username and cfg.smtp_password:
                    server.login(cfg.smtp_username, cfg.smtp_password)
                server.sendmail(mime["From"], recipients, mime.as_string())


def _wrap_email(body: str) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="background:#0a0a12;color:#e0e0f0;font-family:Arial,sans-serif;padding:24px">
  <div style="max-width:600px;margin:0 auto">
    <div style="background:#12121e;border-radius:8px;padding:24px">
      {body}
    </div>
    <p style="color:#444;font-size:11px;margin-top:16px;text-align:center">
      BinanceML Pro – automated notification
    </p>
  </div>
</body>
</html>"""


_email_singleton: EmailNotifier | None = None


def get_email_notifier() -> EmailNotifier:
    global _email_singleton
    if _email_singleton is None:
        _email_singleton = EmailNotifier()
    return _email_singleton
