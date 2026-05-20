"""Niche-aware announcement bar content generator.

The announcement bar is the sticky top-of-page banner most
Shopify themes render. Default themes ship with placeholder
text ("Welcome to our store") which is conversion dead
weight: it takes the highest-visibility pixel real estate
on the storefront and uses it to say nothing.

A well-written announcement bar does ONE of:

  * Surface the free-shipping threshold (AOV lift)
  * Announce a launch promo or new collection
  * State a brand-trust point (made in / cruelty-free /
    sustainably sourced / etc.)
  * Highlight the welcome discount code

This module ships **multiple rotating banners** per niche
so the operator can pick the one that matches their
current campaign focus, or rotate them automatically.

Return shape from :func:`generate_announcement_bars`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "bars": [
            {
                "message": "Free shipping on orders $50+",
                "cta_label": "Shop Now",
                "cta_url": "/collections/all",
                "tone": "shipping_threshold",
                "when_to_use": "Always-on baseline",
            },
            ...
        ],
    }

Persists as a Shopify page (handle ``announcement-bar``)
with all banner options laid out side-by-side -- same
pattern as ``homepage_hero`` / ``email_content`` / etc.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Niche-specific banner content. Each entry:
# (message, cta_label, cta_url_path, tone, when_to_use).
# - message stays under 60 chars (most themes truncate
#   longer banners on mobile).
# - cta_url_path is appended to the storefront base so the
#   operator doesn't have to hardcode their domain.
_NICHE_BARS: dict[
    str,
    list[tuple[str, str, str, str, str]],
] = {
    "beauty": [
        (
            "Free shipping on orders $50+",
            "Shop Bestsellers",
            "/collections/skincare",
            "shipping_threshold",
            "Always-on baseline; pairs with the launch "
            "free-shipping discount.",
        ),
        (
            "Clean formulas, real results.",
            "Our Story",
            "/pages/about",
            "brand_claim",
            "Brand-trust pivot; rotate in for newer "
            "visitors.",
        ),
        (
            "First order? Take 15% off with WELCOME15",
            "Browse Collection",
            "/collections/all",
            "first_order_promo",
            "Rotate during top-of-funnel campaigns + "
            "paid traffic landings.",
        ),
    ],
    "fashion": [
        (
            "Free shipping + returns over $75",
            "Shop New In",
            "/collections/new-arrivals",
            "shipping_threshold",
            "Always-on; free returns is the #1 fashion "
            "buyer objection.",
        ),
        (
            "New drop: Spring collection live",
            "Shop the Drop",
            "/collections/new-arrivals",
            "new_collection",
            "Rotate during collection-launch weeks.",
        ),
        (
            "Welcome offer: 15% off your first order",
            "Browse Styles",
            "/collections/all",
            "first_order_promo",
            "Paid-traffic landings + new-visitor sessions.",
        ),
    ],
    "tech": [
        (
            "Free shipping over $75 + 2-yr warranty",
            "Shop Tech",
            "/collections/gadgets",
            "shipping_threshold",
            "Always-on; warranty is the high-AOV trust "
            "signal.",
        ),
        (
            "All products third-party tested",
            "Why It Matters",
            "/pages/about",
            "brand_claim",
            "Rotate for buyer-skeptical sessions; "
            "pairs with reviews.",
        ),
        (
            "WELCOME10 -- 10% off your first order",
            "Shop Best Sellers",
            "/collections/gadgets",
            "first_order_promo",
            "Paid traffic + first-visit cohort.",
        ),
    ],
    "home": [
        (
            "Free shipping on orders $100+",
            "Shop the Home",
            "/collections/home-decor",
            "shipping_threshold",
            "Always-on baseline.",
        ),
        (
            "Built to last past the next move",
            "Read Our Story",
            "/pages/about",
            "brand_claim",
            "Rotate for higher-AOV traffic.",
        ),
        (
            "WELCOME10 -- 10% off your first order",
            "Browse Collection",
            "/collections/all",
            "first_order_promo",
            "Paid traffic + email pop-up signups.",
        ),
    ],
    "food": [
        (
            "Free shipping on orders $40+",
            "Shop the Pantry",
            "/collections/pantry",
            "shipping_threshold",
            "Always-on; low threshold (food = low AOV "
            "+ high frequency).",
        ),
        (
            "Small-batch, honestly sourced",
            "How We Source",
            "/pages/about",
            "brand_claim",
            "Rotate for new visitors + brand-discovery "
            "sessions.",
        ),
        (
            "Subscribe + save 10% on every order",
            "View Subscriptions",
            "/collections/all",
            "subscription_promo",
            "Always-on for high-frequency niches; "
            "pairs with the loyalty Subscription "
            "Candidates segment.",
        ),
    ],
    "pets": [
        (
            "Free shipping on orders $49+",
            "Shop Dogs",
            "/collections/dogs",
            "shipping_threshold",
            "Always-on; threshold ~ typical 2-bag "
            "food order.",
        ),
        (
            "Vet-approved gear + food",
            "Our Promise",
            "/pages/about",
            "brand_claim",
            "Rotate for trust-anxious shoppers.",
        ),
        (
            "Subscribe + save 10% on every refill",
            "Browse Foods",
            "/collections/food",
            "subscription_promo",
            "Pet food is a subscription-natural "
            "category; pitch from session 1.",
        ),
    ],
    "fitness": [
        (
            "Free shipping over $75",
            "Shop Gear",
            "/collections/apparel",
            "shipping_threshold",
            "Always-on baseline.",
        ),
        (
            "Honest performance gear + tested supplements",
            "Read Our Tests",
            "/pages/about",
            "brand_claim",
            "Rotate for serious-athlete cohorts.",
        ),
        (
            "WELCOME15 -- 15% off first order",
            "Shop Apparel",
            "/collections/apparel",
            "first_order_promo",
            "Paid traffic + email pop-up.",
        ),
    ],
    "jewelry": [
        (
            "Free shipping + free returns over $100",
            "Shop Necklaces",
            "/collections/necklaces",
            "shipping_threshold",
            "Always-on; free returns is the #1 "
            "jewelry buyer ask.",
        ),
        (
            "Heirloom-quality, honestly priced",
            "Our Materials",
            "/pages/about",
            "brand_claim",
            "Rotate for higher-AOV cohorts.",
        ),
        (
            "Engraving available on select pieces",
            "Explore Engravables",
            "/collections/engagement-bridal",
            "feature_highlight",
            "Rotate around bridal / gift season.",
        ),
    ],
    "outdoor": [
        (
            "Free shipping over $75 + repair-not-replace",
            "Shop Camping",
            "/collections/camping-hiking",
            "shipping_threshold",
            "Always-on; repair-not-replace is brand "
            "promise.",
        ),
        (
            "Field-tested, weather-honest",
            "How We Test",
            "/pages/about",
            "brand_claim",
            "Rotate for trail-serious sessions.",
        ),
        (
            "WELCOME10 -- 10% off your first order",
            "Shop Apparel",
            "/collections/apparel",
            "first_order_promo",
            "Paid traffic + first-visit cohort.",
        ),
    ],
    "baby": [
        (
            "Free shipping on orders $50+",
            "Shop the Nursery",
            "/collections/nursery",
            "shipping_threshold",
            "Always-on baseline.",
        ),
        (
            "Soft, safe, parent-tested",
            "Our Promise",
            "/pages/about",
            "brand_claim",
            "Rotate for new-parent traffic.",
        ),
        (
            "Subscribe + save on diapers & essentials",
            "View Subscriptions",
            "/collections/feeding",
            "subscription_promo",
            "Always-on; diapers + formula = highest "
            "subscription LTV.",
        ),
    ],
    "general": [
        (
            "Free shipping on orders $50+",
            "Shop Best Sellers",
            "/collections/best-sellers",
            "shipping_threshold",
            "Always-on baseline.",
        ),
        (
            "WELCOME10 -- 10% off your first order",
            "Browse Collection",
            "/collections/all",
            "first_order_promo",
            "Paid traffic + first-visit cohort.",
        ),
    ],
}


_BAR_PAGE_TITLE: str = "Announcement Bar"
_BAR_PAGE_HANDLE: str = "announcement-bar"


def generate_announcement_bars(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build niche-aware announcement bar options.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.

    Returns:
        ``{store_name, niche, bars: [...]}``. Each bar:
        ``{message, cta_label, cta_url, tone, when_to_use}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    entries = _NICHE_BARS.get(
        niche_n, _NICHE_BARS["general"],
    )

    bars: list[dict[str, Any]] = []
    for message, cta_label, cta_url, tone, when in entries:
        bars.append({
            "message": message,
            "cta_label": cta_label,
            "cta_url": cta_url,
            "tone": tone,
            "when_to_use": when,
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "bars": bars,
    }


def render_bars_html(spec: dict[str, Any]) -> str:
    """Render the bars as a Shopify page body so the
    operator has a single reference for paste-into-theme.

    Each bar shows: rendered preview (the bar itself),
    plus operator-facing metadata (tone + when_to_use).
    """
    if not isinstance(spec, dict) or not spec.get("bars"):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    bars = spec.get("bars") or []

    sections: list[str] = []
    for i, bar in enumerate(bars):
        if not isinstance(bar, dict):
            continue
        message = html.escape(bar.get("message", "") or "")
        cta_label = html.escape(
            bar.get("cta_label", "") or "",
        )
        cta_url = html.escape(bar.get("cta_url", "") or "")
        tone = html.escape(bar.get("tone", "") or "")
        when_to_use = html.escape(
            bar.get("when_to_use", "") or "",
        )
        sections.append(
            "<section class=\"announcement-option\">"
            f"<h2>Option {i + 1} -- {tone}</h2>"
            "<div class=\"announcement-bar\">"
            f"<span class=\"announcement-bar__message\">"
            f"{message}</span>"
            + (
                f" <a href=\"{cta_url}\" "
                "class=\"announcement-bar__cta\">"
                f"{cta_label}</a>"
                if cta_label and cta_url else ""
            ) +
            "</div>"
            f"<p class=\"announcement-option__note\">"
            f"<strong>When to use:</strong> "
            f"{when_to_use}</p>"
            "</section>"
        )

    return (
        "<section class=\"announcement-bars\">"
        f"<h1>{name} -- Announcement Bar Options</h1>"
        "<p>Each option is a complete bar ready to paste "
        "into the theme's announcement section. Pick one "
        "as the default; rotate during campaigns + "
        "seasonal pushes.</p>"
        + "".join(sections) +
        "</section>"
    )


def apply_bars(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist the bar options as a Shopify page (handle
    ``announcement-bar``).

    Args:
        spec: Dict from :func:`generate_announcement_bars`.
        store_id: Optional per-store Pattern Z scope.

    Returns:
        ``{applied, handle, error}``.
    """
    if not isinstance(spec, dict) or not spec.get("bars"):
        return {
            "applied": False,
            "handle": _BAR_PAGE_HANDLE,
            "error": "no_bars_spec",
        }

    body_html = render_bars_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _BAR_PAGE_HANDLE,
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
            "handle": _BAR_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _BAR_PAGE_TITLE,
        "handle": _BAR_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "announcement_bar router.execute raised: %s",
            exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _BAR_PAGE_HANDLE,
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
            "handle": _BAR_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _BAR_PAGE_HANDLE,
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
    bars = spec.get("bars") or []
    params: dict[str, Any] = {
        "handle": _BAR_PAGE_HANDLE,
        "bar_count": len(bars),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_announcement_bar",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _BAR_PAGE_HANDLE,
                "bar_count": len(bars),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "announcement_bar record_writeback raised: "
            "%s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "announcement_bar router import failed: %s",
            exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "announcement_bar capability resolve failed: "
            "%s", exc,
        )
        return None
