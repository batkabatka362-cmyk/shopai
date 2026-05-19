"""Niche-aware newsletter signup popup content.

Email captures are the single highest-LTV marketing
channel for an ecommerce store. The newsletter popup
(modal that fires on first visit or exit intent) is the
mechanism every successful Shopify store runs.

Industry conversion rates:
  * Static footer form: ~0.5% of visitors.
  * Exit-intent popup: 2-5% of visitors.
  * First-visit popup with discount: 4-10% of visitors.

Default themes ship NO popup. Operators have to install
Klaviyo / Privy / OptinMonster + write copy. Most write
generic copy and leave the same default offer running for
years.

This module fills both gaps:

  * Niche-aware copy (headline + subhead + form CTA +
    success message + decline link).
  * Two trigger variants -- **first_visit** (15s delay,
    fires once per session) and **exit_intent** (mouse-
    leave detection, fires once per session).
  * Pairs with ``welcome_discount.py`` -- the popup
    offer IS the welcome discount.

Persists as a Shopify page (handle ``newsletter-popup``)
with both variants laid out for paste-into-Klaviyo /
Privy / Shopify Forms.

Return shape from :func:`generate_newsletter_popups`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "variants": {
            "first_visit": {
                "headline": "...",
                "subhead": "...",
                "form_cta_label": "Get my 15% off",
                "success_message": "...",
                "decline_link_label": "...",
                "discount_code": "WELCOME15",
                "discount_pct": 15,
                "trigger": "first visit, 15s delay",
            },
            "exit_intent": {...},
        },
    }

Records via Pattern Z.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Niche-specific popup headlines + subheads. Each tuple:
# (first_visit_headline, first_visit_subhead,
#  exit_intent_headline, exit_intent_subhead).
#
# Voice matches the rest of the niche-aware launch chain
# (homepage_hero, email_content, etc.) so brand tone is
# consistent across the funnel.
_NICHE_COPY: dict[
    str, tuple[str, str, str, str],
] = {
    "beauty": (
        "Save 15% on your first routine",
        "Clean ingredients, honest formulas. Sign up + "
        "we'll send your code along with our skincare "
        "label-reading guide.",
        "Wait! Save 15% before you go",
        "Quick favor: drop your email and we'll send your "
        "first-order code. You can unsubscribe anytime.",
    ),
    "fashion": (
        "Get 15% off your first piece",
        "Curated styles, real-body sizing, free returns. "
        "Sign up + we'll send your code + new-arrivals "
        "first.",
        "Don't leave without your 15% off",
        "Stay in the loop on new drops + size guides. "
        "Code drops into your inbox same time as the "
        "welcome email.",
    ),
    "tech": (
        "Save 10% on your first order",
        "Premium tech that just works. Sign up + we'll "
        "send your code + early-access to product "
        "launches.",
        "Save 10% before you go",
        "Drop your email and we'll send the welcome code. "
        "No spam, unsubscribe anytime.",
    ),
    "home": (
        "Take 10% off your first piece",
        "Thoughtful home goods, built to last. Sign up + "
        "code + room-curation tips.",
        "10% off -- save before you go",
        "Email + code arrives in your inbox in seconds. "
        "Browse on your terms.",
    ),
    "food": (
        "Take 10% off + free shipping over $40",
        "Small-batch flavours, honestly sourced. Sign up "
        "+ we'll send your code + the seasonal pantry "
        "guide.",
        "Don't leave hungry -- 10% off awaits",
        "One quick signup. Code drops in your inbox + "
        "we send a curated pantry pick once a month.",
    ),
    "pets": (
        "Save 15% on your pet's first treat",
        "Pet-tested gear + vet-approved food. Sign up + "
        "code + species-specific recommendations.",
        "Wait -- 15% off your pet's order",
        "Drop your email + your pet's species. We'll "
        "tailor recommendations + send the welcome code.",
    ),
    "fitness": (
        "Take 15% off your first order",
        "Honest performance gear + third-party tested "
        "supplements. Sign up + code + new-product first "
        "looks.",
        "Save 15% before you go",
        "Code drops in your inbox in seconds. No spam, "
        "no inflated promises.",
    ),
    "jewelry": (
        "Save 10% on your first piece",
        "Heirloom-quality, honestly priced. Sign up + "
        "code + first looks at new collections.",
        "Don't leave without 10% off",
        "Drop your email -- we'll send the welcome code "
        "+ guides on selecting metals + stones.",
    ),
    "outdoor": (
        "Take 10% off your first trip's gear",
        "Field-tested gear, weather-honest. Sign up + "
        "code + trip-planning tips by activity.",
        "Wait -- 10% off your kit",
        "One quick signup. Code lands in your inbox + "
        "we send gear-test summaries monthly.",
    ),
    "baby": (
        "Save 15% on your first order",
        "Soft fabrics, safe finishes, parent-tested gear. "
        "Sign up + code + age-stage-specific picks.",
        "Wait -- 15% off your basket",
        "Drop your email + your baby's age. We'll send "
        "the welcome code + recommendations that grow "
        "with them.",
    ),
    "general": (
        "Save 10% on your first order",
        "Quality products, honest pricing, fast support. "
        "Sign up + we'll send your code.",
        "Don't leave without 10% off",
        "Quick signup -- code lands in your inbox + we'll "
        "keep you posted on new arrivals.",
    ),
}


_POPUP_PAGE_TITLE: str = "Newsletter Signup Popup"
_POPUP_PAGE_HANDLE: str = "newsletter-popup"


def generate_newsletter_popups(
    *,
    store_name: str,
    niche: str = "general",
    discount_code: str | None = None,
    discount_pct: int | None = None,
    first_visit_delay_seconds: int = 15,
) -> dict[str, Any]:
    """Build both popup variants.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.
        discount_code: Discount code to offer. When supplied,
            replaces the default WELCOME{pct} code in the
            copy. Pair with welcome_discount.py output.
        discount_pct: Percentage off. When supplied,
            overrides the niche-default pct in headlines
            + form CTAs.
        first_visit_delay_seconds: How long after page load
            the first-visit variant should fire. Default 15.

    Returns:
        ``{store_name, niche, variants: {first_visit,
        exit_intent}}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    copy = _NICHE_COPY.get(niche_n, _NICHE_COPY["general"])
    fv_headline, fv_subhead, ei_headline, ei_subhead = copy

    code_clean = (discount_code or "").strip().upper() or None
    pct_clean = (
        int(discount_pct)
        if discount_pct is not None
        and int(discount_pct) > 0
        else None
    )

    # When operator overrides pct, substitute it in the
    # default headlines. Headlines carry the niche-default
    # pct (10 or 15); replace cleanly if operator passes a
    # different value.
    if pct_clean is not None:
        fv_headline = _swap_pct(fv_headline, pct_clean)
        fv_subhead = _swap_pct(fv_subhead, pct_clean)
        ei_headline = _swap_pct(ei_headline, pct_clean)
        ei_subhead = _swap_pct(ei_subhead, pct_clean)
        effective_pct = pct_clean
    else:
        effective_pct = _extract_pct(fv_headline)

    # Default code is WELCOME{pct} unless operator
    # overrides
    effective_code = (
        code_clean
        or (
            f"WELCOME{effective_pct}"
            if effective_pct
            else None
        )
    )

    first_visit = _build_variant(
        name=name,
        headline=fv_headline,
        subhead=fv_subhead,
        code=effective_code,
        pct=effective_pct,
        trigger=(
            f"first visit, {int(first_visit_delay_seconds)}s "
            "delay; suppressed for 30d after signup or "
            "dismissal"
        ),
        decline_label="No thanks, full price is fine",
    )
    exit_intent = _build_variant(
        name=name,
        headline=ei_headline,
        subhead=ei_subhead,
        code=effective_code,
        pct=effective_pct,
        trigger=(
            "exit intent (mouse moves toward browser "
            "controls); suppressed for 30d after signup "
            "or dismissal"
        ),
        decline_label="No thanks",
    )

    return {
        "store_name": name,
        "niche": niche_n,
        "variants": {
            "first_visit": first_visit,
            "exit_intent": exit_intent,
        },
    }


