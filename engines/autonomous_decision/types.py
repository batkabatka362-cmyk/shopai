"""AutonomousDecision Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the autonomous decision engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class AutonomousDecisionInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    context: dict
    options: list
    constraints: dict
    goal: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class AutonomousDecisionData(TypedDict):
    """The 'data' block of engine output."""
    decision: dict
    alternatives: list
    predicted_outcome: dict
    confidence: float
    reasoning: str


class AutonomousDecisionMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class AutonomousDecisionOutput(TypedDict):
    """Final output of the autonomous decision engine."""
    status: str
    data: AutonomousDecisionData | None
    meta: AutonomousDecisionMeta
    error: str | None
