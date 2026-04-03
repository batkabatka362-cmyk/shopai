"""InfiniteScaling Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the infinite scaling engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class InfiniteScalingInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    metrics: dict
    resources: dict
    growth_targets: dict


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class InfiniteScalingData(TypedDict):
    """The 'data' block of engine output."""
    growth_trajectory: dict
    bottlenecks: list
    capacity_plan: dict
    scaling_recommendations: list


class InfiniteScalingMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class InfiniteScalingOutput(TypedDict):
    """Final output of the infinite scaling engine."""
    status: str
    data: InfiniteScalingData | None
    meta: InfiniteScalingMeta
    error: str | None
