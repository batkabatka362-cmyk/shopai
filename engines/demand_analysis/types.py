"""DemandAnalysis Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the demand analysis engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class DemandAnalysisInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    market_data: dict
    products: list
    segments: list


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class DemandAnalysisData(TypedDict):
    """The 'data' block of engine output."""
    demand: dict
    segments: list
    saturation_level: float


class DemandAnalysisMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class DemandAnalysisOutput(TypedDict):
    """Final output of the demand analysis engine."""
    status: str
    data: DemandAnalysisData | None
    meta: DemandAnalysisMeta
    error: str | None
