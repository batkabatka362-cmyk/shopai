"""Brand Visual Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the brand visual engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class BrandVisualInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    brand_identity: dict[str, Any]
    industry: str
    competitors: list[dict[str, Any]]
    preferences: dict[str, Any]


# ---------------------------------------------------------------------------
# Intermediate types — colors
# ---------------------------------------------------------------------------

class ColorPalette(TypedDict):
    """Color palette from color_palette_builder."""
    primary: str
    secondary: str
    accent: str
    background: str
    text: str
    palette_name: str


# ---------------------------------------------------------------------------
# Intermediate types — typography
# ---------------------------------------------------------------------------

class Typography(TypedDict):
    """Typography recommendations from typography_selector."""
    heading_font: str
    body_font: str
    sizes: dict[str, str]
    weight_guidelines: dict[str, str]


# ---------------------------------------------------------------------------
# Intermediate types — imagery
# ---------------------------------------------------------------------------

class ImageryStyle(TypedDict):
    """Imagery style from imagery_stylist."""
    style: str
    mood: str
    composition_rules: list[str]
    color_treatment: str


# ---------------------------------------------------------------------------
# Intermediate types — style guide
# ---------------------------------------------------------------------------

class StyleGuide(TypedDict):
    """Compiled style guide from style_guide_compiler."""
    summary: str
    usage_rules: list[str]
    brand_applications: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class BrandVisualData(TypedDict):
    """The 'data' block of the engine output."""
    colors: ColorPalette
    typography: Typography
    imagery: ImageryStyle
    style_guide: StyleGuide


class BrandVisualMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class BrandVisualOutput(TypedDict):
    """Final output of the brand visual engine."""
    status: str
    data: BrandVisualData | None
    meta: BrandVisualMeta
    error: str | None
