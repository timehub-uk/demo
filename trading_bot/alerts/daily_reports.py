"""
Daily email reports:
  - Error & Warning Digest: table of issues with explanation, solution and help text
  - Trade P&L Statement:    full breakdown of every trade closed today
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional


# ── Error knowledge base ───────────────────────────────────────────────────────
# Each entry has a list of keywords to match against the error message (case-insensitive).

_ERROR_KB: list[dict] = [
    {
        "keywords": ["api key", "api_key", "invalid key", "apikey", "api-key"],
        "category": "API Authentication",
        "explanation": (
            "Binance API key is invalid, expired, or does not have the required permissions."
        ),
        "solution": (
            "Go to Settings → Binance and re-enter your API Key and Secret. "
            "Ensure the key has Spot Trading and Read permissions enabled on Binance."
        ),
        "help": "Binance → My Account → API Management → Edit Restrictions",
    },
    {
        "keywords": ["signature", "timestamp", "recv_window", "recvwindow", "time sync"],
        "category": "API Timing",
        "explanation": (
            "Request timestamp is outside the acceptable window (±1000 ms by default). "
            "Usually caused by system clock drift."
        ),
        "solution": (
            "Sync your system clock: run `sudo ntpdate pool.ntp.org` on Linux/Mac. "
            "In Settings → Binance, increase Recv Window to 10000 ms if the issue persists."
        ),
        "help": "Binance requires timestamps within 1 second of their servers by default.",
    },
    {
        "keywords": [
            "connection", "timeout", "refused", "network", "socket",
            "ssl", "connect", "unreachable", "no route",
        ],
        "category": "Network Connectivity",
        "explanation": (
            "Unable to reach Binance or another external service. "
            "Possible causes: internet outage, firewall, VPN blocking, or Binance downtime."
        ),
        "solution": (
            "Check your internet connection. If using a VPN, ensure Binance traffic is allowed. "
            "Check https://status.binance.com for platform incidents."
        ),
        "help": "Ensure ports 443 (HTTPS) and WebSocket (WSS/443) are not blocked by firewall.",
    },
    {
        "keywords": [
            "postgresql", "postgres", "database", "sqlalchemy", "sqlite",
            "psycopg", "db error", "operationalerror",
        ],
        "category": "Database",
        "explanation": (
            "Database connection or query failed. "
            "Trade history and settings may not be persisted correctly."
        ),
        "solution": (
            "Check PostgreSQL is running: `pg_ctl status` or `systemctl status postgresql`. "
            "Verify credentials in Settings → Database. "
            "The app will fall back to local SQLite automatically."
        ),
        "help": "Run `pg_isready -h localhost` to test PostgreSQL connectivity.",
    },
    {
        "keywords": ["redis", "cache", "cach"],
        "category": "Cache (Redis)",
        "explanation": (
            "Redis cache is unavailable. Performance may be reduced but trading continues normally."
        ),
        "solution": (
            "Start Redis: `redis-server` or `systemctl start redis`. "
            "Verify host/port in Settings → Database → Redis."
        ),
        "help": "Redis is optional — the app uses in-memory caching as fallback.",
    },
    {
        "keywords": [
            "insufficient balance", "insufficient funds",
            "balance", "not enough", "account balance",
        ],
        "category": "Account Balance",
        "explanation": (
            "Insufficient funds to execute the trade. The order was rejected by Binance."
        ),
        "solution": (
            "Check your Binance spot wallet balance. "
            "Reduce position size in Settings → Trading → Risk Per Trade %. "
            "Ensure your USDT balance covers the order plus the 0.1% trading fee."
        ),
        "help": "Use paper trading mode to test strategies without risking real funds.",
    },
    {
        "keywords": ["rate limit", "429", "too many request", "ip ban", "weight"],
        "category": "API Rate Limit",
        "explanation": (
            "Too many API requests sent to Binance in a short period. "
            "Risk of temporary IP ban (ban lifts after 60–120 seconds)."
        ),
        "solution": (
            "Reduce polling frequency. Disable unused scanners in Settings → ML. "
            "Wait 2 minutes before retrying. If persistent, reduce the number of watched symbols."
        ),
        "help": (
            "Binance REST: 1200 request weight/min. WebSocket: 10 connections max. "
            "Each endpoint has a different weight cost."
        ),
    },
    {
        "keywords": [
            "model", "lstm", "predict", "torch", "tensorflow",
            "cuda", "mps", "training", "no trained",
        ],
        "category": "ML Model",
        "explanation": (
            "Machine learning model error. Predictions may be unavailable or degraded. "
            "The system will continue with rule-based signals."
        ),
        "solution": (
            "Retrain the model via ML → Train Model. "
            "Ensure at least 48 hours of 1-min OHLCV data has been downloaded first. "
            "In Settings → ML, try disabling GPU if CUDA/MPS errors occur."
        ),
        "help": "ML requires ~48 h of historical 1-min candle data per symbol to train.",
    },
    {
        "keywords": ["permission", "403", "401", "unauthorized", "forbidden"],
        "category": "Permissions",
        "explanation": (
            "Access denied. API key may be missing required permissions "
            "or restricted to specific IP addresses."
        ),
        "solution": (
            "On Binance → API Management, verify the key allows Spot & Margin Trading "
            "and check the IP whitelist. "
            "Disable IP restriction for testing, then re-enable with your server IP."
        ),
        "help": "Required permissions: Enable Reading, Enable Spot & Margin Trading.",
    },
    {
        "keywords": ["min notional", "lot size", "filter", "order quantity", "notional"],
        "category": "Order Validation",
        "explanation": (
            "Order rejected by Binance exchange filters (minimum notional value or lot size). "
            "Each trading pair has minimum order constraints."
        ),
        "solution": (
            "Increase minimum trade value or reduce decimal precision. "
            "Check the symbol's trading rules on Binance. "
            "Most pairs require a minimum of $5–$10 per order."
        ),
        "help": "Binance filters: MIN_NOTIONAL (min order value), LOT_SIZE (qty precision).",
    },
    {
        "keywords": ["webhook", "discord", "slack"],
        "category": "Notifications",
        "explanation": "Failed to send a notification via Discord, Slack, or webhook.",
        "solution": (
            "Verify webhook URL in Settings → Notifications. "
            "Regenerate the Discord/Slack webhook if it has expired or been revoked."
        ),
        "help": "Notification failures are non-critical and do not affect trading.",
    },
    {
        "keywords": ["smtp", "email", "sendgrid", "mail"],
        "category": "Email (SMTP)",
        "explanation": "Email notification failed to send.",
        "solution": (
            "Check SMTP settings in Settings → Notifications → Email. "
            "Verify host, port, credentials, TLS setting, and recipient addresses."
        ),
        "help": (
            "Gmail: smtp.gmail.com:587, STARTTLS, use an App Password not your account password. "
            "Outlook: smtp.office365.com:587."
        ),
    },
    {
        "keywords": ["telegram"],
        "category": "Telegram",
        "explanation": "Telegram bot failed to send a message.",
        "solution": (
            "Verify your bot token and chat ID in Settings → AI / Telegram. "
            "Ensure the bot has been started by the recipient (/start command). "
            "Check the bot has not been blocked."
        ),
        "help": "Get your numeric chat ID by messaging @userinfobot on Telegram.",
    },
    {
        "keywords": ["kill switch", "kill_switch", "emergency stop"],
        "category": "Safety – Kill Switch",
        "explanation": "The emergency kill switch was triggered, halting all trading activity.",
        "solution": (
            "Review the circumstances that triggered the kill switch. "
            "Check drawdown levels, error rates, and recent trades. "
            "Re-enable trading via the Safety panel once you are satisfied."
        ),
        "help": "Kill switch thresholds are configurable in Settings → Trading → Safety.",
    },
    {
        "keywords": ["drawdown", "max drawdown", "daily loss"],
        "category": "Risk Management",
        "explanation": (
            "Maximum drawdown or daily loss limit was reached. "
            "Automated trading has been suspended to protect capital."
        ),
        "solution": (
            "Review recent trades and market conditions. "
            "Adjust drawdown limits in Settings → Trading if appropriate. "
            "Re-enable trading manually once confident."
        ),
        "help": "Conservative daily loss limit: 2–3% of account balance.",
    },
]

_FALLBACK_KB = {
    "category": "General",
    "explanation": "An unexpected error occurred in the trading system.",
    "solution": (
        "Check the full error message for context. "
        "If the issue persists, restart the application and review the log at "
        "~/.binanceml/logs/errors.log."
    ),
    "help": (
        "Log files are stored at ~/.binanceml/logs/. "
        "Share errors.log when reporting issues."
    ),
}


def _lookup_kb(message: str) -> dict:
    """Return the best-matching KB entry for this error message."""
    msg_lower = message.lower()
    for entry in _ERROR_KB:
        if any(kw in msg_lower for kw in entry["keywords"]):
            return entry
    return _FALLBACK_KB


# ── Error / Warning digest ─────────────────────────────────────────────────────

def build_error_report_html(intel_logger) -> tuple[str, int]:
    """
    Pull ERROR / WARNING / CRITICAL entries from the IntelLogger buffer for the last 24 hours,
    group duplicates, annotate each with explanation + solution + help text, and return
    (html_body, total_issue_count).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    entries = [
        e for e in intel_logger.recent(n=5000)
        if e.level in ("ERROR", "CRITICAL", "WARNING") and e.ts >= cutoff
    ]

    date_str = datetime.now(timezone.utc).strftime("%d %B %Y")

    if not entries:
        return (
            f"<h2 style='color:#27ae60'>Daily Error &amp; Warning Digest</h2>"
            f"<p style='color:#aaa'>{date_str} (UTC)</p>"
            f"<p style='color:#27ae60'>&#10003; No errors or warnings in the past 24 hours. "
            f"System running normally.</p>",
            0,
        )

    # Deduplicate: group by (level, source, first 80 chars of message)
    groups: dict[str, dict] = {}
    for e in entries:
        key = f"{e.level}|{e.source}|{e.message[:80]}"
        if key not in groups:
            groups[key] = {"entry": e, "count": 1, "kb": _lookup_kb(e.message)}
        else:
            groups[key]["count"] += 1

    error_count = sum(1 for g in groups.values() if g["entry"].level in ("ERROR", "CRITICAL"))
    warn_count  = sum(1 for g in groups.values() if g["entry"].level == "WARNING")
    total_occ   = sum(g["count"] for g in groups.values())

    rows_html: list[str] = []
    for idx, item in enumerate(groups.values()):
        e    = item["entry"]
        cnt  = item["count"]
        kb   = item["kb"]
        bg   = "#0e0e1a" if idx % 2 == 0 else "#12121e"
        level_colour = {
            "ERROR":    "#e74c3c",
            "CRITICAL": "#c0392b",
            "WARNING":  "#f39c12",
        }.get(e.level, "#888")

        count_badge = (
            f'<span style="background:#333;border-radius:10px;padding:1px 7px;'
            f'font-size:10px;margin-right:4px">{cnt}×</span>'
            if cnt > 1 else ""
        )

        rows_html.append(f"""
        <tr style="background:{bg}">
          <td style="padding:8px 10px;white-space:nowrap;
                     color:{level_colour};font-weight:bold;font-size:11px">{e.level}</td>
          <td style="padding:8px 10px;white-space:nowrap;
                     color:#aaa;font-size:11px">{e.ts.strftime('%H:%M:%S')}</td>
          <td style="padding:8px 10px;white-space:nowrap;
                     color:#ccc;font-size:11px">{e.source}</td>
          <td style="padding:8px 10px;font-size:11px">
            {count_badge}<span style="color:#e0e0f0">{e.message[:120]}</span>
          </td>
          <td style="padding:8px 10px;color:#888;font-size:10px">{kb.get('category','')}</td>
        </tr>
        <tr style="background:#0a0a10">
          <td colspan="5" style="padding:4px 10px 14px 28px">
            <table style="width:100%;font-size:11px;border-spacing:0">
              <tr>
                <td style="color:#666;width:100px;padding:3px 8px;
                           vertical-align:top">Explanation</td>
                <td style="color:#bbb;padding:3px 8px">{kb.get('explanation','')}</td>
              </tr>
              <tr>
                <td style="color:#666;padding:3px 8px;vertical-align:top">Solution</td>
                <td style="color:#7ec8e3;padding:3px 8px">{kb.get('solution','')}</td>
              </tr>
              <tr>
                <td style="color:#666;padding:3px 8px;vertical-align:top">Help</td>
                <td style="color:#999;font-style:italic;padding:3px 8px">
                  {kb.get('help','')}
                </td>
              </tr>
            </table>
          </td>
        </tr>""")

    html = f"""
<h2 style="color:#e74c3c;margin-bottom:4px">Daily Error &amp; Warning Digest</h2>
<p style="color:#aaa;margin-top:0">{date_str} (UTC) &nbsp;&bull;&nbsp;
  <span style="color:#e74c3c">{error_count} error(s)</span> &nbsp;&bull;&nbsp;
  <span style="color:#f39c12">{warn_count} warning(s)</span> &nbsp;&bull;&nbsp;
  <span style="color:#888">{total_occ} total occurrence(s)</span>
</p>
<table style="width:100%;border-collapse:collapse;margin-top:16px">
  <thead>
    <tr style="background:#1a1a2e">
      <th style="padding:8px 10px;text-align:left;color:#00D4FF;font-size:11px">Level</th>
      <th style="padding:8px 10px;text-align:left;color:#00D4FF;font-size:11px">Time (UTC)</th>
      <th style="padding:8px 10px;text-align:left;color:#00D4FF;font-size:11px">Source</th>
      <th style="padding:8px 10px;text-align:left;color:#00D4FF;font-size:11px">Message</th>
      <th style="padding:8px 10px;text-align:left;color:#00D4FF;font-size:11px">Category</th>
    </tr>
  </thead>
  <tbody>{''.join(rows_html)}</tbody>
</table>"""

    return html, error_count + warn_count


