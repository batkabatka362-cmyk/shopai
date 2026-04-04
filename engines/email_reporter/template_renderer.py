"""Email Reporter Engine — template renderer.

Renders compiled report into email HTML and plain text.
"""
from __future__ import annotations

from typing import Any


def render_template(
    compiled_report: dict[str, Any],
) -> dict[str, Any]:
    """Render compiled report into email formats."""
    try:
        title = compiled_report.get("title", "Report")
        period = compiled_report.get("period", "")
        sections = compiled_report.get("sections", [])
        generated_at = compiled_report.get("generated_at", "")

        # Build subject
        subject = f"{title} — {period}"

        # Build HTML
        html_parts = [
            "<!DOCTYPE html><html><head><meta charset='utf-8'>",
            f"<title>{title}</title>",
            "<style>body{font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;}",
            "h1{color:#333;border-bottom:2px solid #007bff;padding-bottom:10px;}",
            "h2{color:#555;margin-top:20px;}.metric{display:inline-block;margin:10px;padding:15px;",
            "background:#f8f9fa;border-radius:8px;text-align:center;min-width:120px;}",
            ".metric-value{font-size:24px;font-weight:bold;color:#007bff;}",
            ".metric-label{font-size:12px;color:#666;margin-top:5px;}",
            "ul{padding-left:20px;}li{margin:5px 0;}",
            ".footer{margin-top:30px;padding-top:15px;border-top:1px solid #ddd;color:#999;font-size:12px;}",
            "</style></head><body>",
            f"<h1>{title}</h1>",
            f"<p style='color:#666;'>Period: {period}</p>",
        ]

        text_parts = [f"{title}\n{'=' * len(title)}\n", f"Period: {period}\n"]

        for section in sections:
            sec_title = section.get("title", "")
            sec_type = section.get("type", "text")
            content = section.get("content", {})

            html_parts.append(f"<h2>{sec_title}</h2>")
            text_parts.append(f"\n{sec_title}\n{'-' * len(sec_title)}")

            if sec_type == "metrics" and isinstance(content, dict):
                html_parts.append("<div>")
                for key, val in content.items():
                    label = key.replace("_", " ").title()
                    html_parts.append(
                        f"<div class='metric'><div class='metric-value'>{val}</div>"
                        f"<div class='metric-label'>{label}</div></div>"
                    )
                    text_parts.append(f"  {label}: {val}")
                html_parts.append("</div>")
            elif sec_type == "list" and isinstance(content, list):
                html_parts.append("<ul>")
                for item in content:
                    html_parts.append(f"<li>{item}</li>")
                    text_parts.append(f"  - {item}")
                html_parts.append("</ul>")
            else:
                html_parts.append(f"<p>{content}</p>")
                text_parts.append(f"  {content}")

        html_parts.append(f"<div class='footer'>Generated at {generated_at}</div>")
        html_parts.append("</body></html>")
        text_parts.append(f"\nGenerated at {generated_at}")

        return {
            "status": "success",
            "rendered": {
                "subject": subject,
                "html_content": "".join(html_parts),
                "text_content": "\n".join(text_parts),
            },
        }
    except Exception as exc:
        return {"status": "error", "rendered": {}, "error": f"Template rendering failed: {exc}"}
