# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — Real data-driven auto-reports with PDF generation."""

import logging
import os
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(os.path.expanduser("~/.pry/reports_real"))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
    )

    _has_reportlab = True
except ImportError:
    _has_reportlab = False


class ReportGenerator:
    """Generate real data-driven reports with charts and PDF export."""

    def __init__(self) -> None:
        self.styles = getSampleStyleSheet() if _has_reportlab else None

    def generate(
        self,
        report_type: str,
        data: dict[str, Any],
        output_format: str = "html",
        title: str = "Report",
        branding: dict | None = None,
    ) -> dict[str, Any]:
        """Generate a data-driven report from real data.

        Args:
            report_type: "competitive", "price_monitor", "seo_audit", "content_tracker", "anomaly_summary"
            data: Real data from database/cache
            output_format: "html" or "pdf"
            title: Report title
            branding: {"company": "...", "color": "#hex"}
        """
        branding = branding or {}
        if report_type == "competitive":
            content = self._competitive_report(data, title, branding)
        elif report_type == "price_monitor":
            content = self._price_report(data, title, branding)
        elif report_type == "seo_audit":
            content = self._seo_report(data, title, branding)
        elif report_type == "anomaly_summary":
            content = self._anomaly_report(data, title, branding)
        else:
            return {"error": f"Unknown report type: {report_type}"}

        if output_format == "pdf" and _has_reportlab:
            pdf_path = self._to_pdf(content, title, branding)
            return {"success": True, "path": str(pdf_path), "format": "pdf"}

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        html_path = REPORTS_DIR / f"{report_type}_{timestamp}.html"
        html_path.write_text(self._wrap_html(content, title, branding))
        return {"success": True, "path": str(html_path), "format": "html"}

    def _competitive_report(self, data: dict, title: str, branding: dict) -> str:
        competitors = data.get("competitors", [])
        changes = data.get("changes", [])
        body = f"""
        <h2>Competitive Analysis</h2>
        <p>Report generated: {datetime.now(UTC).strftime('%B %d, %Y')}</p>
        <h3>Competitors Tracked ({len(competitors)})</h3>
        <table>
            <thead><tr><th>Name</th><th>Price</th><th>Change</th><th>Last Updated</th></tr></thead>
            <tbody>
        """
        for c in competitors:
            change = c.get("price_change", 0) or 0
            change_str = f"{change:+.1f}%" if change else "—"
            change_class = "up" if change > 0 else "down" if change < 0 else "stable"
            body += (
                f"<tr><td>{c.get('name','')}</td>"
                f"<td>${c.get('price',0):.2f}</td>"
                f"<td class='{change_class}'>{change_str}</td>"
                f"<td>{c.get('last_updated','')}</td></tr>"
            )
        body += "</tbody></table>"

        if changes:
            body += "<h3>Recent Changes</h3><ul>"
            for c in changes[:20]:
                body += f"<li>{c}</li>"
            body += "</ul>"
        return body

    def _price_report(self, data: dict, title: str, branding: dict) -> str:
        products = data.get("products", [])
        drops = sum(1 for p in products if (p.get("price_change") or 0) < 0)
        rises = sum(1 for p in products if (p.get("price_change") or 0) > 0)
        body = f"""
        <h2>Price Monitoring Report</h2>
        <p>Generated: {datetime.now(UTC).strftime('%B %d, %Y')}</p>
        <div class='summary'>
            <div class='stat'><h3>{len(products)}</h3><p>Products</p></div>
            <div class='stat up'><h3>{drops}</h3><p>Price Drops</p></div>
            <div class='stat down'><h3>{rises}</h3><p>Price Rises</p></div>
        </div>
        <table><thead><tr><th>Product</th><th>Previous</th><th>Current</th><th>Change</th></tr></thead><tbody>
        """
        for p in products[:50]:
            pc = p.get("price_change", 0) or 0
            change_str = f"{pc:+.1f}%" if pc else "stable"
            change_class = "down" if pc < 0 else "up" if pc > 0 else "stable"
            body += (
                f"<tr><td>{p.get('name','')}</td>"
                f"<td>${p.get('previous_price',0):.2f}</td>"
                f"<td>${p.get('current_price',0):.2f}</td>"
                f"<td class='{change_class}'>{change_str}</td></tr>"
            )
        body += "</tbody></table>"
        return body

    def _seo_report(self, data: dict, title: str, branding: dict) -> str:
        seo = data.get("seo_data", {})
        changes = data.get("changes", [])
        title_text = (seo.get("title") or "N/A")[:100]
        desc = (seo.get("meta_description") or "N/A")[:200]
        body = f"""
        <h2>SEO Audit Report</h2>
        <p>Generated: {datetime.now(UTC).strftime('%B %d, %Y')}</p>
        <h3>Current SEO Status</h3>
        <table>
            <tr><td><strong>Title</strong></td><td>{title_text}</td></tr>
            <tr><td><strong>Meta Description</strong></td><td>{desc}</td></tr>
            <tr><td><strong>Word Count</strong></td><td>{seo.get('word_count', 0):,}</td></tr>
            <tr><td><strong>Internal Links</strong></td><td>{seo.get('links_internal', 0)}</td></tr>
            <tr><td><strong>External Links</strong></td><td>{seo.get('links_external', 0)}</td></tr>
            <tr><td><strong>Schema Markup</strong></td><td>{'Yes' if seo.get('has_schema') else 'No'}</td></tr>
        </table>
        """
        if changes:
            body += "<h3>Recent SEO Changes</h3><ul>"
            for c in changes[:20]:
                body += (
                    f"<li>{c.get('field','')}: {str(c.get('to',''))[:80]}</li>"
                )
            body += "</ul>"
        return body

    def _anomaly_report(self, data: dict, title: str, branding: dict) -> str:
        anomalies = data.get("anomalies", [])
        body = f"""
        <h2>Anomaly Summary Report</h2>
        <p>Generated: {datetime.now(UTC).strftime('%B %d, %Y')}</p>
        <h3>Detected Anomalies ({len(anomalies)})</h3>
        <table><thead><tr><th>Field</th><th>Type</th><th>Severity</th><th>Reason</th></tr></thead><tbody>
        """
        for a in anomalies:
            body += (
                f"<tr><td>{a.get('field','')}</td>"
                f"<td>{a.get('type','')}</td>"
                f"<td>{a.get('severity','')}</td>"
                f"<td>{a.get('reason','')}</td></tr>"
            )
        body += "</tbody></table>"
        return body

    def _to_pdf(self, html_content: str, title: str, branding: dict) -> Path:
        """Convert HTML report to PDF using reportlab."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        pdf_path = REPORTS_DIR / f"report_{timestamp}.pdf"
        doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
        story: list[Any] = []
        assert self.styles is not None
        title_style = ParagraphStyle(
            "title",
            parent=self.styles["Heading1"],
            textColor=colors.HexColor(branding.get("color", "#f59e0b")),
        )
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 0.3 * inch))

        class SimpleHTMLToPDF(HTMLParser):
            def __init__(self, story: list[Any], styles: Any) -> None:
                super().__init__()
                self.story = story
                self.styles = styles
                self.current_row: list[str] = []
                self.in_table = False

            def handle_starttag(self, tag: str, attrs: list) -> None:
                if tag in ("h2", "h3"):
                    self.story.append(Paragraph("&nbsp;", self.styles["Normal"]))
                elif tag == "tr":
                    self.current_row = []

            def handle_endtag(self, tag: str) -> None:
                if tag == "tr" and self.current_row:
                    import contextlib
                    with contextlib.suppress(Exception):
                        self.story.append(
                            Table(
                                [self.current_row],
                                colWidths=[2 * inch] * len(self.current_row),
                            )
                        )
                elif tag == "table":
                    self.story.append(Spacer(1, 0.1 * inch))

            def handle_data(self, data: str) -> None:
                data = data.strip()
                if not data:
                    return
                safe = data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                if len(safe) > 100:
                    safe = safe[:100] + "..."
                if self.in_table:
                    self.current_row.append(safe)
                else:
                    import contextlib
                    with contextlib.suppress(Exception):
                        self.story.append(Paragraph(safe, self.styles["Normal"]))

        SimpleHTMLToPDF(story, self.styles).feed(html_content)
        doc.build(story)
        return pdf_path

    def _wrap_html(self, body: str, title: str, branding: dict) -> str:
        """Wrap report body in full HTML with branding."""
        company = branding.get("company", "Pry")
        color = branding.get("color", "#f59e0b")
        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>{title}</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 40px; color: #1a1a2e; }}
h1 {{ color: {color}; border-bottom: 3px solid {color}; padding-bottom: 10px; }}
h2 {{ color: {color}; margin-top: 30px; }}
h3 {{ color: #444; }}
table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
th {{ background: {color}; color: white; padding: 10px; text-align: left; }}
td {{ padding: 8px; border-bottom: 1px solid #eee; }}
.summary {{ display: flex; gap: 20px; margin: 20px 0; }}
.stat {{ flex: 1; padding: 20px; background: #f8f8f8; border-radius: 8px; text-align: center; border-top: 3px solid {color}; }}
.stat h3 {{ font-size: 36px; margin: 0; }}
.up {{ color: #16a34a; }}
.down {{ color: #dc2626; }}
.stable {{ color: #6b7280; }}
.footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; font-size: 12px; color: #666; text-align: center; }}
</style></head>
<body>
<h1>{title}</h1>
{body}
<div class='footer'>Generated by {company} on {datetime.now(UTC).strftime('%B %d, %Y at %H:%M UTC')}</div>
</body></html>"""
