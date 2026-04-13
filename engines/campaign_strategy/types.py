"""Campaign Strategy Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the campaign strategy engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class CampaignInputData(TypedDict, total=False):
    goal: str
    budget: float
    audience: dict[str, Any]
    products: list[dict[str, Any]]
    channels: list[str]
    duration_days: int


class ChannelPlan(TypedDict):
    channel: str
    role: str
    budget_pct: float
    expected_reach: int
    expected_conversions: int


class CampaignPhase(TypedDict):
    name: str
    duration_days: int
    channels: list[str]
    budget_pct: float
    goal: str
    kpis: list[str]


class BudgetAllocation(TypedDict):
    channel: str
    phase: str
    amount: float
    pct_of_total: float


class Milestone(TypedDict):
    day: int
    description: str
    phase: str
    deliverable: str


class ExpectedResults(TypedDict):
    total_reach: int
    total_conversions: int
    expected_roas: float
    cost_per_acquisition: float


class CampaignStrategyData(TypedDict):
    strategy: dict[str, Any]
    budget_allocation: list[BudgetAllocation]
    expected_results: ExpectedResults
    milestones: list[Milestone]


class CampaignStrategyMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class CampaignStrategyOutput(TypedDict):
    status: str
    data: CampaignStrategyData | None
    meta: CampaignStrategyMeta
    error: str | None
