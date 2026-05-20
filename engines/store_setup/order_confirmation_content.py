"""Niche-aware order confirmation + shipping email content.

Shopify sends transactional emails automatically:

  * **Order confirmation** -- triggered immediately on
    checkout. Highest open rate in any merchant's
    email stack (60-80%).
  * **Shipping confirmation** -- triggered when the
    order ships. Second-highest open rate (45-65%).

Default Shopify templates work, but they're generic +
miss huge cross-sell + brand-voice opportunities:

  * The order-confirmation email is the perfect place
    to introduce subscription / loyalty / related
    products.
  * The shipping-confirmation email is the perfect
    place to ask for a follow + share + soft review
    request.

This module ships niche-aware content blocks for both
emails:

  * subject line + preheader (niche-tuned)
  * pre-receipt copy (brand voice + thank you)
  * post-receipt copy (cross-sell + community + next
    steps)

The output is paste-ready into Shopify Admin's
``Settings -> Notifications`` template editor OR into
Klaviyo / Shopify Email automation.

Return shape from
:func:`generate_order_confirmation_content`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "templates": {
            "order_confirmation": {
                subject, preheader,
                pre_receipt_text, pre_receipt_html,
                post_receipt_text, post_receipt_html,
            },
            "shipping_confirmation": { ... },
        },
    }

Persists as a Shopify page (handle
``order-confirmation-email``).
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Per-niche tuning: (
#   oc_subject, oc_pre, oc_post,
#   sc_subject, sc_pre, sc_post,
# )
_NICHE_COPY: dict[
    str, tuple[str, str, str, str, str, str],
] = {
    "beauty": (
        # Order confirmation
        "Order confirmed -- routine inbound",
        "Thanks for ordering. Your new routine pieces "
        "are being prepped now -- expect a shipping "
        "email within 1-3 business days.",
        "While you wait: read our ingredient deep-dive "
        "guide ({{shop.url}}/blogs/news) for context on "
        "what you just bought, plus tips for working it "
        "into a routine.",
        # Shipping confirmation
        "Your routine is on the way",
        "Your order ships today. Tracking info below.",
        "Once it lands: patch test new actives 24 hours "
        "before full use. Reply to this email with a "
        "photo of the haul -- we feature customer "
        "routines in our weekly digest.",
    ),
    "fashion": (
        "Order confirmed -- new pieces incoming",
        "Thanks for ordering. Pieces are being prepped "
        "and will ship within 1-3 business days.",
        "First time wearing something? Tag us with the "
        "fit. We feature real customers on our "
        "homepage + Instagram -- your fit might land "
        "the spot.",
        "Your pieces are on the way",
        "Order shipped. Tracking + delivery estimate "
        "below.",
        "When it arrives: try the fit immediately. Free "
        "exchanges within 30 days -- email us before "
        "you mail anything back so we can pre-reserve "
        "your replacement size.",
    ),
    "tech": (
        "Order confirmed -- spec sheet attached",
        "Thanks for ordering. Quality-check + packaging "
        "takes 1-3 business days; tracking email follows.",
        "Quickstart guides for everything you ordered "
        "are at {{shop.url}}/pages/quickstart. Bookmark "
        "before unboxing -- saves the 'where do I plug "
        "this in' moment.",
        "Your gear is on the way",
        "Order shipped. Tracking below.",
        "Warranty registration: complete the form linked "
        "in your unboxing notes within 30 days to "
        "activate the 2-year coverage.",
    ),
    "home": (
        "Order confirmed -- new pieces incoming",
        "Thanks for ordering. Items are being inspected "
        "+ packed; ship time 1-3 business days.",
        "Care guides for the materials you ordered "
        "(wood / ceramic / textile / etc.) live at "
        "{{shop.url}}/pages/care -- worth reading "
        "before first use.",
        "Your pieces are on the way",
        "Order shipped + tracking below.",
        "When it arrives: lay heavy pieces flat for "
        "24 hours before lifting fully (joinery settles). "
        "Photos of the final placement always welcome.",
    ),
    "food": (
        "Order confirmed -- pantry inbound",
        "Thanks. We ship Monday-Wednesday to avoid "
        "weekend transit. Expect shipping confirmation "
        "within 24 hours of your nearest shipping "
        "window.",
        "Recipes for everything you just ordered live "
        "at {{shop.url}}/blogs/news. Bookmark a few "
        "before the box arrives -- saves the 'what do "
        "I do with this' moment.",
        "Your pantry is on the way",
        "Order shipped + tracking below.",
        "Keep an eye on the box -- some items need "
        "refrigeration ASAP. Subscribe-and-save details "
        "in your account if you'd like recurring "
        "delivery.",
    ),
    "pets": (
        "Order confirmed -- pet supplies inbound",
        "Thanks for ordering. Your pet's order is being "
        "packed; ship time 1-3 business days.",
        "Feeding-transition tips for new food: mix the "
        "new with the old over 7-10 days. Guide at "
        "{{shop.url}}/blogs/news.",
        "Your pet's order is on the way",
        "Order shipped + tracking below.",
        "If your pet doesn't love it, email us. We "
        "either swap or refund -- food doesn't have to "
        "come back; donate to a local shelter.",
    ),
    "fitness": (
        "Order confirmed -- gear incoming",
        "Thanks for ordering. Gear is being packed; "
        "ships 1-3 business days.",
        "Supplement protocols + apparel sizing guides "
        "at {{shop.url}}/blogs/news. Read before first "
        "use, especially for new supplement stacks.",
        "Your gear is on the way",
        "Shipped + tracking below.",
        "When it arrives: take a 'before' photo. "
        "Customer transformations are our favourite "
        "reviews -- email us your 30-day update if "
        "you're game.",
    ),
    "jewelry": (
        "Order confirmed -- your piece is in production",
        "Thanks for ordering. Custom + made-to-order "
        "pieces take 2-4 weeks; in-stock pieces ship "
        "1-3 business days. You'll receive a separate "
        "email per shipment if there's more than one.",
        "Insurance + appraisal documents for pieces "
        "over $500 are emailed separately within 48 "
        "hours. Keep them filed with your home "
        "insurance.",
        "Your piece is on the way",
        "Shipped via insured carrier (signature on "
        "delivery). Tracking below.",
        "Care for sterling silver: store in the "
        "anti-tarnish pouch when not worn. We polish "
        "complimentary -- bring it back yearly.",
    ),
    "outdoor": (
        "Order confirmed -- gear inbound",
        "Thanks for ordering. Gear ships 1-3 business "
        "days from our warehouse.",
        "Field-test reports + gear-care guides at "
        "{{shop.url}}/blogs/news. Worth a read before "
        "your next trip.",
        "Your gear is on the way",
        "Shipped + tracking below.",
        "Send us a trip photo. Real-customer field "
        "shots end up on the homepage + earn a 10% "
        "credit for the next order.",
    ),
    "baby": (
        "Order confirmed -- nursery inbound",
        "Thanks. Order is being packed; ships 1-3 "
        "business days.",
        "Age-stage guide for what to expect month-by-"
        "month: {{shop.url}}/blogs/news. Bookmark for "
        "the next stage too -- we'll send a reminder "
        "as they grow.",
        "Your order is on the way",
        "Shipped + tracking below.",
        "When it arrives: check sizing immediately. "
        "Babies grow fast; we offer free size-swap "
        "exchanges within 60 days for clothing that "
        "didn't fit by the time it arrived.",
    ),
    "general": (
        "Order confirmed",
        "Thanks for your order. We're packing it now; "
        "shipping email follows in 1-3 business days.",
        "Questions? Reply to this email -- a real person "
        "responds within 24 business hours.",
        "Your order is on the way",
        "Shipped + tracking below.",
        "When it arrives, we'd love to hear how it "
        "went. Reply to this email or leave a review.",
    ),
}


_ORDER_EMAIL_PAGE_TITLE: str = "Order Confirmation Email"
_ORDER_EMAIL_PAGE_HANDLE: str = "order-confirmation-email"


def generate_order_confirmation_content(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build niche-aware order + shipping confirmation
    email content blocks.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.

    Returns:
        ``{store_name, niche, templates:
          {order_confirmation, shipping_confirmation}}``.
        Each template has subject + preheader +
        pre_receipt_text/html + post_receipt_text/html.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    copy = _NICHE_COPY.get(niche_n, _NICHE_COPY["general"])
    (
        oc_subject, oc_pre, oc_post,
        sc_subject, sc_pre, sc_post,
    ) = copy

    return {
        "store_name": name,
        "niche": niche_n,
        "templates": {
            "order_confirmation": _build_template(
                name=name,
                subject=oc_subject,
                pre_receipt=oc_pre,
                post_receipt=oc_post,
                trigger="immediately on checkout",
            ),
            "shipping_confirmation": _build_template(
                name=name,
                subject=sc_subject,
                pre_receipt=sc_pre,
                post_receipt=sc_post,
                trigger="when the order ships",
            ),
        },
    }


def _build_template(
    *,
    name: str,
    subject: str,
    pre_receipt: str,
    post_receipt: str,
    trigger: str,
) -> dict[str, Any]:
    """Build the {subject, preheader, pre_receipt_*,
    post_receipt_*} envelope.

    pre_receipt = text shown ABOVE the order line items
    in the email (greeting + brand voice).
    post_receipt = text shown BELOW the order line items
    (cross-sell + next-steps + community).

    The receipt itself (order items / totals / shipping
    address) is rendered by Shopify -- this module only
    provides the surrounding content.
    """
    preheader = pre_receipt.split(".")[0] + "."
    pre_text = (
        f"Hi {{{{first_name}}}},\n\n"
        f"{pre_receipt}"
    )
    pre_html = (
        f"<p>Hi {{{{first_name}}}},</p>"
        f"<p>{pre_receipt}</p>"
    )
    post_text = (
        f"\n\n{post_receipt}\n\n"
        f"-- The {name} team"
    )
    post_html = (
        f"<p>{post_receipt}</p>"
        f"<p>-- The {name} team</p>"
    )
    return {
        "subject": subject,
        "preheader": preheader,
        "pre_receipt_text": pre_text,
        "pre_receipt_html": pre_html,
        "post_receipt_text": post_text,
        "post_receipt_html": post_html,
        "trigger": trigger,
    }


def render_order_emails_html(
    spec: dict[str, Any],
) -> str:
    if not isinstance(spec, dict) or not spec.get(
        "templates",
    ):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    templates = spec.get("templates") or {}

    sections: list[str] = []
    for key in (
        "order_confirmation", "shipping_confirmation",
    ):
        t = templates.get(key)
        if not isinstance(t, dict):
            continue
        label = key.replace("_", " ").title()
        trigger = html.escape(t.get("trigger", "") or "")
        sections.append(
            "<section class=\"order-email-template\">"
            f"<h2>{html.escape(label)}</h2>"
            "<dl>"
            "<dt>Subject</dt>"
            f"<dd>{html.escape(t.get('subject', ''))}</dd>"
            "<dt>Preheader</dt>"
            f"<dd>{html.escape(t.get('preheader', ''))}</dd>"
            "<dt>Trigger</dt>"
            f"<dd>{trigger}</dd>"
            "<dt>Pre-receipt (plain text)</dt>"
            f"<dd><pre>{html.escape(t.get('pre_receipt_text', ''))}"
            "</pre></dd>"
            "<dt>Pre-receipt (HTML)</dt>"
            f"<dd><pre>{html.escape(t.get('pre_receipt_html', ''))}"
            "</pre></dd>"
            "<dt>Post-receipt (plain text)</dt>"
            f"<dd><pre>{html.escape(t.get('post_receipt_text', ''))}"
            "</pre></dd>"
            "<dt>Post-receipt (HTML)</dt>"
            f"<dd><pre>{html.escape(t.get('post_receipt_html', ''))}"
            "</pre></dd>"
            "</dl>"
            "</section>"
        )

    return (
        "<section class=\"order-emails\">"
        f"<h1>{name} -- Order Confirmation Emails</h1>"
        "<p>Paste these into Shopify Admin -> Settings -> "
        "Notifications, OR into Klaviyo / Shopify Email "
        "transactional templates. The receipt itself "
        "(line items / totals) is rendered by Shopify -- "
        "this module provides the surrounding pre- + "
        "post-receipt content.</p>"
        + "".join(sections) +
        "</section>"
    )


def apply_order_confirmation_content(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist as Shopify page
    ``order-confirmation-email``."""
    if not isinstance(spec, dict) or not spec.get(
        "templates",
    ):
        return {
            "applied": False,
            "handle": _ORDER_EMAIL_PAGE_HANDLE,
            "error": "no_order_email_spec",
        }

    body_html = render_order_emails_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _ORDER_EMAIL_PAGE_HANDLE,
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
            "handle": _ORDER_EMAIL_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _ORDER_EMAIL_PAGE_TITLE,
        "handle": _ORDER_EMAIL_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_confirmation_content "
            "router.execute raised: %s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _ORDER_EMAIL_PAGE_HANDLE,
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
            "handle": _ORDER_EMAIL_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _ORDER_EMAIL_PAGE_HANDLE,
        "error": str(error or "rejected"),
    }


# ── Helpers ──────────────────────────────────────────────


def _record(
    *,
    success: bool,
    store_id: str | None,
    error: str | None,
    spec: dict[str, Any],
) -> None:
    templates = spec.get("templates") or {}
    params: dict[str, Any] = {
        "handle": _ORDER_EMAIL_PAGE_HANDLE,
        "template_keys": sorted(templates.keys()),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_order_confirmation",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _ORDER_EMAIL_PAGE_HANDLE,
                "template_count": len(templates),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_confirmation_content "
            "record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_confirmation_content router import "
            "failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_confirmation_content capability "
            "resolve failed: %s", exc,
        )
        return None
