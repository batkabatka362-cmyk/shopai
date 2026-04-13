"""Opportunity Scoring Engine — all TypedDicts and type aliases."""
from __future__ import annotations
from typing import Any, TypedDict

class OpportunityScoringInputData(TypedDict, total=False):
    opportunities: list[dict[str, Any]]
    criteria: dict[str, Any]
    risk_tolerance: str

class ScoredOpportunity(TypedDict):
    opportunity: dict[str, Any]
    score: float
    risk: str
    roi: float

class OpportunityScoringData(TypedDict):
    scored: list[ScoredOpportunity]
    ranked_list: list[str]
    recommended: dict[str, Any]

class OpportunityScoringMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float

class OpportunityScoringOutput(TypedDict):
    status: str
    data: OpportunityScoringData | None
    meta: OpportunityScoringMeta
    error: str | None
