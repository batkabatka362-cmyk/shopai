"""CompetitionAnalyzer Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the competition analyzer engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CompetitionAnalyzerInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    competitors: list
    products: list
    market_data: dict


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class CompetitionAnalyzerData(TypedDict):
    """The 'data' block of engine output."""
    analysis: list
    threats: list
    opportunities: list


class CompetitionAnalyzerMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class CompetitionAnalyzerOutput(TypedDict):
    """Final output of the competition analyzer engine."""
    status: str
    data: CompetitionAnalyzerData | None
    meta: CompetitionAnalyzerMeta
    error: str | None
