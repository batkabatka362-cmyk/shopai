"""Niche-aware email content generator (welcome + abandoned
cart).

Two of the highest-leverage emails a Shopify store sends:

  1. **Welcome email** -- triggered when a customer subscribes
     or makes a first purchase. Defaults are generic
     ("Thanks for signing up!"); a niche-aware welcome reads
     like a real brand voice and drives the first purchase.
  2. **Abandoned cart email** -- triggered when checkout is
     started but not completed. Industry conversion lift from
     a well-written abandoned-cart email is 5-15%.

Shopify exposes email-content editing through:

  * `Settings -> Notifications` admin UI (manual paste)
  * Shopify Email / Shopify Flow apps for marketing
    automations
  * `EmailTemplate` GraphQL nodes for transactional
    customisation (limited scope)

This module produces the CONTENT (subject + body, plain text
+ HTML versions). Operators paste into:

  * Klaviyo / Mailchimp / Omnisend (most stores)
  * Shopify Email (Shopify-native)
  * Shopify's transactional templates (for order
    confirmations -- the schema is narrower)

We persist as a Shopify page (handle ``email-templates``)
with both versions side-by-side so the operator has a
single reference. Records via Pattern Z.

Return shape from :func:`generate_emails`::

    {
        "store_name": "Acme",
        "niche": "beauty",
        "templates": {
            "welcome": {
                "subject":   "Welcome to Acme -- ...",
                "preheader": "Get 15% off your first order...",
                "body_text": "Hi {{first_name}}, ...",
                "body_html": "<p>Hi {{first_name}}, ...</p>",
            },
            "abandoned_cart": {
                "subject":   "Did you forget something?",
                "preheader": "Your items are still here...",
                "body_text": "...",
                "body_html": "...",
            },
        },
    }

Liquid-style ``{{first_name}}`` / ``{{store.name}}`` /
``{{cart.line_items_count}}`` tokens are pre-set so
Shopify-native or Klaviyo paste-in works without rewrite.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Niche-specific opening line for the welcome email.
# Each template includes a ``{{first_name}}`` placeholder
# (Shopify + Klaviyo recognise it).
_WELCOME_OPENINGS: dict[str, str] = {
    "beauty": (
        "We're glad you're here. {{store.name}} is built on "
        "clean formulas + honest ingredients -- because the "
        "bathroom shelf deserves better."
    ),
    "fashion": (
        "Welcome in. {{store.name}} is built for the way "
        "you actually dress -- quality fabrics, timeless "
        "cuts, sized to fit real bodies."
    ),
    "tech": (
        "Glad you're here. {{store.name}} ships premium "
        "tech that just works -- and keeps working."
    ),
    "home": (
        "Welcome. {{store.name}} is built around small "
        "upgrades you'll notice every day -- thoughtful "
        "design, sustainable materials, built to last."
    ),
    "food": (
        "Welcome to the pantry. {{store.name}} carries "
        "small-batch flavours from people who care about "
        "the ingredients."
    ),
    "pets": (
        "Welcome -- on behalf of the animals who run our "
        "households. {{store.name}} is built around "
        "pet-tested gear, food, and play."
    ),
    "fitness": (
        "Welcome in. {{store.name}} ships honest "
        "performance gear and transparent supplements -- "
        "no fluff."
    ),
    "jewelry": (
        "Welcome. {{store.name}} carries heirloom-quality "
        "pieces -- solid materials, considered "
        "craftsmanship, priced for the metal not the "
        "markup."
    ),
    "outdoor": (
        "Welcome to the trail. {{store.name}} ships gear "
        "that goes the distance -- field-tested, "
        "weather-honest, repairs over replacements."
    ),
    "baby": (
        "Welcome. {{store.name}} is built around the "
        "smallest moments -- soft fabrics, safe finishes, "
        "and gear that grows with your family."
    ),
    "general": (
        "Welcome. {{store.name}} is built on quality "
        "products, honest pricing, and fast support."
    ),
}


# Niche-aware abandoned cart preheader + recovery message.
_CART_RECOVERY_LINES: dict[str, str] = {
    "beauty": (
        "Your routine starts here. Let's get that order "
        "across the finish line."
    ),
    "fashion": (
        "Your basket is still warm. Free returns if it "
        "doesn't fit."
    ),
    "tech": (
        "Your gear is ready when you are. Reliable "
        "performance, day after day."
    ),
    "home": (
        "Your upgrade is waiting. Built to last past the "
        "next move."
    ),
    "food": (
        "Your pantry is one click away. Small-batch + "
        "honestly sourced."
    ),
    "pets": (
        "Your pet's order is still here. Vet-approved + "
        "no fillers."
    ),
    "fitness": (
        "Your gear is waiting. Honest performance, "
        "transparent ingredients."
    ),
    "jewelry": (
        "Your piece is ready. Solid materials, honestly "
        "priced -- not in the catalogue, in your jewelry "
        "box."
    ),
    "outdoor": (
        "Your kit is ready for the next trip. Field-tested, "
        "weather-honest."
    ),
    "baby": (
        "Your basket is still here. Soft, safe, "
        "parent-tested."
    ),
    "general": (
        "Your items are still in your cart. We saved them "
        "for you."
    ),
}


_EMAIL_PAGE_TITLE: str = "Email Templates"
_EMAIL_PAGE_HANDLE: str = "email-templates"


def generate_emails(
    *,
    store_name: str,
    niche: str = "general",
    welcome_discount_code: str | None = None,
    welcome_discount_pct: int | None = None,
) -> dict[str, Any]:
    """Build niche-aware welcome + abandoned-cart email
    templates.

    Args:
        store_name: Display name (interpolated into subject
            + body). Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.
        welcome_discount_code: If supplied, the welcome
            email body includes a call-to-action with this
            code. Pair with ``welcome_discount.py``'s output
            for autonomous-launch end-to-end coverage.
        welcome_discount_pct: Percentage off the code is
            worth. Used in the email's CTA copy.

    Returns:
        ``{store_name, niche, templates: {welcome, abandoned_cart}}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    opening = _WELCOME_OPENINGS.get(
        niche_n, _WELCOME_OPENINGS["general"],
    )
    cart_recovery = _CART_RECOVERY_LINES.get(
        niche_n, _CART_RECOVERY_LINES["general"],
    )

    welcome = _build_welcome(
        name=name,
        opening=opening,
        discount_code=(
            (welcome_discount_code or "").strip().upper()
            or None
        ),
        discount_pct=welcome_discount_pct,
    )
    abandoned = _build_abandoned_cart(
        name=name, recovery_line=cart_recovery,
    )

    return {
        "store_name": name,
        "niche": niche_n,
        "templates": {
            "welcome": welcome,
            "abandoned_cart": abandoned,
        },
    }


