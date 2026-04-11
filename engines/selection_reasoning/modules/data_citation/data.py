"""Data Citation — reference data: citation templates and source labels.

Templates format data points into human-readable citation strings.
Source labels map engine names to their display names for attribution.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Citation formatting templates by category
# ---------------------------------------------------------------------------
CITATION_TEMPLATES: dict[str, str] = {
    "profitability": "{data_point} (Source: {source})",
    "demand": "{data_point} (Source: {source})",
    "competition": "{data_point} (Source: {source})",
    "risk": "{data_point} (Source: {source})",
    "trend": "{data_point} (Source: {source})",
    "market": "{data_point} (Source: {source})",
    "overall": "{data_point} (Source: {source})",
    "general": "{data_point} (Source: {source})",
}

# ---------------------------------------------------------------------------
# Data source display labels
# ---------------------------------------------------------------------------
DATA_SOURCE_LABELS: dict[str, str] = {
    "profitability": "Profitability Calculator Engine",
    "demand": "Demand Estimator Engine",
    "competition": "Competition Analyzer Engine",
    "risk": "Product Risk Engine",
    "trend": "Trend Discovery Engine",
    "market_research": "Market Research Engine",
    "filter": "Product Filter Engine",
    "score_aggregation": "Score Aggregation Engine",
    "selection_decision": "Selection Decision Engine",
}

# ---------------------------------------------------------------------------
# Citation category descriptions
# ---------------------------------------------------------------------------
CITATION_CATEGORY_INFO: dict[str, dict[str, Any]] = {
    "profitability": {
        "label": "Profitability",
        "description": "Revenue, cost, margin, and ROI data",
        "required": True,
        "priority": 1,
    },
    "demand": {
        "label": "Demand",
        "description": "Search volume, sales velocity, and market demand signals",
        "required": True,
        "priority": 2,
    },
    "risk": {
        "label": "Risk",
        "description": "Composite risk score, risk level, and specific risk factors",
        "required": True,
        "priority": 3,
    },
    "competition": {
        "label": "Competition",
        "description": "Competitor count, market saturation, and competitive landscape",
        "required": False,
        "priority": 4,
    },
    "trend": {
        "label": "Trend",
        "description": "Trend direction, momentum, and seasonal patterns",
        "required": False,
        "priority": 5,
    },
    "market": {
        "label": "Market",
        "description": "Market size, growth rate, and overall market assessment",
        "required": False,
        "priority": 6,
    },
    "overall": {
        "label": "Overall",
        "description": "Unified score and aggregate metrics",
        "required": False,
        "priority": 7,
    },
}

# ---------------------------------------------------------------------------
# Impact classification thresholds
# ---------------------------------------------------------------------------
IMPACT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "margin": {"high": 30.0, "medium": 15.0, "unit": "%"},
    "roi": {"high": 100.0, "medium": 50.0, "unit": "%"},
    "demand_score": {"high": 70.0, "medium": 40.0, "unit": "/100"},
    "competition_score": {"high": 70.0, "medium": 40.0, "unit": "/100"},
    "composite_risk": {"high": 50.0, "medium": 30.0, "unit": "/100"},
    "trend_score": {"high": 70.0, "medium": 40.0, "unit": "/100"},
    "unified_score": {"high": 75.0, "medium": 55.0, "unit": "/100"},
}

# ---------------------------------------------------------------------------
# Maximum citations per category to avoid overrepresentation
# ---------------------------------------------------------------------------
MAX_CITATIONS_PER_CATEGORY: dict[str, int] = {
    "profitability": 3,
    "demand": 2,
    "risk": 2,
    "competition": 2,
    "trend": 1,
    "market": 2,
    "overall": 1,
}
