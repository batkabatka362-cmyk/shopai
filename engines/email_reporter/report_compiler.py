"""Email Reporter Engine — report compiler.

Compiles report from dashboard data into structured sections.
"""
from __future__ import annotations

import copy
import time
from typing import Any


def compile_report(
    report_type: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Compile report from dashboard data."""
    try:
        data = copy.deepcopy(data)

        title_map = {
            "daily": "Daily Business Report",
            "weekly": "Weekly Performance Summary",
            "monthly": "Monthly Business Review",
        }
        title = title_map.get(report_type, f"{report_type.title()} Report")

        period_map = {
            "daily": "Last 24 hours",
            "weekly": "Last 7 days",
            "monthly": "Last 30 days",
        }
        period = period_map.get(report_type, "Custom period")

        # Build report sections
        sections: list[dict[str, Any]] = []

        # Revenue section
        metrics = data.get("metrics", {})
        sections.append({
            "title": "Revenue Overview",
            "type": "metrics",
            "content": {
                "total_revenue": metrics.get("total_revenue", 0),
                "total_orders": metrics.get("total_orders", 0),
                "avg_order_value": metrics.get("avg_order_value", 0),
            },
        })

        # Performance section
        sections.append({
            "title": "Marketing Performance",
            "type": "metrics",
            "content": {
                "conversion_rate": metrics.get("conversion_rate", 0),
                "roas": metrics.get("roas", 0),
                "cac": metrics.get("cac", 0),
            },
        })

        # Highlights section
        highlights = data.get("highlights", [])
        if highlights:
            sections.append({
                "title": "Key Highlights",
                "type": "list",
                "content": highlights,
            })

        # Action items section
        action_items = data.get("action_items", [])
        if action_items:
            sections.append({
                "title": "Action Items",
                "type": "list",
                "content": action_items,
            })

        compiled = {
            "title": title,
            "sections": sections,
            "metrics_summary": metrics,
            "period": period,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        return {"status": "success", "compiled_report": compiled}
    except Exception as exc:
        return {"status": "error", "compiled_report": {}, "error": f"Report compilation failed: {exc}"}
