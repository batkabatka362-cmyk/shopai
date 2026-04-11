"""Selection Decision Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the selection decision engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class RankedProduct(TypedDict, total=False):
    """Single ranked product for selection."""
    id: str
    title: str
    category: str
    score: float
    risk_score: float
    profitability_score: float


class SelectionConstraint(TypedDict, total=False):
    """Selection constraint."""
    type: str
    field: str
    operator: str
    value: Any
    description: str


class SelectionInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    ranked_products: list[RankedProduct]
    constraints: list[SelectionConstraint]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class DecisionMatrixItem(TypedDict):
    """Per-product decision matrix from decision_matrix."""
    product_id: str
    weighted_score: float
    criteria_scores: dict[str, float]
    rank: int


class ConstraintCheckResult(TypedDict):
    """Per-product constraint check from constraint_checker."""
    product_id: str
    passes_all: bool
    violations: list[str]
    violation_count: int


class PortfolioBalance(TypedDict):
    """Portfolio balance result from portfolio_balancer."""
    category_distribution: dict[str, int]
    risk_distribution: dict[str, int]
    balance_score: float
    recommendations: list[str]


class VerdictItem(TypedDict):
    """Per-product verdict from verdict_builder."""
    product_id: str
    verdict: str
    confidence: float
    reasons: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SelectionData(TypedDict):
    """The 'data' block of the engine output."""
    selected: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    portfolio_balance: dict[str, Any]


class SelectionMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class SelectionOutput(TypedDict):
    """Final output of the selection decision engine."""
    status: str
    data: SelectionData | None
    meta: SelectionMeta
    error: str | None