def _build_variant(
    *,
    name: str,
    headline: str,
    subhead: str,
    code: str | None,
    pct: int | None,
    trigger: str,
    decline_label: str,
) -> dict[str, Any]:
    cta_label = (
        f"Get my {pct}% off"
        if pct else "Sign me up"
    )
    success_message = (
        f"Thanks! Your code is {code}. "
        f"It also lands in your inbox in the next minute."
        if code else
        f"Thanks! Watch your inbox -- {name} updates "
        "land within the hour."
    )
    return {
        "headline": headline,
        "subhead": subhead,
        "form_cta_label": cta_label,
        "success_message": success_message,
        "decline_link_label": decline_label,
        "discount_code": code,
        "discount_pct": pct,
        "trigger": trigger,
    }


def _extract_pct(text: str) -> int | None:
    """Pull the percent number from a headline like
    'Save 15% on your first routine'. None if no match."""
    import re
    m = re.search(r"(\d+)%", text)
    if m:
        try:
            return int(m.group(1))
        except (ValueError, TypeError):
            return None
    return None


def _swap_pct(text: str, new_pct: int) -> str:
    """Replace the first NN% in text with new_pct%."""
    import re
    return re.sub(
        r"\d+%",
        f"{new_pct}%",
        text,
        count=1,
    )


