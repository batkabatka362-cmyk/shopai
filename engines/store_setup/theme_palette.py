"""Niche-aware theme palette recommender.

Every Shopify store ships with the theme's default palette
(usually black on white plus one accent). For an autonomous
merchant building dozens of niche-specific stores, that's the
visual equivalent of every store using the same template --
the opposite of brand-aware.

This module produces a structured palette spec per niche:
six semantic color slots (primary, secondary, accent,
background, surface, text) plus WCAG-checked contrast pairs.
The palette is deterministic per niche so two stores in the
same niche get tuned-for-that-category palettes (warm tones
for beauty, bold for fashion, earthy for outdoor, soft for
baby, etc.).

Return shape from :func:`generate_palette`::

    {
        "niche": "beauty",
        "tokens": {
            "primary":   "#1F1B16",  # darkest, used for CTAs
            "secondary": "#A47148",  # accent for hover states
            "accent":    "#D9A47A",  # highlight
            "background":"#FFF8F2",  # page bg
            "surface":   "#FFFFFF",  # card / panel bg
            "text":      "#1F1B16",  # body copy
        },
        "contrast": {
            "primary_on_background": 12.3,   # AAA
            "text_on_background":    12.3,
            "primary_on_surface":    13.7,
            "text_on_surface":       13.7,
        },
        "wcag_compliant_aa": True,
        "wcag_compliant_aaa": True,
    }

The :func:`apply_palette` persists the palette as a Shopify
page (handle ``theme-palette``) carrying both human-readable
swatches AND the structured JSON in a ``<pre>`` block --
mirrors the homepage_hero pattern so a future
theme-settings-write adapter can pick the palette up
deterministically, and operators can copy hex values into
their theme settings today.

Records each push via Pattern Z.
"""
from __future__ import annotations

import html
import json
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Niche-specific palette spec. Six semantic slots per niche.
# Hex values picked to (a) match category aesthetic and
# (b) maintain >= 7:1 contrast for primary-on-background
# and text-on-background (AAA level) so every default
# palette is accessible out of the box.
_NICHE_PALETTES: dict[str, dict[str, str]] = {
    "beauty": {
        # Warm minimal -- creams + soft browns
        "primary":    "#1F1B16",
        "secondary":  "#A47148",
        "accent":     "#D9A47A",
        "background": "#FFF8F2",
        "surface":    "#FFFFFF",
        "text":       "#1F1B16",
    },
    "fashion": {
        # Bold high-contrast -- black/white plus single
        # statement red
        "primary":    "#0A0A0A",
        "secondary":  "#C8102E",
        "accent":     "#C8102E",
        "background": "#FFFFFF",
        "surface":    "#F7F7F7",
        "text":       "#0A0A0A",
    },
    "tech": {
        # Cool premium -- near-black + electric blue
        "primary":    "#0F172A",
        "secondary":  "#2563EB",
        "accent":     "#60A5FA",
        "background": "#FFFFFF",
        "surface":    "#F1F5F9",
        "text":       "#0F172A",
    },
    "home": {
        # Earthy neutrals -- warm grey, sage, terracotta
        "primary":    "#2D2A24",
        "secondary":  "#6B7C5A",
        "accent":     "#C97B5A",
        "background": "#F7F4EF",
        "surface":    "#FFFFFF",
        "text":       "#2D2A24",
    },
    "food": {
        # Pantry warm -- deep brown + green + cream
        "primary":    "#3B2D1F",
        "secondary":  "#4F7942",
        "accent":     "#D4A24C",
        "background": "#FBF6EE",
        "surface":    "#FFFFFF",
        "text":       "#3B2D1F",
    },
    "pets": {
        # Friendly playful -- warm yellow + chocolate
        "primary":    "#3E2723",
        "secondary":  "#E8A33D",
        "accent":     "#5BAA56",
        "background": "#FFFAEC",
        "surface":    "#FFFFFF",
        "text":       "#3E2723",
    },
    "fitness": {
        # High-energy -- charcoal + electric lime
        "primary":    "#111111",
        "secondary":  "#A0E84A",
        "accent":     "#FF5722",
        "background": "#FFFFFF",
        "surface":    "#F4F4F4",
        "text":       "#111111",
    },
    "jewelry": {
        # Luxe muted -- deep navy + soft gold
        "primary":    "#0E1A2B",
        "secondary":  "#B8A164",
        "accent":     "#B8A164",
        "background": "#FFFCF7",
        "surface":    "#FFFFFF",
        "text":       "#0E1A2B",
    },
    "outdoor": {
        # Trail-tested -- forest green + slate + warm tan
        "primary":    "#1B2E20",
        "secondary":  "#556B5A",
        "accent":     "#C18A4C",
        "background": "#F5F2EC",
        "surface":    "#FFFFFF",
        "text":       "#1B2E20",
    },
    "baby": {
        # Soft pastel -- dusty pink/blue + cream
        "primary":    "#3D2E2A",
        "secondary":  "#F2B7C0",
        "accent":     "#A3C9E2",
        "background": "#FFFAF5",
        "surface":    "#FFFFFF",
        "text":       "#3D2E2A",
    },
    "general": {
        # Safe neutral -- classic monochrome with one
        # accent. Conservative on purpose so it never
        # clashes with whatever niche the operator picks
        # later.
        "primary":    "#1A1A1A",
        "secondary":  "#4A4A4A",
        "accent":     "#0066CC",
        "background": "#FFFFFF",
        "surface":    "#F5F5F5",
        "text":       "#1A1A1A",
    },
}


