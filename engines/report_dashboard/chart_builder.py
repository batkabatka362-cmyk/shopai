"""Report Dashboard Engine — chart builder.

Builds chart data structures for dashboard visualization.
"""
from __future__ import annotations

from typing import Any


def build_charts(
    metrics: list[dict[str, Any]],
    aggregated_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build chart data from metrics and aggregated data."""
    try:
        charts: list[dict[str, Any]] = []

        # Revenue trend chart
        revenue_metric = next((m for m in metrics if m.get("name") == "total_revenue"), {})
        current_rev = float(revenue_metric.get("value", 0))
        prev_rev = float(revenue_metric.get("previous_value", 0))
        charts.append({
            "chart_type": "line",
            "title": "Revenue Trend",
            "labels": ["Previous Period", "Current Period"],
            "datasets": [{"label": "Revenue", "data": [prev_rev, current_rev]}],
        })

        # Orders bar chart
        orders_metric = next((m for m in metrics if m.get("name") == "total_orders"), {})
        current_orders = float(orders_metric.get("value", 0))
        prev_orders = float(orders_metric.get("previous_value", 0))
        charts.append({
            "chart_type": "bar",
            "title": "Orders Comparison",
            "labels": ["Previous Period", "Current Period"],
            "datasets": [{"label": "Orders", "data": [prev_orders, current_orders]}],
        })

        # KPI summary chart (gauge-style data)
        kpi_names = ["conversion_rate", "roas", "avg_order_value"]
        kpi_values = []
        for name in kpi_names:
            m = next((m for m in metrics if m.get("name") == name), {})
            kpi_values.append(float(m.get("value", 0)))
        charts.append({
            "chart_type": "gauge",
            "title": "Key Performance Indicators",
            "labels": kpi_names,
            "datasets": [{"label": "Current", "data": kpi_values}],
        })

        # Data source breakdown (pie)
        source_labels = []
        source_counts = []
        for agg in aggregated_data:
            source_labels.append(agg.get("source", ""))
            source_counts.append(agg.get("records_count", 0))
        charts.append({
            "chart_type": "pie",
            "title": "Data Source Distribution",
            "labels": source_labels,
            "datasets": [{"label": "Records", "data": source_counts}],
        })

        return {"status": "success", "charts": charts}
    except Exception as exc:
        return {"status": "error", "charts": [], "error": f"Chart building failed: {exc}"}
