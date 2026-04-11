"""TrendDiscovery Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the trend discovery engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class TrendDiscoveryInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    category: str
    search_data: dict
    social_data: dict
    marketplace_data: dict


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class TrendDiscoveryData(TypedDict):
    """The 'data' block of engine output."""
    trends: list
    emerging_niches: list
    hot_products: list


class TrendDiscoveryMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class TrendDiscoveryOutput(TypedDict):
    """Final output of the trend discovery engine."""
    status: str
    data: TrendDiscoveryData | None
    meta: TrendDiscoveryMeta
    error: str | None