# ── Daily trade P&L statement ──────────────────────────────────────────────────

def build_trade_statement_html(trade_journal) -> tuple[str, dict]:
    """
    Pull today's closed trades from TradeJournal and return (html_body, summary_dict).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_str = datetime.now(timezone.utc).strftime("%d %B %Y")

    all_closed = trade_journal.get_closed_trades(limit=1000)
    trades = [t for t in all_closed if (t.get("exit_time") or "").startswith(today)]

    if not trades:
        return (
            f"<h2 style='color:#00D4FF'>Daily Trade Statement</h2>"
            f"<p style='color:#aaa'>{date_str} (UTC)</p>"
            f"<p style='color:#888'>No trades closed today.</p>",
            {"total_trades": 0, "total_pnl": 0.0, "win_rate": 0.0},
        )

    total_pnl   = sum(float(t.get("pnl", 0)) for t in trades)
    wins        = [t for t in trades if float(t.get("pnl", 0)) > 0]
    losses      = [t for t in trades if float(t.get("pnl", 0)) <= 0]
    win_rate    = len(wins) / len(trades)
    best_trade  = max(trades, key=lambda t: float(t.get("pnl", 0)))
    worst_trade = min(trades, key=lambda t: float(t.get("pnl", 0)))
    avg_dur     = sum(float(t.get("duration_minutes", 0)) for t in trades) / len(trades)

    pnl_colour = "#27ae60" if total_pnl >= 0 else "#e74c3c"

    # ── Summary cards ──────────────────────────────────────────────────────────
    summary_html = f"""
