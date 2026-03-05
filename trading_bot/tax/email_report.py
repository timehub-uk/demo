"""
Monthly tax report generator and email sender.
Generates PDF reports with full HMRC-compliant trade records
and sends them via SendGrid or SMTP.
"""

from __future__ import annotations

import smtplib
import calendar
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
from pathlib import Path
from typing import Optional

from loguru import logger
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable
)

from config import get_settings
from .uk_tax import UKTaxCalculator, TaxYearSummary

REPORT_DIR = Path.home() / ".binanceml" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


class TaxEmailReporter:
    """Generates PDF reports and dispatches monthly email summaries."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._calc = UKTaxCalculator()

    # ── Main entry ─────────────────────────────────────────────────────
    def generate_and_send_monthly(self, year: int, month: int, user_id: str | None = None) -> bool:
        """Generate PDF report for the given month and email it."""
        data = self._calc.monthly_summary(year, month, user_id)
        pdf_path = self._generate_pdf(year, month, data)
        if pdf_path:
            return self._send_email(year, month, data, pdf_path)
        return False

    def generate_annual_report(self, tax_year: str, user_id: str | None = None) -> Optional[Path]:
        """Generate a full annual CGT report PDF."""
        summary = self._calc.calculate_tax_year(tax_year, user_id)
        return self._generate_annual_pdf(tax_year, summary)

    # ── PDF generation ─────────────────────────────────────────────────
    def _generate_pdf(self, year: int, month: int, data: dict) -> Optional[Path]:
        month_name = calendar.month_name[month]
        filename = REPORT_DIR / f"tax_report_{year}_{month:02d}.pdf"

        doc = SimpleDocTemplate(
            str(filename),
            pagesize=A4,
            rightMargin=20*mm, leftMargin=20*mm,
            topMargin=20*mm, bottomMargin=20*mm,
        )
        styles = getSampleStyleSheet()
        story = []

        # Title
        title_style = ParagraphStyle(
            "Title", parent=styles["Title"],
            fontSize=18, textColor=colors.HexColor("#1a1a2e"),
            spaceAfter=6,
        )
        story.append(Paragraph("BinanceML Pro – Crypto Tax Report", title_style))
        story.append(Paragraph(f"{month_name} {year}", styles["Heading2"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
        story.append(Spacer(1, 10))

        # Summary table
        s = self._settings
        summary_data = [
            ["Report Period:", f"{month_name} {year}"],
            ["UK Tax Year:", data["tax_year"]],
            ["Total Proceeds (GBP):", f"£{data['total_proceeds_gbp']:,.2f}"],
            ["Total Cost (GBP):", f"£{data['total_cost_gbp']:,.2f}"],
            ["Net Capital Gain/Loss:", f"£{data['net_gain_gbp']:,.2f}"],
            ["Number of Disposals:", str(data["disposals_count"])],
        ]
        tbl = Table(summary_data, colWidths=[80*mm, 80*mm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#f0f4f8")),
            ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("GRID", (0,0), (-1,-1), 0.5, colors.lightgrey),
            ("PADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 15))

        # Disposals table
        if data["disposals"]:
            story.append(Paragraph("Capital Disposals", styles["Heading3"]))
            headers = ["Date", "Asset", "Qty", "Proceeds (£)", "Cost (£)", "Gain/Loss (£)", "Rule"]
            rows = [headers]
            for d in data["disposals"]:
                dt = datetime.fromisoformat(d["date"]).strftime("%d/%m/%Y")
                gl = d["gain_loss_gbp"]
                rows.append([
                    dt, d["asset"],
                    f"{d['quantity']:.6f}",
                    f"{d['proceeds_gbp']:,.2f}",
                    f"{d['cost_gbp']:,.2f}",
                    f"{gl:+,.2f}",
                    d.get("rule", "S104"),
                ])
            d_tbl = Table(rows, repeatRows=1)
            d_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a1a2e")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 8),
                ("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f9f9f9")]),
                ("PADDING", (0,0), (-1,-1), 4),
                ("ALIGN", (2,0), (-1,-1), "RIGHT"),
            ]))
            story.append(d_tbl)

        story.append(Spacer(1, 20))
        story.append(Paragraph(
            "This report is generated for HMRC record-keeping purposes. "
            "Please consult a qualified tax adviser for advice on your individual circumstances.",
            styles["Italic"],
        ))
        story.append(Paragraph(
            f"Generated by BinanceML Pro on {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            styles["Normal"],
        ))

        doc.build(story)
        logger.info(f"PDF report saved: {filename}")
        return filename

    def _generate_annual_pdf(self, tax_year: str, summary: TaxYearSummary) -> Optional[Path]:
        filename = REPORT_DIR / f"annual_cgt_{tax_year.replace('/', '_')}.pdf"
        doc = SimpleDocTemplate(str(filename), pagesize=A4,
                                rightMargin=20*mm, leftMargin=20*mm,
                                topMargin=20*mm, bottomMargin=20*mm)
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph(f"UK CGT Annual Report – Tax Year {tax_year}", styles["Title"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
        story.append(Spacer(1, 10))

        tax_data = [
            ["Total Proceeds:", f"£{float(summary.total_proceeds):,.2f}"],
            ["Total Acquisition Cost:", f"£{float(summary.total_cost):,.2f}"],
            ["Total Gains:", f"£{float(summary.total_gains):,.2f}"],
            ["Total Losses:", f"£{float(summary.total_losses):,.2f}"],
            ["Net Capital Gain:", f"£{float(summary.net_gain):,.2f}"],
            ["Annual CGT Allowance:", f"£{float(summary.annual_allowance):,.2f}"],
            ["Taxable Gain:", f"£{float(summary.taxable_gain):,.2f}"],
            ["Estimated Tax (Basic Rate 10%):", f"£{float(summary.estimated_tax_basic):,.2f}"],
            ["Estimated Tax (Higher Rate 20%):", f"£{float(summary.estimated_tax_higher):,.2f}"],
        ]
        tbl = Table(tax_data, colWidths=[100*mm, 60*mm])
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("GRID", (0,0), (-1,-1), 0.5, colors.lightgrey),
            ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#f0f4f8")),
            ("BACKGROUND", (0,-3), (-1,-1), colors.HexColor("#fff8e1")),
            ("FONTNAME", (0,-3), (-1,-1), "Helvetica-Bold"),
            ("PADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(tbl)
        doc.build(story)
        return filename

    # ── Email sending ──────────────────────────────────────────────────
    def _send_email(self, year: int, month: int, data: dict, pdf_path: Path) -> bool:
        settings = self._settings
        if not settings.user.email:
            logger.warning("No user email configured – skipping email.")
            return False

        month_name = calendar.month_name[month]
        subject = f"BinanceML Pro – Tax Report {month_name} {year}"

        # HTML body
        gl = data["net_gain_gbp"]
        colour = "#27ae60" if gl >= 0 else "#e74c3c"
        html = f"""
        <html><body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
        <div style="background:white; border-radius:8px; padding:30px; max-width:600px; margin:auto;">
          <h2 style="color:#1a1a2e;">🏦 BinanceML Pro Monthly Tax Report</h2>
          <h3 style="color:#555;">{month_name} {year} | UK Tax Year {data['tax_year']}</h3>
          <table style="width:100%; border-collapse:collapse; margin-top:20px;">
            <tr style="background:#f0f4f8;"><td style="padding:10px;"><b>Total Proceeds</b></td>
              <td style="padding:10px;">£{data['total_proceeds_gbp']:,.2f}</td></tr>
            <tr><td style="padding:10px;"><b>Total Cost Basis</b></td>
              <td style="padding:10px;">£{data['total_cost_gbp']:,.2f}</td></tr>
            <tr style="background:#f0f4f8;"><td style="padding:10px;"><b>Net Gain / Loss</b></td>
              <td style="padding:10px; color:{colour}; font-weight:bold;">£{gl:+,.2f}</td></tr>
            <tr><td style="padding:10px;"><b>Number of Disposals</b></td>
              <td style="padding:10px;">{data['disposals_count']}</td></tr>
          </table>
          <p style="color:#888; font-size:12px; margin-top:20px;">
            Full HMRC-compliant PDF report is attached. Please consult a qualified tax adviser.
          </p>
        </div></body></html>
        """

        try:
            msg = MIMEMultipart("mixed")
            msg["Subject"] = subject
            msg["From"] = "noreply@binancemlpro.local"
            msg["To"] = settings.user.email
            msg.attach(MIMEText(html, "html"))

            with open(pdf_path, "rb") as f:
                part = MIMEApplication(f.read(), Name=pdf_path.name)
                part["Content-Disposition"] = f'attachment; filename="{pdf_path.name}"'
                msg.attach(part)

            # SendGrid via SMTP relay
            with smtplib.SMTP("smtp.sendgrid.net", 587) as server:
                server.starttls()
                server.login("apikey", settings.ai.claude_api_key or "dummy")
                server.sendmail(msg["From"], [msg["To"]], msg.as_string())

            logger.info(f"Tax report emailed to {settings.user.email}")
            return True

        except Exception as exc:
            logger.error(f"Email send failed: {exc}")
            return False
