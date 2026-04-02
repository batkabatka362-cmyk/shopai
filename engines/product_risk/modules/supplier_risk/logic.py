"""Supplier risk decision logic — diversification, safety stock, contingency.

Takes supplier risk assessment and produces actionable plans:
  - How to diversify the supplier base
  - How much safety stock to hold given the risk level
  - What contingency plans to prepare
"""
from __future__ import annotations

from typing import Any


# Safety stock multipliers based on risk level
SAFETY_STOCK_MULTIPLIERS = {
    "low": 1.0,       # Standard safety stock
    "moderate": 1.5,   # 50% extra buffer
    "high": 2.5,       # 2.5x standard
    "critical": 4.0,   # 4x standard — emergency buffer
}

# Minimum safety stock in days by supplier region
MIN_SAFETY_STOCK_DAYS = {
    "domestic": 14,
    "north_america": 21,
    "europe": 30,
    "asia": 60,       # Min 2 months for overseas
    "default": 45,
}


def recommend_supplier_diversification(
    risk: dict[str, Any],
) -> dict[str, Any]:
    """Recommend how to diversify the supplier base given current risk.

    Args:
        risk: Output from code.assess_supplier_risk()["data"]

    Returns:
        Diversification plan with specific actions.
    """
    concentration = risk.get("concentration_risk", {})
    dims = risk.get("dimensions", {})
    dep_score = dims.get("single_source_dependency", {}).get("score", 50)
    geo_score = dims.get("geopolitical_stability", {}).get("score", 50)
    composite = risk.get("composite_score", 50)

    actions = []
    target_suppliers = 1

    # Determine target supplier count
    if dep_score >= 75:
        target_suppliers = 3
        actions.append(
            "URGENT: Find at least 2 additional suppliers immediately. "
            "Single-source dependency is at critical levels."
        )
    elif dep_score >= 50:
        target_suppliers = 2
        actions.append(
            "Add at least 1 backup supplier. Test with a small order to validate "
            "quality and reliability before committing volume."
        )
    else:
        target_suppliers = max(2, concentration.get("supplier_count", 1))
        actions.append("Supplier diversification is adequate. Maintain current relationships.")

    # Geographic diversification
    if geo_score >= 60:
        actions.append(
            "Diversify geographically — source from at least 2 different countries. "
            "Single-country dependency amplifies geopolitical risk."
        )

    # Volume distribution recommendation
    if target_suppliers >= 3:
        distribution = "50-30-20"
        actions.append(
            "Target a 50/30/20 volume split across 3 suppliers. "
            "No single supplier should handle more than 50%."
        )
    elif target_suppliers == 2:
        distribution = "60-40"
        actions.append(
            "Target a 60/40 volume split across 2 suppliers. "
            "Primary handles most volume, secondary stays warm."
        )
    else:
        distribution = "100"

    # Quality-based diversification
    quality_score = dims.get("quality_consistency", {}).get("score", 50)
    if quality_score >= 60:
        actions.append(
            "Current supplier has quality issues. Use the backup supplier "
            "as leverage to demand improvement — or shift volume."
        )

    return {
        "current_supplier_count": concentration.get("supplier_count", 1),
        "target_supplier_count": target_suppliers,
        "recommended_distribution": distribution,
        "urgency": "immediate" if dep_score >= 75 else "short_term" if dep_score >= 50 else "maintenance",
        "actions": actions,
    }


