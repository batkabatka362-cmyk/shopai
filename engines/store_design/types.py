"""Store Design Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the store design engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class BrandInfo(TypedDict, total=False):
    """Brand identity information."""
    colors: list[str]
    fonts: list[str]
    voice: str


class AnalyticsInput(TypedDict, total=False):
    """Analytics data for design decisions."""
    bounce_rate: float
    device_split: dict[str, float]


class StoreDesignInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    brand: BrandInfo
    products: list[dict[str, Any]]
    analytics: AnalyticsInput


# ---------------------------------------------------------------------------
# Intermediate types — layout optimization
# ---------------------------------------------------------------------------

class LayoutRecommendation(TypedDict):
    """Single layout recommendation from layout_optimizer."""
    page: str
    current_issue: str
    recommendation: str
    priority: str
    expected_impact: str


# ---------------------------------------------------------------------------
# Intermediate types — color recommendation
# ---------------------------------------------------------------------------

class ColorPalette(TypedDict):
    """Color palette from color_recommender."""
    primary: str
    secondary: str
    accent: str
    background: str
    text: str
    cta: str
    rationale: str


# ---------------------------------------------------------------------------
# Intermediate types — navigation
# ---------------------------------------------------------------------------

class MenuItem(TypedDict):
    """Single navigation menu item."""
    label: str
    url: str
    children: list[dict[str, Any]]
    priority: int


class NavigationStructure(TypedDict):
    """Navigation structure from navigation_builder."""
    menu_items: list[MenuItem]
    hierarchy: dict[str, list[str]]
    max_depth: int
    total_items: int


# ---------------------------------------------------------------------------
# Intermediate types — mobile optimization
# ---------------------------------------------------------------------------

class MobileOptimization(TypedDict):
    """Single mobile optimization from mobile_optimizer."""
    area: str
    issue: str
    recommendation: str
    impact: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class StoreDesignData(TypedDict):
    """The 'data' block of the engine output."""
    layout_recommendations: list[LayoutRecommendation]
    color_palette: ColorPalette
    navigation: NavigationStructure
    mobile_optimizations: list[MobileOptimization]
    estimated_conversion_lift: float


class StoreDesignMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class StoreDesignOutput(TypedDict):
    """Final output of the store design engine."""
    status: str
    data: StoreDesignData | None
    meta: StoreDesignMeta
    error: str | None
