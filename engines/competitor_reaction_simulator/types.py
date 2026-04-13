"""Competitor Reaction Simulator Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the competitor reaction simulator engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class Competitor(TypedDict, total=False):
    name: str
    market_share: float
    pricing_strategy: str
    aggressiveness: float
    history: list[dict[str, Any]]


class CompetitorReactionInputData(TypedDict, total=False):
    our_action: dict[str, Any]
    competitors: list[Competitor]
    market_data: dict[str, Any]
    history: list[dict[str, Any]]


class BehaviorModel(TypedDict):
    competitor: str
    strategy_type: str
    aggressiveness: float
    response_speed_days: float
    price_follow_rate: float
    confidence: float


class ReactionPrediction(TypedDict):
    competitor: str
    likely_reaction: str
    probability: float
    timeline: str
    impact_on_us: str


class NashEquilibrium(TypedDict):
    description: str
    our_optimal_price: float
    competitor_optimal_prices: dict[str, float]
    stable: bool


class CounterStrategy(TypedDict):
    strategy: str
    description: str
    trigger_condition: str
    expected_outcome: str


class CompetitorReactionData(TypedDict):
    predictions: list[ReactionPrediction]
    nash_equilibrium: NashEquilibrium
    recommended_counterstrategy: CounterStrategy


class CompetitorReactionMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class CompetitorReactionOutput(TypedDict):
    status: str
    data: CompetitorReactionData | None
    meta: CompetitorReactionMeta
    error: str | None