<h2 style="color:#00D4FF;margin-bottom:4px">Daily Trade Statement</h2>
<p style="color:#aaa;margin-top:0">{date_str} (UTC)</p>
<table style="border-collapse:collapse;font-size:12px;margin:16px 0;width:100%">
  <tr style="background:#1a1a2e">
    <td style="padding:10px 16px;color:#aaa">Total Trades</td>
    <td style="padding:10px 16px;color:#e0e0f0;font-weight:bold">{len(trades)}</td>
    <td style="padding:10px 16px;color:#aaa">Win / Loss</td>
    <td style="padding:10px 16px;color:#e0e0f0;font-weight:bold">
      <span style="color:#27ae60">{len(wins)}</span> /
      <span style="color:#e74c3c">{len(losses)}</span>
    </td>
    <td style="padding:10px 16px;color:#aaa">Win Rate</td>
    <td style="padding:10px 16px;color:#e0e0f0;font-weight:bold">{win_rate:.0%}</td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#aaa">Net P&amp;L (USDT)</td>
    <td style="padding:10px 16px;color:{pnl_colour};font-size:16px;font-weight:bold">
      {total_pnl:+,.4f}
    </td>
    <td style="padding:10px 16px;color:#aaa">Avg Duration</td>
    <td style="padding:10px 16px;color:#e0e0f0;font-weight:bold">{avg_dur:.0f} min</td>
    <td style="padding:10px 16px;color:#aaa"></td>
    <td style="padding:10px 16px"></td>
  </tr>
  <tr style="background:#1a1a2e">
    <td style="padding:10px 16px;color:#aaa">Best Trade</td>
    <td style="padding:10px 16px;color:#27ae60;font-weight:bold">
      {float(best_trade.get('pnl',0)):+,.4f} USDT
      <span style="color:#888;font-size:10px">&nbsp;{best_trade.get('symbol','')}</span>
    </td>
    <td style="padding:10px 16px;color:#aaa">Worst Trade</td>
    <td colspan="3" style="padding:10px 16px;color:#e74c3c;font-weight:bold">
      {float(worst_trade.get('pnl',0)):+,.4f} USDT
      <span style="color:#888;font-size:10px">&nbsp;{worst_trade.get('symbol','')}</span>
    </td>
  </tr>
