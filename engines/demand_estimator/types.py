"""DemandEstimator Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the demand estimator engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class DemandEstimatorInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    product: dict
    market_size: float
    competition: dict
    seasonality: dict


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class DemandEstimatorData(TypedDict):
    """The 'data' block of engine output."""
    estimate: dict
    confidence: float
    scenarios: dict


class DemandEstimatorMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class DemandEstimatorOutput(TypedDict):
    """Final output of the demand estimator engine."""
    status: str
    data: DemandEstimatorData | None
    meta: DemandEstimatorMeta
    error: str | None
