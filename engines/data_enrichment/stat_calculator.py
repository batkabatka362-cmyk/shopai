"""Data Enrichment Engine — stat calculator.

Computes product/customer statistics from raw data records:
averages, totals, counts, percentiles, and derived metrics.
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_stats(
    raw_data: list[dict[str, Any]],
    enrichment_level: str = "standard",
) -> dict[str, Any]:
    """Compute statistics for each record in the raw data.

    Args:
        raw_data: List of raw data records.
        enrichment_level: Level of enrichment (basic, standard, deep).

    Returns:
        Structured dict with computed stats per record.
    """
    try:
        records = copy.deepcopy(raw_data)
        stats: list[dict[str, Any]] = []

        numeric_fields = _identify_numeric_fields(records)

        for record in records:
            record_id = str(record.get("id", record.get("product_id", "unknown")))
            record_stats: dict[str, float] = {}

            for field in numeric_fields:
                val = record.get(field)
                if val is not None:
                    try:
                        record_stats[field] = float(val)
                    except (ValueError, TypeError):
                        continue

            # Derived stats
            if "price" in record_stats and "cost" in record_stats:
                price = record_stats["price"]
                cost = record_stats["cost"]
                record_stats["margin"] = round(price - cost, 2)
                record_stats["margin_pct"] = (
                    round((price - cost) / price * 100, 2) if price > 0 else 0.0
                )

            if "quantity_sold" in record_stats and "quantity_available" in record_stats:
                sold = record_stats["quantity_sold"]
                avail = record_stats["quantity_available"]
                total = sold + avail
                record_stats["sell_through_rate"] = (
                    round(sold / total * 100, 2) if total > 0 else 0.0
                )

            if enrichment_level == "deep" and "revenue" in record_stats:
                record_stats["revenue_per_unit"] = (
                    round(record_stats["revenue"] / record_stats.get("quantity_sold", 1), 2)
                    if record_stats.get("quantity_sold", 0) > 0 else 0.0
                )

            stats.append({
                "record_id": record_id,
                "stats": record_stats,
                "stat_type": enrichment_level,
            })

        return {
            "status": "success",
            "stats": stats,
            "total_computed": len(stats),
            "numeric_fields_found": numeric_fields,
        }
    except Exception as exc:
        return {
            "status": "error",
            "stats": [],
            "error": f"Stat calculation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _identify_numeric_fields(records: list[dict[str, Any]]) -> list[str]:
    """Identify fields that contain numeric values across records."""
    if not records:
        return []

    field_counts: dict[str, int] = {}
    for record in records[:50]:  # Sample first 50
        for key, val in record.items():
            if isinstance(val, (int, float)):
                field_counts[key] = field_counts.get(key, 0) + 1

    threshold = max(1, len(records[:50]) // 4)
    return [f for f, c in field_counts.items() if c >= threshold]