</table>"""

    # ── Trade-by-trade table ───────────────────────────────────────────────────
    rows_html: list[str] = []
    for i, t in enumerate(trades):
        pnl     = float(t.get("pnl", 0))
        pnl_pct = float(t.get("pnl_pct", 0))
        pnl_col = "#27ae60" if pnl > 0 else "#e74c3c"
        side_col = "#27ae60" if t.get("side") == "BUY" else "#e74c3c"

        exit_time = t.get("exit_time") or ""
        try:
            exit_ts = datetime.fromisoformat(exit_time).strftime("%H:%M:%S")
        except Exception:
            exit_ts = exit_time[11:19] if len(exit_time) > 18 else exit_time

        paper_badge = (
            ' <span style="color:#888;font-size:9px">[PAPER]</span>'
            if t.get("paper") else ""
        )
        bg = "background:#0e0e1a" if i % 2 == 0 else "background:#12121e"

        entry_p = float(t.get("entry_price", 0))
        exit_p  = float(t.get("exit_price", 0))
        qty     = float(t.get("quantity", 0))
        dur     = float(t.get("duration_minutes", 0))
        regime  = t.get("regime") or ""
        reason  = t.get("exit_reason") or ""

        rows_html.append(f"""
        <tr style="{bg}">
          <td style="padding:6px 8px;color:#aaa;white-space:nowrap;font-size:11px">{exit_ts}</td>
          <td style="padding:6px 8px;color:#e0e0f0;font-weight:bold;font-size:11px">
            {t.get('symbol','')}{paper_badge}
          </td>
          <td style="padding:6px 8px;color:{side_col};font-weight:bold;font-size:11px">
            {t.get('side','')}
          </td>
          <td style="padding:6px 8px;color:#ccc;text-align:right;font-size:11px">
            {entry_p:,.4f}
          </td>
          <td style="padding:6px 8px;color:#ccc;text-align:right;font-size:11px">
            {exit_p:,.4f}
          </td>
          <td style="padding:6px 8px;color:#ccc;text-align:right;font-size:11px">
            {qty:.6f}
          </td>
          <td style="padding:6px 8px;color:{pnl_col};font-weight:bold;
                     text-align:right;font-size:11px">{pnl:+,.4f}</td>
          <td style="padding:6px 8px;color:{pnl_col};text-align:right;font-size:11px">
            {pnl_pct:+.2f}%
          </td>
          <td style="padding:6px 8px;color:#888;text-align:right;font-size:11px">
            {dur:.0f}m
          </td>
          <td style="padding:6px 8px;color:#888;font-size:10px">{reason}</td>
          <td style="padding:6px 8px;color:#555;font-size:10px">{regime}</td>
        </tr>""")

    trades_html = f"""
