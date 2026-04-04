"""Report Dashboard Engine — summary writer.

Writes executive summary, highlights, and action items from metrics.
"""
from __future__ import annotations

from typing import Any


def write_summary(
    metrics: list[dict[str, Any]],
    period: str,
) -> dict[str, Any]:
    """Write executive summary from dashboard metrics."""
    try:
        highlights: list[str] = []
        action_items: list[str] = []

        for m in metrics:
            name = m.get("name", "").replace("_", " ").title()
            change = float(m.get("change_pct", 0))
            trend = m.get("trend", "stable")

            if change > 5:
                highlights.append(f"{name} increased by {change}% — strong performance")
            elif change < -5:
                highlights.append(f"{name} decreased by {abs(change)}% — needs attention")
                action_items.append(f"Investigate {name.lower()} decline and develop improvement plan")

        # General action items based on metrics
        revenue_metric = next((m for m in metrics if m.get("name") == "total_revenue"), {})
        if float(revenue_metric.get("value", 0)) > 0:
            roas_metric = next((m for m in metrics if m.get("name") == "roas"), {})
            if float(roas_metric.get("value", 0)) < 3.0:
                action_items.append("ROAS below 3.0 — review marketing spend efficiency")

        conv_metric = next((m for m in metrics if m.get("name") == "conversion_rate"), {})
        if float(conv_metric.get("value", 0)) < 2.0:
            action_items.append("Conversion rate below 2% — consider A/B testing checkout flow")

        if not highlights:
            highlights.append("Performance is stable across all key metrics")

        summary_text = f"Dashboard for {period}: "
        up_count = sum(1 for m in metrics if m.get("trend") == "up")
        down_count = sum(1 for m in metrics if m.get("trend") == "down")
        summary_text += f"{up_count} metrics trending up, {down_count} trending down."

        period_comparison = {
            "current_period": period,
            "previous_period": "previous",
            "metrics": metrics,
        }

        return {
            "status": "success",
            "summary": summary_text,
            "highlights": highlights,
            "action_items": action_items,
            "period_comparison": period_comparison,
        }
    except Exception as exc:
        return {"status": "error", "summary": "", "highlights": [], "action_items": [], "error": f"Summary writing failed: {exc}"}
