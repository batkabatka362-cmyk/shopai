"""Supplier risk assessment — dependency, quality, geopolitical, and financial risks.

Evaluates supply chain risks that threaten product availability and quality:
  - Single-source dependency: all eggs in one basket?
  - Quality consistency: defect rate and variance
  - Lead time reliability: on-time delivery track record
  - Geopolitical stability: country and trade policy risk
  - Communication quality: responsiveness and clarity
  - Financial stability of supplier: can they survive a downturn?

Each dimension scored 0-100 (higher = more risk).
Also calculates supplier concentration risk and alternative availability.
"""
from __future__ import annotations

from typing import Any

from .data import get_country_risk, get_lead_time_variance


# Weights for composite supplier risk score
DIMENSION_WEIGHTS = {
    "single_source_dependency": 0.25,
    "quality_consistency": 0.20,
    "lead_time_reliability": 0.15,
    "geopolitical_stability": 0.15,
    "communication_quality": 0.10,
    "financial_stability": 0.15,
}

RISK_BANDS = {
    "low": (0, 25),
    "moderate": (25, 50),
    "high": (50, 75),
    "critical": (75, 100),
}


def assess_supplier_risk(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Assess supply chain risks for a product's supplier setup.

    Args:
        input_payload: {
            "supplier_count": int,           # number of active suppliers
            "primary_supplier_pct": float,    # % of volume from primary supplier (0-100)
            "defect_rate_pct": float,         # average defect rate (0-100)
            "on_time_delivery_pct": float,    # % of orders delivered on time (0-100)
            "supplier_country": str,          # primary supplier country
            "response_time_hours": float,     # avg communication response time
            "supplier_years_in_business": int,
            "alternative_suppliers_known": int,
        }

    Returns:
        Engine contract: {status, data, meta, error}
    """
    try:
        dimensions = _score_all_dimensions(input_payload)
        composite = _calculate_composite_score(dimensions)
        classification = _classify_risk(composite)
        concentration = _assess_concentration_risk(input_payload)
        alternatives = _assess_alternative_availability(input_payload)

        return {
            "status": "success",
            "data": {
                "dimensions": dimensions,
                "composite_score": round(composite, 1),
                "classification": classification,
                "concentration_risk": concentration,
                "alternative_availability": alternatives,
                "summary": _build_summary(composite, classification, concentration),
            },
            "meta": {
                "module": "supplier_risk",
                "version": "1.0",
                "weights": DIMENSION_WEIGHTS,
                "bands": RISK_BANDS,
            },
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "error",
            "data": None,
            "meta": {"module": "supplier_risk", "version": "1.0"},
            "error": str(exc),
        }


def _score_all_dimensions(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Score each supplier risk dimension 0-100."""
    supplier_count = payload.get("supplier_count", 1)
    primary_pct = payload.get("primary_supplier_pct", 100)
    defect_rate = payload.get("defect_rate_pct", 5)
    on_time_pct = payload.get("on_time_delivery_pct", 80)
    country = payload.get("supplier_country", "china")
    response_hrs = payload.get("response_time_hours", 48)
    years_biz = payload.get("supplier_years_in_business", 3)

    # Single-source dependency: 1 supplier = max risk
    if supplier_count <= 1:
        dep_score = 95
    elif supplier_count == 2:
        dep_score = 65
    elif supplier_count == 3:
        dep_score = 40
    else:
        dep_score = max(10, 30 - (supplier_count - 3) * 5)
    # Adjust by concentration in primary supplier
    dep_score = min(100, dep_score * (primary_pct / 100) * 1.2)

    # Quality consistency: higher defect rate = higher risk
    if defect_rate <= 1:
        quality_score = 10
    elif defect_rate <= 3:
        quality_score = 30
    elif defect_rate <= 5:
        quality_score = 50
    elif defect_rate <= 10:
        quality_score = 75
    else:
        quality_score = 95

    # Lead time reliability: lower on-time % = higher risk
    lead_score = max(0, min(100, (100 - on_time_pct) * 2.5))

    # Geopolitical stability: country-based risk
    country_risk = get_country_risk(country.lower())
    geo_score = country_risk.get("risk_score", 50)

    # Communication quality: slower response = higher risk
    if response_hrs <= 12:
        comm_score = 10
    elif response_hrs <= 24:
        comm_score = 25
    elif response_hrs <= 48:
        comm_score = 45
    elif response_hrs <= 72:
        comm_score = 65
    else:
        comm_score = 85

    # Financial stability: younger companies = higher risk
    if years_biz >= 10:
        fin_score = 15
    elif years_biz >= 5:
        fin_score = 30
    elif years_biz >= 3:
        fin_score = 50
    elif years_biz >= 1:
        fin_score = 70
    else:
        fin_score = 90

    return {
        "single_source_dependency": {
            "score": round(dep_score, 1),
            "detail": f"{supplier_count} supplier(s), primary handles {primary_pct}%",
        },
        "quality_consistency": {
            "score": round(quality_score, 1),
            "detail": f"{defect_rate}% defect rate",
        },
        "lead_time_reliability": {
            "score": round(lead_score, 1),
            "detail": f"{on_time_pct}% on-time delivery",
        },
        "geopolitical_stability": {
            "score": round(geo_score, 1),
            "detail": f"Country: {country} — {country_risk.get('level', 'unknown')} risk",
        },
        "communication_quality": {
            "score": round(comm_score, 1),
            "detail": f"Avg response: {response_hrs}h",
        },
        "financial_stability": {
            "score": round(fin_score, 1),
            "detail": f"Supplier in business {years_biz} year(s)",
        },
    }


def _calculate_composite_score(dimensions: dict[str, dict[str, Any]]) -> float:
    """Weighted aggregation of all dimension scores."""
    total = 0.0
    for dim_key, weight in DIMENSION_WEIGHTS.items():
        score = dimensions.get(dim_key, {}).get("score", 50)
        total += score * weight
    return total


def _classify_risk(composite: float) -> str:
    """Classify composite risk score into a band."""
    for label, (low, high) in RISK_BANDS.items():
        if low <= composite < high:
            return label
    return "critical"


def _assess_concentration_risk(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate how concentrated the supply chain is."""
    supplier_count = payload.get("supplier_count", 1)
    primary_pct = payload.get("primary_supplier_pct", 100)

    if supplier_count <= 1:
        level = "critical"
        message = "Complete dependency on a single supplier — any disruption halts operations"
    elif primary_pct >= 80:
        level = "high"
        message = "Primary supplier handles 80%+ — backup exists but is insufficient"
    elif primary_pct >= 60:
        level = "moderate"
        message = "Moderately concentrated — backup supplier could partially cover a disruption"
    else:
        level = "low"
        message = "Well diversified — no single supplier dominates"

    return {"level": level, "message": message, "supplier_count": supplier_count}


def _assess_alternative_availability(payload: dict[str, Any]) -> dict[str, Any]:
    """Assess how available alternative suppliers are."""
    alternatives = payload.get("alternative_suppliers_known", 0)

    if alternatives >= 5:
        status = "strong"
        message = "Multiple alternatives identified — easy to switch if needed"
    elif alternatives >= 2:
        status = "adequate"
        message = "Some alternatives known — transition possible but not instant"
    elif alternatives >= 1:
        status = "weak"
        message = "Only one alternative known — vulnerability if both fail"
    else:
        status = "none"
        message = "No alternatives identified — must find backups immediately"

    return {"status": status, "message": message, "alternatives_known": alternatives}


def _build_summary(composite: float, classification: str, concentration: dict) -> str:
    """Human-readable supplier risk summary."""
    return (
        f"Overall supplier risk: {classification.upper()} ({composite:.0f}/100). "
        f"Concentration risk: {concentration['level']}. "
        f"{concentration['message']}."
    )
