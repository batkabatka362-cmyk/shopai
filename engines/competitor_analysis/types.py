"""CompetitorAnalysis Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the competitor analysis engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CompetitorAnalysisInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    competitors: list
    tracked_products: list


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class CompetitorAnalysisData(TypedDict):
    """The 'data' block of engine output."""
    strategies: list
    price_changes: list
    new_products: list
    alerts: list


class CompetitorAnalysisMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class CompetitorAnalysisOutput(TypedDict):
    """Final output of the competitor analysis engine."""
    status: str
    data: CompetitorAnalysisData | None
    meta: CompetitorAnalysisMeta
    error: str | None