def render_popups_html(spec: dict[str, Any]) -> str:
    if not isinstance(spec, dict) or not spec.get(
        "variants",
    ):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    variants = spec.get("variants") or {}

    sections: list[str] = []
    for key in ("first_visit", "exit_intent"):
        v = variants.get(key)
        if not isinstance(v, dict):
            continue
        label = key.replace("_", " ").title()
        trigger = html.escape(v.get("trigger", "") or "")
        sections.append(
            "<section class=\"popup-variant\">"
            f"<h2>{html.escape(label)}</h2>"
            "<dl>"
            "<dt>Headline</dt>"
            f"<dd>{html.escape(v.get('headline', ''))}</dd>"
            "<dt>Subhead</dt>"
            f"<dd>{html.escape(v.get('subhead', ''))}</dd>"
            "<dt>Form CTA</dt>"
            f"<dd>{html.escape(v.get('form_cta_label', ''))}</dd>"
            "<dt>Success Message</dt>"
            f"<dd>{html.escape(v.get('success_message', ''))}</dd>"
            "<dt>Decline Link</dt>"
            f"<dd>{html.escape(v.get('decline_link_label', ''))}</dd>"
            "<dt>Trigger</dt>"
            f"<dd>{trigger}</dd>"
            "</dl>"
            "</section>"
        )

    return (
        "<section class=\"newsletter-popups\">"
        f"<h1>{name} -- Newsletter Signup Popups</h1>"
        "<p>Two variants -- paste into Klaviyo / Privy / "
        "Shopify Forms. Suppress for 30 days after signup "
        "or dismissal in your popup tool's frequency "
        "rules.</p>"
        + "".join(sections) +
        "</section>"
    )


def apply_popups(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(spec, dict) or not spec.get(
        "variants",
    ):
        return {
            "applied": False,
            "handle": _POPUP_PAGE_HANDLE,
            "error": "no_popup_spec",
        }

    body_html = render_popups_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _POPUP_PAGE_HANDLE,
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
            "handle": _POPUP_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _POPUP_PAGE_TITLE,
        "handle": _POPUP_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "newsletter_popup router.execute raised: %s",
            exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _POPUP_PAGE_HANDLE,
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
            "handle": _POPUP_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _POPUP_PAGE_HANDLE,
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
    variants = spec.get("variants") or {}
    params: dict[str, Any] = {
        "handle": _POPUP_PAGE_HANDLE,
        "variant_keys": sorted(variants.keys()),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_newsletter_popup",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _POPUP_PAGE_HANDLE,
                "variant_count": len(variants),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "newsletter_popup record_writeback raised: "
            "%s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "newsletter_popup router import failed: %s",
            exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "newsletter_popup capability resolve "
            "failed: %s", exc,
        )
        return None
