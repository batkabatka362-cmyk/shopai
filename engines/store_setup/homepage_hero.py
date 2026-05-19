"""Niche-aware homepage hero content generator + applier.

The above-the-fold homepage banner -- "hero" -- is the single
highest-conversion-leverage piece of copy on a Shopify store.
Visitors form an opinion in under 5 seconds; the hero is what
they see first. A fresh Shopify store running the default
theme hero is the conversion equivalent of a billboard that
says "Open for business" -- it doesn't sell.

This module generates a structured hero spec (h1 + subhead +
primary CTA + secondary CTA + optional image alt) sized to
fit any theme's hero section. Niche-aware so the copy
matches category convention (heirloom-quality / field-tested /
parent-tested / etc.).

The applier persists the hero as a Shopify ``page`` with
handle ``homepage-hero`` so:

  1. The content is reachable through the standard
     ``SHOPIFY_CREATE_PAGE`` / ``SHOPIFY_UPDATE_PAGE``
     adapters (no new capability).
  2. Themes can render it via a Liquid ``page`` reference if
     the merchant wires it up, OR the operator can paste the
     content into the theme's hero settings.
  3. ``launch_audit`` can detect "is a homepage hero
     prepared?" by checking for that page handle.

The structured spec is also returned to the caller so an
operator-facing UI (or a future direct-to-theme-settings
applier) can use it without re-generating.

Return shape from :func:`generate_hero`::

    {
        "headline": "Beauty that earns the bathroom shelf.",
        "subhead": "Clean ingredients. Honest formulas. ...",
        "primary_cta_label": "Shop Best Sellers",
        "primary_cta_url": "/collections/all",
        "secondary_cta_label": "Read Our Story",
        "secondary_cta_url": "/pages/about",
        "image_alt": "Acme Beauty hero",
    }

Records every push via Pattern Z so the autonomous learning
loop sees homepage-hero adoption per store -- a leading
indicator of "store is conversion-ready".
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Niche-specific hero content fragments. Each entry is
# ``(headline_template, subhead_template, primary_cta_label,
# secondary_cta_label)``. The templates may carry one of the
# placeholders ``{store_name}`` or ``{niche}``.
_HERO_FRAGMENTS: dict[
    str, tuple[str, str, str, str],
] = {
    "beauty": (
        "Beauty that earns the bathroom shelf.",
        "{store_name}: clean formulas, honest ingredients, "
        "real results -- the daily routine that delivers.",
        "Shop Best Sellers",
        "Read Our Story",
    ),
    "fashion": (
        "Style for the way you actually dress.",
        "{store_name}: quality fabrics, timeless cuts, "
        "sized to fit real bodies.",
        "Shop New Arrivals",
        "Read Our Story",
    ),
    "tech": (
        "Tech that just works -- and keeps working.",
        "{store_name}: premium materials, honest claims, "
        "reliable performance, day after day.",
        "Shop Gadgets",
        "How We Build",
    ),
    "home": (
        "Small upgrades that you'll notice every day.",
        "{store_name}: thoughtful design, sustainable "
        "materials, built to last past the next move.",
        "Shop the Home",
        "Read Our Story",
    ),
    "food": (
        "Honestly sourced, small-batch, real flavour.",
        "{store_name}: small-batch flavours from people "
        "who actually care about the ingredients.",
        "Shop the Pantry",
        "Read Our Story",
    ),
    "pets": (
        "Better gear, food, and play -- for the animals "
        "who run our households.",
        "{store_name}: pet-tested, vet-approved "
        "philosophies, and no questionable fillers.",
        "Shop for Dogs",
        "Read Our Story",
    ),
    "fitness": (
        "Gear for the days when training is the easy part.",
        "{store_name}: honest performance gear, "
        "transparent supplements, tested by people "
        "who actually train.",
        "Shop Apparel",
        "Read Our Story",
    ),
    "jewelry": (
        "Heirloom-quality jewelry, honestly priced.",
        "{store_name}: solid materials, considered "
        "craftsmanship, priced for the metal not the "
        "markup.",
        "Shop Necklaces",
        "Our Materials",
    ),
    "outdoor": (
        "Gear that goes the distance -- trail, water, "
        "everywhere in between.",
        "{store_name}: field-tested, weather-honest, "
        "repairs over replacements.",
        "Shop Camping",
        "Read Our Story",
    ),
    "baby": (
        "Soft, safe, and parent-tested.",
        "{store_name}: gentle fabrics, safe finishes, "
        "and gear that grows with your family.",
        "Shop the Nursery",
        "Read Our Story",
    ),
    "general": (
        "Quality you can trust, every order.",
        "{store_name}: hand-picked products, honest "
        "pricing, fast support.",
        "Shop Best Sellers",
        "Read Our Story",
    ),
}


# Map the niche's typical first-collection slug for the
# primary CTA URL. Falls back to /collections/all when
# unknown.
_PRIMARY_COLLECTION_URLS: dict[str, str] = {
    "beauty": "/collections/skincare",
    "fashion": "/collections/new-arrivals",
    "tech": "/collections/gadgets",
    "home": "/collections/home-decor",
    "food": "/collections/pantry",
    "pets": "/collections/dogs",
    "fitness": "/collections/apparel",
    "jewelry": "/collections/necklaces",
    "outdoor": "/collections/camping-hiking",
    "baby": "/collections/nursery",
}


_HERO_PAGE_TITLE: str = "Homepage Hero"
_HERO_PAGE_HANDLE: str = "homepage-hero"


def generate_hero(
    *,
    store_name: str,
    niche: str = "general",
    primary_cta_url: str | None = None,
    secondary_cta_url: str | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    """Build a structured homepage-hero spec.

    Args:
        store_name: Display name interpolated into the subhead.
            Empty / whitespace -> empty dict (caller can
            short-circuit).
        niche: Lowercase niche key. Unknown niches fall back
            to ``general``.
        primary_cta_url: Override for the primary CTA target.
            When omitted, defaults to the niche's typical
            first-collection slug.
        secondary_cta_url: Override for the secondary CTA
            target. Defaults to ``/pages/about``.
        image_url: Optional hero image URL (must be already
            uploaded to Shopify Files or external CDN). When
            None, the spec carries no image fields -- theme
            renders headline + subhead only.

    Returns:
        Structured spec dict (see module docstring). Empty
        dict when ``store_name`` is blank.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    fragments = _HERO_FRAGMENTS.get(
        niche_n, _HERO_FRAGMENTS["general"],
    )
    headline, subhead_tmpl, primary_label, secondary_label = (
        fragments
    )

    subhead = subhead_tmpl.replace("{store_name}", name)

    primary_url = (
        (primary_cta_url or "").strip()
        or _PRIMARY_COLLECTION_URLS.get(
            niche_n, "/collections/all",
        )
    )
    secondary_url = (
        (secondary_cta_url or "").strip() or "/pages/about"
    )

    out: dict[str, Any] = {
        "headline": headline,
        "subhead": subhead,
        "primary_cta_label": primary_label,
        "primary_cta_url": primary_url,
        "secondary_cta_label": secondary_label,
        "secondary_cta_url": secondary_url,
        "image_alt": f"{name} hero",
    }
    if image_url:
        out["image_url"] = image_url.strip()
    return out