<h3 style="color:#00D4FF;margin-top:28px">Trade Log</h3>
<table style="width:100%;border-collapse:collapse">
  <thead>
    <tr style="background:#1a1a2e">
      <th style="padding:6px 8px;text-align:left;color:#00D4FF;font-size:10px">Exit Time</th>
      <th style="padding:6px 8px;text-align:left;color:#00D4FF;font-size:10px">Symbol</th>
      <th style="padding:6px 8px;text-align:left;color:#00D4FF;font-size:10px">Side</th>
      <th style="padding:6px 8px;text-align:right;color:#00D4FF;font-size:10px">Entry</th>
      <th style="padding:6px 8px;text-align:right;color:#00D4FF;font-size:10px">Exit</th>
      <th style="padding:6px 8px;text-align:right;color:#00D4FF;font-size:10px">Qty</th>
      <th style="padding:6px 8px;text-align:right;color:#00D4FF;font-size:10px">P&amp;L (USDT)</th>
      <th style="padding:6px 8px;text-align:right;color:#00D4FF;font-size:10px">P&amp;L %</th>
      <th style="padding:6px 8px;text-align:right;color:#00D4FF;font-size:10px">Dur</th>
      <th style="padding:6px 8px;text-align:left;color:#00D4FF;font-size:10px">Exit Reason</th>
      <th style="padding:6px 8px;text-align:left;color:#00D4FF;font-size:10px">Regime</th>
    </tr>
  </thead>
  <tbody>{''.join(rows_html)}</tbody>
</table>"""

    summary = {
        "total_trades": len(trades),
        "total_pnl":    total_pnl,
        "win_rate":     win_rate,
        "wins":         len(wins),
        "losses":       len(losses),
    }

    return summary_html + trades_html, summary
