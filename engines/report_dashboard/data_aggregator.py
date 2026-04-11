"""Report Dashboard Engine — data aggregator.

Aggregates data from multiple engine sources for dashboard generation.
"""
from __future__ import annotations

import copy
from typing import Any


_SOURCE_DEFAULTS = {
    "orders": {"total_orders": 0, "total_revenue": 0, "avg_order_value": 0},
    "products": {"total_products": 0, "active_products": 0, "out_of_stock": 0},
    "customers": {"total_customers": 0, "new_customers": 0, "returning_customers": 0},
    "marketing": {"total_spend": 0, "total_clicks": 0, "total_conversions": 0},
}


def aggregate_data(
    data_sources: list[str],
    period: str,
    raw_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate data from specified sources."""
    try:
        raw_data = copy.deepcopy(raw_data or {})
        aggregated: list[dict[str, Any]] = []

        for source in data_sources:
            source_data = raw_data.get(source, {})
            defaults = _SOURCE_DEFAULTS.get(source, {})

            summary = {}
            for key, default in defaults.items():
                summary[key] = source_data.get(key, default)

            records_count = int(source_data.get("records_count", 0))

            aggregated.append({
                "source": source,
                "records_count": records_count,
                "summary": summary,
            })

        return {"status": "success", "aggregated": aggregated}
    except Exception as exc:
        return {"status": "error", "aggregated": [], "error": f"Data aggregation failed: {exc}"}