def render_hero_html(spec: dict[str, Any]) -> str:
    """Render the structured spec as standalone HTML so the
    operator can paste it into a theme section or preview it
    inside the page applier.

    Output is intentionally simple semantic HTML -- no
    framework-specific markup -- so it works across every
    theme.
    """
    if not isinstance(spec, dict) or not spec:
        return ""
    headline = html.escape(spec.get("headline", "") or "")
    subhead = html.escape(spec.get("subhead", "") or "")
    p_label = html.escape(spec.get("primary_cta_label", "") or "")
    p_url = html.escape(spec.get("primary_cta_url", "") or "")
    s_label = html.escape(
        spec.get("secondary_cta_label", "") or "",
    )
    s_url = html.escape(spec.get("secondary_cta_url", "") or "")
    image_url = (spec.get("image_url") or "").strip()
    image_alt = html.escape(spec.get("image_alt", "") or "")

    parts: list[str] = ["<section class=\"hero\">"]
    if image_url:
        parts.append(
            f"<img src=\"{html.escape(image_url)}\" "
            f"alt=\"{image_alt}\" class=\"hero__image\" />"
        )
    parts.append(
        f"<h1 class=\"hero__headline\">{headline}</h1>"
    )
    if subhead:
        parts.append(
            f"<p class=\"hero__subhead\">{subhead}</p>"
        )
    cta_html: list[str] = []
    if p_label and p_url:
        cta_html.append(
            f"<a href=\"{p_url}\" "
            f"class=\"hero__cta hero__cta--primary\">"
            f"{p_label}</a>"
        )
    if s_label and s_url:
        cta_html.append(
            f"<a href=\"{s_url}\" "
            f"class=\"hero__cta hero__cta--secondary\">"
            f"{s_label}</a>"
        )
    if cta_html:
        parts.append(
            "<div class=\"hero__ctas\">"
            + "".join(cta_html)
            + "</div>"
        )
    parts.append("</section>")
    return "".join(parts)


def apply_hero(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist the hero spec as a Shopify page (handle
    ``homepage-hero``) so the content is reachable + visible
    in the admin.

    The page body is the structured-HTML render of the spec;
    its title is "Homepage Hero". Operators can either:

      1. Reference the page directly in a Liquid section
         (``{{ pages.homepage-hero.content }}``), OR
      2. Copy the rendered HTML into the theme's hero
         section settings.

    Args:
        spec: Dict from :func:`generate_hero`. Empty / non-dict
            short-circuits.
        store_id: Optional per-store recording scope.

    Returns:
        ``{applied, handle, error}``.
    """
    if not isinstance(spec, dict) or not spec:
        return {
            "applied": False,
            "handle": _HERO_PAGE_HANDLE,
            "error": "no_hero_spec",
        }

    body_html = render_hero_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _HERO_PAGE_HANDLE,
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
            "handle": _HERO_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _HERO_PAGE_TITLE,
        "handle": _HERO_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "homepage_hero router.execute raised: %s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _HERO_PAGE_HANDLE,
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
            "handle": _HERO_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _HERO_PAGE_HANDLE,
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
    params: dict[str, Any] = {
        "handle": _HERO_PAGE_HANDLE,
        "headline": spec.get("headline", ""),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_homepage_hero",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _HERO_PAGE_HANDLE,
                "has_image": bool(spec.get("image_url")),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "homepage_hero record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "homepage_hero router import failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "homepage_hero capability resolve failed: %s",
            exc,
        )
        return None
