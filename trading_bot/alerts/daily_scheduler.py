"""
Daily Report Scheduler.

Runs a lightweight background thread that fires two email reports once per day
at a configured wall-clock time (default 08:00 UTC):

  1. Error & Warning Digest  – table of issues with explanation, solution and help
  2. Trade P&L Statement     – full breakdown of every trade closed today

Send time is configurable via settings.notifications.daily_report_time ("HH:MM").
Reports can also be triggered immediately via send_now() for testing.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from utils.logger import get_intel_logger


class DailyScheduler:
    """
    Background thread that sends daily email reports at a configured time.

    Usage:
        scheduler = DailyScheduler(email_notifier=email, trade_journal=journal)
        scheduler.start()
    """

    def __init__(self, email_notifier, trade_journal=None) -> None:
        self._email      = email_notifier
        self._journal    = trade_journal
        self._intel      = get_intel_logger()
        self._thread: Optional[threading.Thread] = None
        self._running    = False
        self._last_sent_date: Optional[str] = None   # "YYYY-MM-DD"

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="daily-scheduler"
        )
        self._thread.start()
        send_time = self._get_send_time()
        self._intel.system(
            "DailyScheduler",
            f"Daily report scheduler started – reports will send at {send_time} UTC",
        )

    def stop(self) -> None:
        self._running = False

    # ── Manual trigger ─────────────────────────────────────────────────────────

    def send_now(self) -> None:
        """Send both reports immediately (for testing or on-demand delivery)."""
        threading.Thread(
            target=self._send_all_reports, daemon=True, name="daily-report-now"
        ).start()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _get_send_time(self) -> str:
        """Return configured send time as 'HH:MM'. Default 08:00."""
        try:
            from config import get_settings
            t = getattr(get_settings().notifications, "daily_report_time", "08:00")
            return t if t else "08:00"
        except Exception:
            return "08:00"

    def _worker(self) -> None:
        while self._running:
            try:
                now   = datetime.now(timezone.utc)
                today = now.strftime("%Y-%m-%d")
                send_time = self._get_send_time()

                try:
                    target_hour, target_min = (int(p) for p in send_time.split(":"))
                except Exception:
                    target_hour, target_min = 8, 0

                if (
                    now.hour == target_hour
                    and now.minute == target_min
                    and self._last_sent_date != today
                ):
                    self._last_sent_date = today
                    self._send_all_reports()

            except Exception as exc:
                logger.debug(f"DailyScheduler tick error: {exc}")

            time.sleep(30)   # check every 30 seconds

    def _send_all_reports(self) -> None:
        date_str = datetime.now(timezone.utc).strftime("%d %b %Y")
        self._intel.system("DailyScheduler", f"Sending daily reports for {date_str}…")

        try:
            self._send_error_report()
        except Exception as exc:
            logger.error(f"DailyScheduler: error report failed: {exc}")

        try:
            self._send_trade_statement()
        except Exception as exc:
            logger.error(f"DailyScheduler: trade statement failed: {exc}")

    # ── Error report ───────────────────────────────────────────────────────────

    def _send_error_report(self) -> None:
        if not (self._email and self._email.enabled):
            return

        from alerts.daily_reports import build_error_report_html
        from alerts.email_notifier import _wrap_email, EmailMessage

        html_body, issue_count = build_error_report_html(self._intel)
        date_str = datetime.now(timezone.utc).strftime("%d %b %Y")
        suffix   = f"{issue_count} issue(s)" if issue_count > 0 else "All Clear ✓"

        self._email._enqueue(EmailMessage(
            subject=f"[BinanceML Pro] Daily Error Report – {date_str} – {suffix}",
            html_body=_wrap_email(html_body),
            text_body=(
                f"Daily error digest for {date_str}: {issue_count} issue(s). "
                f"Open the HTML version for explanations and solutions."
            ),
        ))
        self._intel.system(
            "DailyScheduler",
            f"Error report sent ({issue_count} issue(s) logged today)",
        )

    # ── Trade P&L statement ────────────────────────────────────────────────────

    def _send_trade_statement(self) -> None:
        if not (self._email and self._email.enabled):
            return
        if not self._journal:
            return

        from alerts.daily_reports import build_trade_statement_html
        from alerts.email_notifier import _wrap_email, EmailMessage

        html_body, summary = build_trade_statement_html(self._journal)
        date_str   = datetime.now(timezone.utc).strftime("%d %b %Y")
        pnl        = summary.get("total_pnl", 0.0)
        trades_n   = summary.get("total_trades", 0)
        win_rate   = summary.get("win_rate", 0.0)

        self._email._enqueue(EmailMessage(
            subject=(
                f"[BinanceML Pro] Daily Trade Statement – {date_str} – "
                f"{pnl:+,.2f} USDT"
            ),
            html_body=_wrap_email(html_body),
            text_body=(
                f"Daily P&L for {date_str}: {pnl:+,.4f} USDT | "
                f"Trades: {trades_n} | Win Rate: {win_rate:.0%}"
            ),
        ))
        self._intel.system(
            "DailyScheduler",
            f"Trade statement sent ({trades_n} trades, {pnl:+,.4f} USDT, "
            f"{win_rate:.0%} win rate)",
        )


# ── Singleton ──────────────────────────────────────────────────────────────────

_scheduler: DailyScheduler | None = None


def get_daily_scheduler(email_notifier=None, trade_journal=None) -> DailyScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = DailyScheduler(
            email_notifier=email_notifier,
            trade_journal=trade_journal,
        )
    return _scheduler
