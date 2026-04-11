"""Data Enrichment Engine — feature builder.

Builds derived features from raw data: ratios, categories,
bins, interaction terms, and computed attributes.
"""
from __future__ import annotations

import copy
from typing import Any


def build_features(
    raw_data: list[dict[str, Any]],
    computed_stats: list[dict[str, Any]],
    enrichment_level: str = "standard",
) -> dict[str, Any]:
    """Build derived features from raw data and computed stats.

    Args:
        raw_data: Original raw data records.
        computed_stats: Stats computed by stat_calculator.
        enrichment_level: Level of feature derivation.

    Returns:
        Structured dict with derived features.
    """
    try:
        records = copy.deepcopy(raw_data)
        stats_map = {
            s.get("record_id", ""): s.get("stats", {})
            for s in computed_stats
        }

        features: list[dict[str, Any]] = []

        for record in records:
            record_id = str(record.get("id", record.get("product_id", "unknown")))
            record_stats = stats_map.get(record_id, {})

            # Price tier feature
            price = record_stats.get("price") or record.get("price")
            if price is not None:
                price = float(price)
                tier = _price_tier(price)
                features.append({
                    "feature_name": f"{record_id}_price_tier",
                    "feature_value": tier,
                    "source_fields": ["price"],
                    "confidence": 1.0,
                })

            # Margin category feature
            margin_pct = record_stats.get("margin_pct")
            if margin_pct is not None:
                cat = _margin_category(margin_pct)
                features.append({
                    "feature_name": f"{record_id}_margin_category",
                    "feature_value": cat,
                    "source_fields": ["price", "cost"],
                    "confidence": 1.0,
                })

            # Velocity feature
            sold = record_stats.get("quantity_sold") or record.get("quantity_sold")
            if sold is not None:
                velocity = _velocity_class(float(sold))
                features.append({
                    "feature_name": f"{record_id}_velocity",
                    "feature_value": velocity,
                    "source_fields": ["quantity_sold"],
                    "confidence": 0.9,
                })

            # Deep enrichment: interaction features
            if enrichment_level == "deep" and price and sold:
                revenue_velocity = round(float(price) * float(sold), 2)
                features.append({
                    "feature_name": f"{record_id}_revenue_velocity",
                    "feature_value": revenue_velocity,
                    "source_fields": ["price", "quantity_sold"],
                    "confidence": 0.85,
                })

        return {
            "status": "success",
            "features": features,
            "total_features": len(features),
        }
    except Exception as exc:
        return {
            "status": "error",
            "features": [],
            "error": f"Feature building failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _price_tier(price: float) -> str:
    """Classify price into tier."""
    if price < 10:
        return "budget"
    elif price < 50:
        return "mid_range"
    elif price < 200:
        return "premium"
    return "luxury"


def _margin_category(margin_pct: float) -> str:
    """Classify margin percentage into category."""
    if margin_pct < 10:
        return "thin"
    elif margin_pct < 30:
        return "moderate"
    elif margin_pct < 60:
        return "healthy"
    return "high"


def _velocity_class(quantity: float) -> str:
    """Classify sales velocity."""
    if quantity < 5:
        return "slow"
    elif quantity < 50:
        return "moderate"
    elif quantity < 200:
        return "fast"
    return "very_fast"