def calculate_safety_stock_for_risk(
    risk_level: str,
    lead_time_days: int,
    daily_sales_units: float = 10,
    supplier_region: str = "asia",
) -> dict[str, Any]:
    """Calculate recommended safety stock based on risk level and lead time.

    Args:
        risk_level: low | moderate | high | critical
        lead_time_days: Standard lead time in days
        daily_sales_units: Average daily sales volume
        supplier_region: domestic | north_america | europe | asia

    Returns:
        Safety stock recommendation in days and units.
    """
    multiplier = SAFETY_STOCK_MULTIPLIERS.get(risk_level, 1.5)
    min_days = MIN_SAFETY_STOCK_DAYS.get(supplier_region, MIN_SAFETY_STOCK_DAYS["default"])

    # Base safety stock = lead time coverage
    base_days = max(lead_time_days * 0.5, min_days)
    adjusted_days = round(base_days * multiplier)

    # Units calculation
    safety_units = round(adjusted_days * daily_sales_units)

    # Cost estimate (rough, assuming $10 avg cost per unit)
    estimated_cost = safety_units * 10

    # Reorder point
    reorder_point_units = round((lead_time_days * daily_sales_units) + safety_units)

    return {
        "risk_level": risk_level,
        "lead_time_days": lead_time_days,
        "safety_stock_days": adjusted_days,
        "safety_stock_units": safety_units,
        "reorder_point_units": reorder_point_units,
        "multiplier_applied": multiplier,
        "min_days_for_region": min_days,
        "estimated_holding_cost_usd": estimated_cost,
        "recommendation": (
            f"Hold {adjusted_days} days of safety stock ({safety_units} units). "
            f"Reorder when inventory drops to {reorder_point_units} units."
        ),
    }


def build_contingency_plan(
    risks: dict[str, Any],
) -> dict[str, Any]:
    """Build a contingency plan based on the supplier risk assessment.

    Args:
        risks: Output from code.assess_supplier_risk()["data"]

    Returns:
        Contingency plan with triggers, actions, and priorities.
    """
    dims = risks.get("dimensions", {})
    composite = risks.get("composite_score", 50)
    plans = []

    # Plan for supplier failure
    dep_score = dims.get("single_source_dependency", {}).get("score", 50)
    if dep_score >= 40:
        plans.append({
            "trigger": "Primary supplier fails to deliver or goes out of business",
            "probability": "high" if dep_score >= 70 else "moderate",
            "impact": "severe",
            "actions": [
                "Activate backup supplier within 48 hours",
                "Place emergency order at premium pricing if needed",
                "Communicate delay expectations to customers proactively",
                "Review and activate safety stock to cover gap",
            ],
            "preparation": [
                "Keep backup supplier relationship warm with quarterly small orders",
                "Maintain updated pricing and MOQ from backup supplier",
                "Have purchase order templates ready to execute immediately",
            ],
        })

    # Plan for quality collapse
    quality_score = dims.get("quality_consistency", {}).get("score", 50)
    if quality_score >= 40:
        plans.append({
            "trigger": "Defect rate spikes above 10% on a shipment",
            "probability": "moderate" if quality_score >= 60 else "low",
            "impact": "high",
            "actions": [
                "Quarantine the affected shipment immediately",
                "Request replacement batch or credit from supplier",
                "Increase inspection frequency for next 3 shipments",
                "Source a test batch from backup supplier",
            ],
            "preparation": [
                "Define quality acceptance criteria in writing with supplier",
                "Set up pre-shipment inspection with a third-party service",
                "Keep 2 weeks of known-good inventory as a quality buffer",
            ],
        })

    # Plan for geopolitical disruption
    geo_score = dims.get("geopolitical_stability", {}).get("score", 50)
    if geo_score >= 40:
        plans.append({
            "trigger": "Trade policy change, tariffs imposed, or port shutdown",
            "probability": "moderate" if geo_score >= 60 else "low",
            "impact": "severe",
            "actions": [
                "Activate alternative-country supplier immediately",
                "Evaluate tariff impact on landed cost and adjust pricing",
                "Consider air freight for critical stock to bridge the gap",
                "Review contracts for force majeure clauses",
            ],
            "preparation": [
                "Identify at least one supplier in a different country or region",
                "Monitor trade news for your supplier's country weekly",
                "Maintain 90 days of safety stock for geopolitically risky sources",
            ],
        })

    # Default minimal plan if no major risks
    if not plans:
        plans.append({
            "trigger": "General supply chain disruption",
            "probability": "low",
            "impact": "moderate",
            "actions": [
                "Maintain standard safety stock levels",
                "Review supplier performance quarterly",
            ],
            "preparation": [
                "Keep a list of potential backup suppliers updated",
                "Review contingency plan annually",
            ],
        })

    return {
        "overall_risk_level": risks.get("classification", "moderate"),
        "composite_score": composite,
        "plan_count": len(plans),
        "plans": plans,
        "review_frequency": "monthly" if composite >= 60 else "quarterly",
    }