_PALETTE_PAGE_TITLE: str = "Theme Palette"
_PALETTE_PAGE_HANDLE: str = "theme-palette"


def generate_palette(
    *,
    niche: str = "general",
) -> dict[str, Any]:
    """Build a structured palette spec for a niche.

    Args:
        niche: Lowercase niche key. Unknown niches fall back
            to ``general`` (safe monochrome + one accent).

    Returns:
        Dict with ``niche``, ``tokens`` (six semantic color
        slots), ``contrast`` (four WCAG ratios), and the two
        compliance flags. Always non-empty -- niche=general
        is the safe fallback.
    """
    niche_n = (niche or "general").strip().lower() or "general"
    tokens = _NICHE_PALETTES.get(
        niche_n, _NICHE_PALETTES["general"],
    )

    contrast = _compute_contrast_pairs(tokens)
    min_contrast = min(contrast.values()) if contrast else 0.0
    # WCAG AA: 4.5:1 normal text; AAA: 7:1 normal text.
    aa = min_contrast >= 4.5
    aaa = min_contrast >= 7.0

    return {
        "niche": niche_n,
        "tokens": dict(tokens),
        "contrast": contrast,
        "wcag_compliant_aa": aa,
        "wcag_compliant_aaa": aaa,
    }


def render_palette_html(spec: dict[str, Any]) -> str:
    """Render the structured palette as a Shopify page body.

    Output has two sections:

      1. A row of visible color swatches (one ``<div>`` per
         token) with hex labels and contrast ratios -- the
         operator-facing view.
      2. A ``<pre>`` block with the full JSON spec so a
         future theme-settings-write adapter can re-parse
         deterministically.

    Empty / non-dict spec -> empty string.
    """
    if not isinstance(spec, dict) or not spec.get("tokens"):
        return ""

    tokens = spec.get("tokens") or {}
    contrast = spec.get("contrast") or {}
    niche = html.escape(spec.get("niche", "") or "")
    aaa = bool(spec.get("wcag_compliant_aaa"))
    aa = bool(spec.get("wcag_compliant_aa"))

    swatches: list[str] = []
    for name, hex_value in tokens.items():
        safe_name = html.escape(str(name))
        safe_hex = html.escape(str(hex_value))
        swatches.append(
            f"<div class=\"palette__swatch\" "
            f"style=\"background-color:{safe_hex};\">"
            f"<span class=\"palette__label\">{safe_name}"
            f": {safe_hex}</span>"
            f"</div>"
        )

    compliance_line = (
        "WCAG AAA-compliant (>= 7:1 contrast)" if aaa
        else "WCAG AA-compliant (>= 4.5:1 contrast)" if aa
        else "below WCAG AA -- raise contrast before launch"
    )

    spec_json = html.escape(
        json.dumps(spec, indent=2, sort_keys=True),
    )

    return (
        "<section class=\"palette\">"
        f"<h1 class=\"palette__heading\">Theme Palette "
        f"({niche})</h1>"
        f"<p class=\"palette__compliance\">"
        f"{compliance_line}</p>"
        "<div class=\"palette__swatches\">"
        + "".join(swatches) +
        "</div>"
        "<h2>Contrast ratios</h2>"
        "<ul class=\"palette__contrast\">"
        + "".join(
            f"<li>{html.escape(k)}: "
            f"{v:.2f}:1</li>"
            for k, v in contrast.items()
        ) +
        "</ul>"
        "<h2>Theme spec (JSON)</h2>"
        f"<pre class=\"palette__json\">{spec_json}</pre>"
        "</section>"
    )


