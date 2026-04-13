"""MarketResearch Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the market research engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class MarketResearchInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    category: str
    competitors: list
    trends: list
    search_data: dict


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class MarketResearchData(TypedDict):
    """The 'data' block of engine output."""
    market_size: dict
    gaps: list
    trends: list
    verdict: dict


class MarketResearchMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class MarketResearchOutput(TypedDict):
    """Final output of the market research engine."""
    status: str
    data: MarketResearchData | None
    meta: MarketResearchMeta
    error: str | None