def _build_welcome(
    *,
    name: str,
    opening: str,
    discount_code: str | None,
    discount_pct: int | None,
) -> dict[str, str]:
    subject = f"Welcome to {name}"
    preheader = (
        f"Use code {discount_code} for "
        f"{int(discount_pct)}% off your first order."
        if discount_code and discount_pct and discount_pct > 0
        else (
            "Glad you're here. Here's what to expect from "
            "your first order."
        )
    )

    cta_block_text = (
        (
            f"\n\nUse code {discount_code} for "
            f"{int(discount_pct)}% off your first order. "
            "Cap your visit with something you'll "
            "actually use."
        )
        if discount_code and discount_pct and discount_pct > 0
        else ""
    )
    cta_block_html = (
        (
            f"<p><strong>Use code {discount_code}</strong> "
            f"for {int(discount_pct)}% off your first "
            "order.</p>"
            "<p><a href=\"{{shop.url}}/collections/all\" "
            "class=\"btn\">Shop the store</a></p>"
        )
        if discount_code and discount_pct and discount_pct > 0
        else (
            "<p><a href=\"{{shop.url}}/collections/all\" "
            "class=\"btn\">Shop the store</a></p>"
        )
    )

    body_text = (
        f"Hi {{{{first_name}}}},\n\n"
        f"{opening}"
        f"{cta_block_text}\n\n"
        "Reply to this email any time -- a real person "
        "reads every message and gets back within 24 "
        "business hours.\n\n"
        f"-- The {name} team"
    )
    body_html = (
        f"<p>Hi {{{{first_name}}}},</p>"
        f"<p>{opening}</p>"
        f"{cta_block_html}"
        "<p>Reply to this email any time -- a real person "
        "reads every message and gets back within 24 "
        "business hours.</p>"
        f"<p>-- The {name} team</p>"
    )
    return {
        "subject": subject,
        "preheader": preheader,
        "body_text": body_text,
        "body_html": body_html,
    }


