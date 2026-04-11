"""Gap finder data — gap type definitions, benchmarks, and history tracking.

Stores discovered gaps for tracking and learning over time.
"""
from __future__ import annotations

import time
from typing import Any


# Gap type definitions with expected profitability
GAP_TYPE_PROFILES = {
    "demand_supply_gap": {
        "description": "High demand, low supply",
        "avg_success_rate": 0.65,
        "avg_margin_premium": 0.0,
        "time_to_validate": "2-4 weeks",
        "investment_level": "medium",
        "risk": "medium",
        "best_for": "Fast movers who can source quickly",
    },
    "quality_gap": {
        "description": "Existing products are low quality",
        "avg_success_rate": 0.55,
        "avg_margin_premium": 0.25,
        "time_to_validate": "4-8 weeks",
        "investment_level": "high",
        "risk": "medium",
        "best_for": "Brand builders who invest in quality",
    },
    "complaint_gap": {
        "description": "Customers complaining about specific issue",
        "avg_success_rate": 0.70,
        "avg_margin_premium": 0.15,
        "time_to_validate": "2-4 weeks",
        "investment_level": "medium",
        "risk": "low",
        "best_for": "Problem solvers who listen to customers",
    },
    "price_gap": {
        "description": "No product in a price tier",
        "avg_success_rate": 0.45,
        "avg_margin_premium": 0.0,
        "time_to_validate": "4-6 weeks",
        "investment_level": "medium",
        "risk": "medium",
        "best_for": "Stores that can source at the right cost point",
    },
    "competitor_weakness": {
        "description": "Competitors performing poorly",
        "avg_success_rate": 0.60,
        "avg_margin_premium": 0.10,
        "time_to_validate": "2-4 weeks",
        "investment_level": "low",
        "risk": "low",
        "best_for": "Execution-focused operators",
    },
    "new_market_gap": {
        "description": "Emerging market with few players",
        "avg_success_rate": 0.35,
        "avg_margin_premium": 0.30,
        "time_to_validate": "6-12 weeks",
        "investment_level": "low",
        "risk": "high",
        "best_for": "Risk-tolerant early adopters",
    },
}

# Industry benchmarks for gap detection
BENCHMARKS = {
    "healthy_review_avg": 4.2,           # Below this = quality gap exists
    "min_products_for_competition": 20,   # Below this = potential supply gap
    "high_search_threshold": 5000,        # Monthly searches above this = real demand
    "complaint_threshold_pct": 15,        # >15% negative reviews = complaint gap
}


class GapRecord:
    """A single detected gap record for tracking."""

    def __init__(
        self,
        gap_type: str,
        category: str,
        description: str,
        opportunity_score: int,
        timestamp: float | None = None,
    ) -> None:
        self.gap_type = gap_type
        self.category = category
        self.description = description
        self.opportunity_score = opportunity_score
        self.timestamp = timestamp or time.time()
        self.status = "detected"  # detected → pursuing → filled → abandoned
        self.outcome: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_type": self.gap_type,
            "category": self.category,
            "description": self.description,
            "opportunity_score": self.opportunity_score,
            "timestamp": self.timestamp,
            "status": self.status,
            "outcome": self.outcome,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GapRecord:
        record = cls(
            gap_type=data["gap_type"],
            category=data["category"],
            description=data["description"],
            opportunity_score=data["opportunity_score"],
            timestamp=data.get("timestamp"),
        )
        record.status = data.get("status", "detected")
        record.outcome = data.get("outcome")
        return record


def get_gap_profile(gap_type: str) -> dict[str, Any]:
    """Get benchmark profile for a gap type."""
    return GAP_TYPE_PROFILES.get(gap_type, {
        "description": "Unknown gap type",
        "avg_success_rate": 0.40,
        "avg_margin_premium": 0.0,
        "time_to_validate": "unknown",
        "investment_level": "unknown",
        "risk": "unknown",
        "best_for": "Requires further analysis",
    })


def get_benchmarks() -> dict[str, Any]:
    """Get industry benchmarks for gap detection."""
    return BENCHMARKS
