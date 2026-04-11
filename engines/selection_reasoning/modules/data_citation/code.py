"""Data Citation — extracts and formats data citations from engine results.

Pulls key numbers from all upstream engine outputs and formats them as
properly sourced citations. Each citation includes the data point, its
source engine, and its relevance to the selection decision.

Returns the engine contract: {status, data, meta, error}.
"""

from __future__ import annotations

from typing import Any

from .data import CITATION_TEMPLATES, DATA_SOURCE_LABELS
from .logic import rank_citations_by_impact, filter_relevant_citations
from .rules import validate_citations


def cite_data(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Extract and format data citations from all engine results.

    Args:
        input_payload: dict with keys:
            - selected_product (dict): chosen product with all engine data
            - engine_results (dict): raw outputs from upstream engines
            - decision_rationale (dict): why the product was chosen
            - goal (str): profit|growth|balanced

    Returns:
        Engine contract dict {status, data, meta, error}.
    """
    try:
        selected = input_payload.get("selected_product")
        if not selected or not isinstance(selected, dict):
            return _error("selected_product is required")

        engine_results = input_payload.get("engine_results", {})
        rationale = input_payload.get("decision_rationale", {})
        goal = input_payload.get("goal", "balanced")

        # --- Extract citations from each engine ---
        raw_citations: list[dict[str, Any]] = []

        # Profitability citations
        profit = selected.get("profitability", {}) or {}
        if profit:
            raw_citations.extend(_extract_profitability_citations(profit))

        # Demand citations
        demand = selected.get("demand", {}) or {}
        if demand:
            raw_citations.extend(_extract_demand_citations(demand))

        # Competition citations
        competition = selected.get("competition", {}) or {}
        if competition:
            raw_citations.extend(_extract_competition_citations(competition))

        # Risk citations
        risk = selected.get("risk", {}) or {}
        if risk:
            raw_citations.extend(_extract_risk_citations(risk))

        # Trend citations
        trend = selected.get("trend_discovery", {}) or {}
        if trend:
            raw_citations.extend(_extract_trend_citations(trend))

        # Market research citations
        market = selected.get("market_research", {}) or {}
        if market:
            raw_citations.extend(_extract_market_citations(market))

        # Unified score citation
        unified_score = selected.get("unified_score")
        if unified_score is not None:
            raw_citations.append({
                "data_point": f"Unified Score: {unified_score:.1f}/100",
                "value": unified_score,
                "source": "Score Aggregation Engine",
                "category": "overall",
                "impact": _score_impact(unified_score),
            })

        # --- Rank and filter citations ---
        ranked = rank_citations_by_impact(raw_citations)
        filtered = filter_relevant_citations(ranked, rationale)

        # --- Format citations ---
        formatted = [_format_citation(c) for c in filtered]

        # --- Validate ---
        validation = validate_citations(filtered)

        return {
            "status": "success",
            "data": {
                "citations": formatted,
                "citation_details": filtered,
                "total_citations": len(filtered),
                "sources_represented": list({c["source"] for c in filtered}),
                "categories_covered": list({c["category"] for c in filtered}),
                "validation": validation,
            },
            "meta": {
                "module": "data_citation",
                "raw_citations_extracted": len(raw_citations),
                "citations_after_filter": len(filtered),
                "goal": goal,
            },
            "error": None,
        }

    except Exception as exc:
        return _error(f"Citation extraction failed: {exc}")


def _extract_profitability_citations(
    profit: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract citations from profitability engine data."""
    citations: list[dict[str, Any]] = []
    source = DATA_SOURCE_LABELS["profitability"]

    margin = profit.get("margin")
    if margin is not None:
        citations.append({
            "data_point": f"Profit Margin: {margin:.1f}%",
            "value": margin,
            "source": source,
            "category": "profitability",
            "impact": "high" if margin >= 30 else "medium",
        })

    roi = profit.get("roi")
    if roi is not None:
        citations.append({
            "data_point": f"ROI: {roi:.1f}%",
            "value": roi,
            "source": source,
            "category": "profitability",
            "impact": "high" if roi >= 100 else "medium",
        })

    cost = profit.get("unit_cost")
    if cost is not None:
        citations.append({
            "data_point": f"Unit Cost: ${cost:.2f}",
            "value": cost,
            "source": source,
            "category": "profitability",
            "impact": "medium",
        })

    return citations


def _extract_demand_citations(
    demand: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract citations from demand engine data."""
    citations: list[dict[str, Any]] = []
    source = DATA_SOURCE_LABELS["demand"]

    score = demand.get("demand_score")
    if score is not None:
        citations.append({
            "data_point": f"Demand Score: {score:.0f}/100",
            "value": score,
            "source": source,
            "category": "demand",
            "impact": "high" if score >= 60 else "medium",
        })

    volume = demand.get("volume_projection")
    if volume is not None:
        citations.append({
            "data_point": f"Volume Projection: {volume:,.0f} units/month",
            "value": volume,
            "source": source,
            "category": "demand",
            "impact": "high",
        })

    return citations


def _extract_competition_citations(
    competition: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract citations from competition engine data."""
    citations: list[dict[str, Any]] = []
    source = DATA_SOURCE_LABELS["competition"]

    score = competition.get("competition_score")
    if score is not None:
        citations.append({
            "data_point": f"Competition Score: {score:.0f}/100",
            "value": score,
            "source": source,
            "category": "competition",
            "impact": "high" if score >= 70 else "medium",
        })

    landscape = competition.get("competitive_landscape")
    if landscape:
        citations.append({
            "data_point": f"Competitive Landscape: {landscape}",
            "value": landscape,
            "source": source,
            "category": "competition",
            "impact": "medium",
        })

    return citations


def _extract_risk_citations(
    risk: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract citations from risk engine data."""
    citations: list[dict[str, Any]] = []
    source = DATA_SOURCE_LABELS["risk"]

    composite = risk.get("composite_risk")
    if composite is not None:
        citations.append({
            "data_point": f"Composite Risk: {composite:.0f}/100",
            "value": composite,
            "source": source,
            "category": "risk",
            "impact": "high" if composite >= 50 else "medium",
        })

    level = risk.get("risk_level")
    if level:
        citations.append({
            "data_point": f"Risk Level: {level}",
            "value": level,
            "source": source,
            "category": "risk",
            "impact": "high" if level in ("high", "critical") else "medium",
        })

    return citations


def _extract_trend_citations(
    trend: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract citations from trend discovery engine data."""
    citations: list[dict[str, Any]] = []
    source = DATA_SOURCE_LABELS["trend"]

    score = trend.get("trend_score")
    if score is not None:
        citations.append({
            "data_point": f"Trend Score: {score:.0f}/100",
            "value": score,
            "source": source,
            "category": "trend",
            "impact": "medium",
        })

    return citations


def _extract_market_citations(
    market: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract citations from market research engine data."""
    citations: list[dict[str, Any]] = []
    source = DATA_SOURCE_LABELS["market_research"]

    verdict = market.get("market_verdict")
    if verdict:
        citations.append({
            "data_point": f"Market Verdict: {verdict}",
            "value": verdict,
            "source": source,
            "category": "market",
            "impact": "medium",
        })

    size_score = market.get("market_size_score")
    if size_score is not None:
        citations.append({
            "data_point": f"Market Size Score: {size_score:.0f}/100",
            "value": size_score,
            "source": source,
            "category": "market",
            "impact": "medium",
        })

    return citations


def _format_citation(citation: dict[str, Any]) -> str:
    """Format a citation dict into a human-readable string."""
    template = CITATION_TEMPLATES.get(
        citation.get("category", "general"),
        CITATION_TEMPLATES["general"],
    )
    return template.format(
        data_point=citation["data_point"],
        source=citation["source"],
    )


def _score_impact(score: float) -> str:
    """Classify the impact level of a score value."""
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {"module": "data_citation"},
        "error": message,
    }