def _build_abandoned_cart(
    *,
    name: str,
    recovery_line: str,
) -> dict[str, str]:
    subject = "You left something behind"
    preheader = recovery_line
    body_text = (
        f"Hi {{{{first_name}}}},\n\n"
        f"{recovery_line}\n\n"
        "Your cart:\n"
        "{{cart.line_items_count}} item(s) saved for "
        "{{cart.expiry_minutes}} more minutes.\n\n"
        "Pick up where you left off:\n"
        "{{cart.recovery_url}}\n\n"
        "Questions? Reply to this email.\n\n"
        f"-- The {name} team"
    )
    body_html = (
        f"<p>Hi {{{{first_name}}}},</p>"
        f"<p>{recovery_line}</p>"
        "<p><strong>Your cart:</strong> "
        "{{cart.line_items_count}} item(s) saved for "
        "{{cart.expiry_minutes}} more minutes.</p>"
        "<p><a href=\"{{cart.recovery_url}}\" "
        "class=\"btn\">Complete your order</a></p>"
        "<p>Questions? Reply to this email.</p>"
        f"<p>-- The {name} team</p>"
    )
    return {
        "subject": subject,
        "preheader": preheader,
        "body_text": body_text,
        "body_html": body_html,
    }


def render_emails_html(spec: dict[str, Any]) -> str:
    """Render the email templates as a Shopify page body so
    operators have a single reference to copy from.

    Each template gets its own section (welcome, abandoned
    cart) with subject + preheader + the HTML body in a
    ``<pre>`` block and the text body in another. Everything
    HTML-escaped for safety.
    """
    if not isinstance(spec, dict) or not spec.get("templates"):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    templates = spec.get("templates") or {}

    sections: list[str] = []
    for key in ("welcome", "abandoned_cart"):
        tmpl = templates.get(key)
        if not isinstance(tmpl, dict):
            continue
        section_label = key.replace("_", " ").title()
        sections.append(
            "<section class=\"email-template\">"
            f"<h2>{html.escape(section_label)}</h2>"
            "<dl>"
            "<dt>Subject</dt>"
            f"<dd>{html.escape(tmpl.get('subject', ''))}</dd>"
            "<dt>Preheader</dt>"
            f"<dd>{html.escape(tmpl.get('preheader', ''))}</dd>"
            "<dt>Plain text</dt>"
            f"<dd><pre>{html.escape(tmpl.get('body_text', ''))}"
            "</pre></dd>"
            "<dt>HTML</dt>"
            f"<dd><pre>{html.escape(tmpl.get('body_html', ''))}"
            "</pre></dd>"
            "</dl>"
            "</section>"
        )

    return (
        "<section class=\"email-templates\">"
        f"<h1>{name} -- Email Templates</h1>"
        "<p>Paste these into your email service "
        "(Klaviyo / Shopify Email / Mailchimp). Liquid-style "
        "placeholders (<code>{{first_name}}</code>, "
        "<code>{{shop.url}}</code>, "
        "<code>{{cart.recovery_url}}</code>) are recognised "
        "by both Shopify-native and Klaviyo paste-in.</p>"
        + "".join(sections) +
        "</section>"
    )


def apply_emails(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist the email templates as a Shopify page (handle
    ``email-templates``).

    Args:
        spec: Dict from :func:`generate_emails`.
        store_id: Optional per-store recording scope.

    Returns:
        ``{applied, handle, error}``.
    """
    if not isinstance(spec, dict) or not spec.get("templates"):
        return {
            "applied": False,
            "handle": _EMAIL_PAGE_HANDLE,
            "error": "no_email_spec",
        }

    body_html = render_emails_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _EMAIL_PAGE_HANDLE,
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
            "handle": _EMAIL_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _EMAIL_PAGE_TITLE,
        "handle": _EMAIL_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "email_content router.execute raised: %s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _EMAIL_PAGE_HANDLE,
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
            "handle": _EMAIL_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _EMAIL_PAGE_HANDLE,
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
    templates = spec.get("templates") or {}
    params: dict[str, Any] = {
        "handle": _EMAIL_PAGE_HANDLE,
        "template_keys": sorted(templates.keys()),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_email_templates",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _EMAIL_PAGE_HANDLE,
                "template_count": len(templates),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "email_content record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "email_content router import failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "email_content capability resolve failed: %s",
            exc,
        )
        return None
