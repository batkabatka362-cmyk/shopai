"""Niche-aware homepage section ordering recommender.

Every Shopify theme renders the homepage as a stack of
sections (hero / featured collection / featured products /
testimonials / newsletter / etc.). Default themes ship a
single one-size-fits-all order; merchants change it
manually if at all.

But the right section order is heavily niche-dependent:

  * Food / pets / baby benefit from subscription pitch
    above-the-fold (high-frequency repurchase categories).
  * Jewelry needs craftsmanship + materials story before
    products (high consideration, low-volume buy).
  * Fashion benefits from new-arrivals + sale below the
    hero (browsing-driven shopping).
  * Tech wants specs + warranty trust above
    testimonials (high-AOV trust signals).

This module ships a structured section-order recommendation
per niche. Themes (Online Store 2.0 like Dawn) consume the
order by writing it into ``templates/index.json`` --
operators paste the recommended order into theme settings,
or a future ``SHOPIFY_UPDATE_THEME_FILE`` adapter wires it
directly.

Return shape from :func:`recommend_homepage_sections`::

    {
        "store_name": "Acme Food",
        "niche": "food",
        "sections": [
            {
                "name": "Hero",
                "rationale": "...",
                "above_fold": True,
            },
            {
                "name": "Subscription Pitch",
                "rationale": "Food = repeat purchase ...",
                "above_fold": True,
            },
            ...
        ],
        "ranking_notes": "...",
    }

Persists as a Shopify page (handle ``homepage-sections``)
with the recommended order + rationale per section -- same
operator-paste pattern as the other reference content
modules. Records via Pattern Z.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Universal sections every store benefits from. Order here
# is the BASELINE; niches reorder + insert their own
# specific sections.
#
# Each tuple: (name, rationale)
_UNIVERSAL_SECTIONS: dict[str, str] = {
    "Hero": (
        "Single message + CTA above the fold. Pair with "
        "the announcement bar so the brand promise + the "
        "offer land in the first 1.5 screens."
    ),
    "Featured Collection": (
        "Above-the-fold product entry point. Pick the "
        "highest-converting collection (best-sellers OR "
        "new arrivals)."
    ),
    "Featured Products": (
        "Hand-picked SKUs -- the 4-8 products you want "
        "every visitor to see."
    ),
    "Testimonials / Reviews": (
        "Social proof. Pulls aggregate ratings + "
        "specific review quotes."
    ),
    "Newsletter Signup": (
        "Email capture. Pair with welcome_discount so "
        "the signup leads to a 15% off code."
    ),
    "Footer": (
        "Navigation + policies + contact. Required by "
        "trust + legal."
    ),
}


# Per-niche recommended section order. Sections are
# ordered top-to-bottom on the homepage.
_NICHE_ORDERS: dict[str, list[str]] = {
    "beauty": [
        "Hero",
        "Newsletter Signup",  # Beauty has high email LTV
        "Featured Collection",  # Skincare typically
        "Featured Products",  # Best-sellers
        "Testimonials / Reviews",
        "Footer",
    ],
    "fashion": [
        "Hero",
        "Featured Collection",  # New Arrivals
        "Featured Products",
        "Testimonials / Reviews",
        "Newsletter Signup",
        "Footer",
    ],
    "tech": [
        "Hero",
        "Featured Products",  # Spec + warranty up top
        "Featured Collection",
        "Testimonials / Reviews",  # Trust before sale
        "Newsletter Signup",
        "Footer",
    ],
    "home": [
        "Hero",
        "Featured Collection",  # Room curation
        "Featured Products",
        "Testimonials / Reviews",
        "Newsletter Signup",
        "Footer",
    ],
    "food": [
        "Hero",
        "Subscription Pitch",  # Highest leverage section
        "Featured Collection",  # Pantry / Best-sellers
        "Featured Products",
        "Testimonials / Reviews",
        "Newsletter Signup",
        "Footer",
    ],
    "pets": [
        "Hero",
        "Subscription Pitch",  # Pet food repeats monthly
        "Featured Collection",  # By species
        "Featured Products",
        "Testimonials / Reviews",
        "Newsletter Signup",
        "Footer",
    ],
    "fitness": [
        "Hero",
        "Featured Collection",  # Apparel / Equipment
        "Featured Products",
        "Testimonials / Reviews",  # Athlete + use cases
        "Newsletter Signup",
        "Footer",
    ],
    "jewelry": [
        "Hero",
        "Craftsmanship Story",  # Jewelry-specific
        "Featured Collection",  # New / Bridal
        "Featured Products",
        "Testimonials / Reviews",
        "Newsletter Signup",
        "Footer",
    ],
    "outdoor": [
        "Hero",
        "Featured Collection",  # Activity-keyed
        "Featured Products",
        "Trail Stories",  # Outdoor-specific
        "Testimonials / Reviews",
        "Newsletter Signup",
        "Footer",
    ],
    "baby": [
        "Hero",
        "Subscription Pitch",  # Diapers / formula
        "Featured Collection",  # Age-stage curated
        "Featured Products",
        "Testimonials / Reviews",
        "Newsletter Signup",
        "Footer",
    ],
    "general": [
        "Hero",
        "Featured Collection",
        "Featured Products",
        "Testimonials / Reviews",
        "Newsletter Signup",
        "Footer",
    ],
}


# Niche-specific sections (NOT in the universal set).
# Rationales tuned for the niche.
_NICHE_SPECIFIC_SECTIONS: dict[
    str, dict[str, str],
] = {
    "food": {
        "Subscription Pitch": (
            "Food categories have natural repeat-purchase "
            "cadence (weekly / monthly). A clear "
            "subscribe-and-save pitch above the fold "
            "captures the highest-LTV cohort early in "
            "the session."
        ),
    },
    "pets": {
        "Subscription Pitch": (
            "Pet food + treats are subscription-natural. "
            "Above-fold pitch converts 2-3x better than "
            "burying it in the footer."
        ),
    },
    "baby": {
        "Subscription Pitch": (
            "Diapers + wipes + formula = recurring spend. "
            "Surface the subscribe-and-save offer above "
            "the fold so new parents see it session 1."
        ),
    },
    "jewelry": {
        "Craftsmanship Story": (
            "Jewelry is a considered purchase. Materials "
            "+ craftsmanship story builds trust BEFORE "
            "the price tag is visible. Move this above "
            "the product grid."
        ),
    },
    "outdoor": {
        "Trail Stories": (
            "User-generated trail content (real customers "
            "using gear in the field) outperforms studio "
            "shots for outdoor / adventure niches."
        ),
    },
}


_SECTIONS_PAGE_TITLE: str = "Homepage Section Order"
_SECTIONS_PAGE_HANDLE: str = "homepage-sections"


def recommend_homepage_sections(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build the niche-aware section-order recommendation.

    Args:
        store_name: Display name (returned for context).
            Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.

    Returns:
        ``{store_name, niche, sections: [...],
        ranking_notes: str}``. Each section:
        ``{name, rationale, above_fold}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    order = _NICHE_ORDERS.get(
        niche_n, _NICHE_ORDERS["general"],
    )
    niche_specific = _NICHE_SPECIFIC_SECTIONS.get(
        niche_n, {},
    )

    # Treat the first 3 sections as above-the-fold
    # (industry convention: ~2 screens of mobile scroll).
    sections: list[dict[str, Any]] = []
    for i, section_name in enumerate(order):
        rationale = (
            niche_specific.get(section_name)
            or _UNIVERSAL_SECTIONS.get(
                section_name,
                "Custom section.",
            )
        )
        sections.append({
            "name": section_name,
            "rationale": rationale,
            "above_fold": i < 3,
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "sections": sections,
        "ranking_notes": (
            "Sections are ordered top-to-bottom on the "
            "homepage. Above-the-fold = first 3 entries "
            "(roughly 2 screens of mobile scroll). The "
            "below-fold sections still load but require "
            "scroll to view."
        ),
    }


def render_sections_html(
    spec: dict[str, Any],
) -> str:
    if not isinstance(spec, dict) or not spec.get(
        "sections",
    ):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    niche = html.escape(spec.get("niche", "") or "")
    sections = spec.get("sections") or []
    notes = html.escape(
        spec.get("ranking_notes", "") or "",
    )

    rows: list[str] = []
    for i, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            continue
        section_name = html.escape(
            section.get("name", "") or "",
        )
        rationale = html.escape(
            section.get("rationale", "") or "",
        )
        above_fold = section.get("above_fold")
        fold_badge = (
            "<span class=\"section-fold "
            "section-fold--above\">Above the fold</span>"
            if above_fold else
            "<span class=\"section-fold "
            "section-fold--below\">Below the fold</span>"
        )
        rows.append(
            "<li class=\"section-row\">"
            f"<h3>{i}. {section_name}</h3>"
            f"{fold_badge}"
            f"<p>{rationale}</p>"
            "</li>"
        )

    return (
        "<section class=\"homepage-sections\">"
        f"<h1>{name} -- Homepage Section Order ({niche})</h1>"
        f"<p>{notes}</p>"
        "<ol class=\"section-list\">"
        + "".join(rows) +
        "</ol>"
        "</section>"
    )


def apply_sections(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist as Shopify page ``homepage-sections``."""
    if not isinstance(spec, dict) or not spec.get(
        "sections",
    ):
        return {
            "applied": False,
            "handle": _SECTIONS_PAGE_HANDLE,
            "error": "no_sections_spec",
        }

    body_html = render_sections_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _SECTIONS_PAGE_HANDLE,
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
            "handle": _SECTIONS_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _SECTIONS_PAGE_TITLE,
        "handle": _SECTIONS_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "homepage_sections router.execute raised: "
            "%s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _SECTIONS_PAGE_HANDLE,
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
            "handle": _SECTIONS_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _SECTIONS_PAGE_HANDLE,
        "error": str(error or "rejected"),
    }


# ── Helpers ───────────────────────────────────────────────────


def _record(
    *,
    success: bool,
    store_id: str | None,
    error: str | None,
    spec: dict[str, Any],
) -> None:
    sections = spec.get("sections") or []
    params: dict[str, Any] = {
        "handle": _SECTIONS_PAGE_HANDLE,
        "section_count": len(sections),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_homepage_sections",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _SECTIONS_PAGE_HANDLE,
                "section_count": len(sections),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "homepage_sections record_writeback raised: "
            "%s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "homepage_sections router import failed: %s",
            exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "homepage_sections capability resolve "
            "failed: %s", exc,
        )
        return None