def apply_palette(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist the palette spec as a Shopify page (handle
    ``theme-palette``) so it's reachable from the admin and
    referenceable from Liquid.

    Args:
        spec: Dict from :func:`generate_palette`. Empty /
            non-dict short-circuits.
        store_id: Optional per-store Pattern Z scope.

    Returns:
        ``{applied, handle, error}``.
    """
    if not isinstance(spec, dict) or not spec.get("tokens"):
        return {
            "applied": False,
            "handle": _PALETTE_PAGE_HANDLE,
            "error": "no_palette_spec",
        }

    body_html = render_palette_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _PALETTE_PAGE_HANDLE,
            "error": "empty_render",
        }

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        _record(
            success=False, store_id=store_id,
            error="router_unavailable", spec=spec,
        )
        return {
            "applied": False,
            "handle": _PALETTE_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _PALETTE_PAGE_TITLE,
        "handle": _PALETTE_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "theme_palette router.execute raised: %s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _PALETTE_PAGE_HANDLE,
            "error": f"adapter_raise: {exc}",
        }

    ok = bool(getattr(result, "ok", False))
    error = getattr(result, "error", None)
    _record(
        success=ok, store_id=store_id,
        error=None if ok else str(error or "rejected"),
        spec=spec,
    )
    if ok:
        return {
            "applied": True,
            "handle": _PALETTE_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _PALETTE_PAGE_HANDLE,
        "error": str(error or "rejected"),
    }


# ── WCAG contrast helpers ─────────────────────────────────────


def _compute_contrast_pairs(
    tokens: dict[str, str],
) -> dict[str, float]:
    """Compute the four key WCAG contrast ratios for a
    palette's semantic slots: text-on-bg, primary-on-bg,
    text-on-surface, primary-on-surface.
    """
    bg = tokens.get("background", "#FFFFFF")
    surface = tokens.get("surface", "#FFFFFF")
    primary = tokens.get("primary", "#000000")
    text = tokens.get("text", "#000000")
    return {
        "primary_on_background": (
            round(_contrast(primary, bg), 2)
        ),
        "text_on_background": (
            round(_contrast(text, bg), 2)
        ),
        "primary_on_surface": (
            round(_contrast(primary, surface), 2)
        ),
        "text_on_surface": (
            round(_contrast(text, surface), 2)
        ),
    }


def _contrast(hex_a: str, hex_b: str) -> float:
    """WCAG 2.x relative-luminance contrast ratio between
    two hex colors. Returns 1.0..21.0 (white-on-white = 1,
    black-on-white = 21)."""
    la = _relative_luminance(_hex_to_rgb(hex_a))
    lb = _relative_luminance(_hex_to_rgb(hex_b))
    lighter, darker = (la, lb) if la >= lb else (lb, la)
    return (lighter + 0.05) / (darker + 0.05)


def _hex_to_rgb(hex_value: str) -> tuple[int, int, int]:
    """Parse #RRGGBB or RRGGBB. Invalid input -> black."""
    if not isinstance(hex_value, str):
        return (0, 0, 0)
    h = hex_value.strip().lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    try:
        return (
            int(h[0:2], 16),
            int(h[2:4], 16),
            int(h[4:6], 16),
        )
    except ValueError:
        return (0, 0, 0)


def _relative_luminance(
    rgb: tuple[int, int, int],
) -> float:
    """WCAG 2.x relative luminance for an sRGB triple."""
    def _channel(v: int) -> float:
        c = v / 255.0
        return (
            c / 12.92 if c <= 0.03928
            else ((c + 0.055) / 1.055) ** 2.4
        )

    r, g, b = rgb
    return (
        0.2126 * _channel(r)
        + 0.7152 * _channel(g)
        + 0.0722 * _channel(b)
    )


# ── Helpers ───────────────────────────────────────────────────


def _record(
    *,
    success: bool,
    store_id: str | None,
    error: str | None,
    spec: dict[str, Any],
) -> None:
    params: dict[str, Any] = {
        "handle": _PALETTE_PAGE_HANDLE,
        "niche": spec.get("niche", ""),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_theme_palette",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _PALETTE_PAGE_HANDLE,
                "niche": spec.get("niche", ""),
                "wcag_aaa": bool(
                    spec.get("wcag_compliant_aaa"),
                ),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "theme_palette record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "theme_palette router import failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "theme_palette capability resolve failed: %s",
            exc,
        )
        return None
