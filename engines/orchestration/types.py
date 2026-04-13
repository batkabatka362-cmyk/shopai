"""Orchestration Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the orchestration engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class OrchestrationInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    workflow: list
    context: dict


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class OrchestrationData(TypedDict):
    """The 'data' block of engine output."""
    execution_plan: list
    results: dict
    timing: dict
    success_rate: float


class OrchestrationMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class OrchestrationOutput(TypedDict):
    """Final output of the orchestration engine."""
    status: str
    data: OrchestrationData | None
    meta: OrchestrationMeta
    error: str | None
