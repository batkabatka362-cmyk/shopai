"""Niche-aware post-purchase review request email content.

`email_content.py` (PR #383) ships welcome + abandoned-cart
templates -- the two highest-leverage CUSTOMER-LIFECYCLE
emails. This module adds the third critical one: the
post-purchase review request.

Reviews compound. They:

  * Drive on-page conversion (social proof on PDPs).
  * Enable Schema.org Review aggregateRating rich snippets
    in Google -- the star ratings on search results that
    PR #388's FAQPage block paves the road for.
  * Feed product-research signals (which products buyers
    actually love).

Default Shopify themes ship NO review-request email.
Operators have to set it up in Klaviyo / Shopify Email /
Loox / Judge.me -- and most never write good copy. This
module fills that gap.

Two variants per niche:
  * **vanilla** -- generic ask, 7 days post-delivery.
  * **with_incentive** -- offers a small discount on next
    order in exchange for a review (14 days post-delivery).
    Pairs cleanly with `coupon_playbook.loyalty_second_order`
    -- the discount code IS the second-order nudge.

Return shape from :func:`generate_review_request_emails`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "templates": {
            "vanilla": {...},
            "with_incentive": {...},
        },
    }

Persists as a Shopify page (handle ``review-request-email``)
with both variants side-by-side for paste-into-tool.
Records via Pattern Z.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Niche-specific subject lines. Each niche has its own
# voice: beauty wants "loved it", tech wants "rate it",
# food wants "how did it taste", etc.
_NICHE_SUBJECTS: dict[str, tuple[str, str]] = {
    # (vanilla, with_incentive)
    "beauty": (
        "How are you liking your {{store.name}} order?",
        "{{first_name}}, leave a review -- get 10% off",
    ),
    "fashion": (
        "How did it fit, {{first_name}}?",
        "Share your fit -- get 10% off next time",
    ),
    "tech": (
        "How's the new gear treating you?",
        "Rate your {{store.name}} order -- get 10% off",
    ),
    "home": (
        "How does it look in your space?",
        "Share a photo -- get 10% off your next order",
    ),
    "food": (
        "How did it taste, {{first_name}}?",
        "Tell us how it tasted -- get 10% off",
    ),
    "pets": (
        "Did your pet love it?",
        "Tell us how your pet liked it -- 10% off",
    ),
    "fitness": (
        "How's the gear holding up?",
        "Review your gear -- 10% off next order",
    ),
    "jewelry": (
        "Loving your new piece?",
        "Share your piece -- 10% off your next",
    ),
    "outdoor": (
        "How did it perform on the trail?",
        "Trail-test review -- 10% off next gear",
    ),
    "baby": (
        "How's your little one liking it?",
        "Tell us what they thought -- 10% off",
    ),
    "general": (
        "How are you liking your order?",
        "Leave a review -- get 10% off your next order",
    ),
}


# Niche-specific body content. Each entry is the heart of
# the email body -- one paragraph that asks the right
# question for the category.
_NICHE_BODY_LINES: dict[str, str] = {
    "beauty": (
        "How's the new routine working out? A quick "
        "review on the product page helps us improve "
        "formulas and helps other shoppers pick the "
        "right SKU for their skin type."
    ),
    "fashion": (
        "How was the fit? A quick review (with a photo "
        "if you're game) helps other shoppers pick "
        "their size with confidence."
    ),
    "tech": (
        "How's the gear performing? A quick review "
        "helps other shoppers compare specs against "
        "real-world use, not marketing copy."
    ),
    "home": (
        "How does it look in your space? A quick "
        "review -- especially with a photo -- helps "
        "other shoppers see scale + finish in context."
    ),
    "food": (
        "How did it taste? A quick review helps us "
        "source better + helps other shoppers find "
        "what's worth buying."
    ),
    "pets": (
        "How did your pet take to it? A quick review "
        "helps other pet parents pick the right "
        "product for their animal."
    ),
    "fitness": (
        "How's the gear holding up after a few "
        "sessions? A real-use review helps other "
        "athletes pick gear that survives training, "
        "not just the photoshoot."
    ),
    "jewelry": (
        "Have you been wearing it daily? A quick "
        "review (with a photo if you'd like) helps "
        "other shoppers see how the piece looks beyond "
        "the studio shot."
    ),
    "outdoor": (
        "How did it perform on the trail? Weather + "
        "terrain notes are gold for other shoppers "
        "deciding between similar options."
    ),
    "baby": (
        "How's your little one getting on with it? "
        "A quick review -- especially age + stage "
        "details -- helps other parents pick what "
        "fits their family."
    ),
    "general": (
        "How are you liking your order? A quick "
        "review helps us improve + helps other "
        "shoppers make the right choice."
    ),
}


_REVIEW_EMAIL_PAGE_TITLE: str = "Review Request Email"
_REVIEW_EMAIL_PAGE_HANDLE: str = "review-request-email"


def generate_review_request_emails(
    *,
    store_name: str,
    niche: str = "general",
    incentive_code: str | None = None,
    incentive_pct: int | None = None,
    days_after_delivery_vanilla: int = 7,
    days_after_delivery_incentive: int = 14,
) -> dict[str, Any]:
    """Build niche-aware review-request email templates.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.
        incentive_code: Discount code for the incentive
            variant. When None, the incentive variant
            still ships but the body uses a generic
            "your next order" reward language.
        incentive_pct: Percentage for the incentive (used
            in subject + body when supplied).
        days_after_delivery_vanilla: When the vanilla
            email fires (caller passes to their email
            tool's automation). Default 7. Captured in
            spec for documentation.
        days_after_delivery_incentive: Same for incentive
            variant. Default 14.

    Returns:
        ``{store_name, niche, templates: {vanilla,
        with_incentive}}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    subjects = _NICHE_SUBJECTS.get(
        niche_n, _NICHE_SUBJECTS["general"],
    )
    body_line = _NICHE_BODY_LINES.get(
        niche_n, _NICHE_BODY_LINES["general"],
    )

    code_clean = (incentive_code or "").strip().upper() or None
    pct = (
        int(incentive_pct)
        if incentive_pct is not None
        and int(incentive_pct) > 0
        else None
    )

    vanilla = _build_vanilla(
        name=name,
        subject=subjects[0],
        body_line=body_line,
        days_after_delivery=int(
            days_after_delivery_vanilla,
        ),
    )
    incentive = _build_incentive(
        name=name,
        subject_template=subjects[1],
        body_line=body_line,
        code=code_clean,
        pct=pct,
        days_after_delivery=int(
            days_after_delivery_incentive,
        ),
    )

    return {
        "store_name": name,
        "niche": niche_n,
        "templates": {
            "vanilla": vanilla,
            "with_incentive": incentive,
        },
    }


def _build_vanilla(
    *,
    name: str,
    subject: str,
    body_line: str,
    days_after_delivery: int,
) -> dict[str, Any]:
    body_text = (
        f"Hi {{{{first_name}}}},\n\n"
        f"{body_line}\n\n"
        "Review the product on the page where you bought "
        "it:\n"
        "{{order.line_item.product.url}}\n\n"
        "Takes about 30 seconds. Thanks for being a "
        f"{name} customer.\n\n"
        f"-- The {name} team"
    )
    body_html = (
        f"<p>Hi {{{{first_name}}}},</p>"
        f"<p>{body_line}</p>"
        "<p><a href=\"{{order.line_item.product.url}}\" "
        "class=\"btn\">Leave a review</a></p>"
        "<p>Takes about 30 seconds. Thanks for being a "
        f"{name} customer.</p>"
        f"<p>-- The {name} team</p>"
    )
    return {
        "subject": subject,
        "preheader": (
            "A quick review helps us improve + helps "
            "other shoppers."
        ),
        "body_text": body_text,
        "body_html": body_html,
        "trigger": (
            f"{days_after_delivery} days after delivery"
        ),
    }


def _build_incentive(
    *,
    name: str,
    subject_template: str,
    body_line: str,
    code: str | None,
    pct: int | None,
    days_after_delivery: int,
) -> dict[str, Any]:
    if code and pct:
        subject = subject_template.replace(
            "10% off", f"{pct}% off",
        )
        reward_text = (
            f"\n\nAs a thank-you, code {code} takes "
            f"{pct}% off your next order. Drops into "
            "your inbox after the review posts."
        )
        reward_html = (
            f"<p><strong>Thank-you reward:</strong> "
            f"code <code>{code}</code> takes {pct}% off "
            "your next order. Drops into your inbox "
            "after your review posts.</p>"
        )
        preheader = (
            f"Leave a review, get {pct}% off your "
            "next order."
        )
    else:
        subject = subject_template
        # Generic reward language when no code is wired in
        reward_text = (
            "\n\nWe'll send a thank-you reward after "
            "the review posts."
        )
        reward_html = (
            "<p><strong>Thank-you reward:</strong> we'll "
            "send a discount after your review posts.</p>"
        )
        preheader = (
            "Leave a review, get a thank-you reward."
        )

    body_text = (
        f"Hi {{{{first_name}}}},\n\n"
        f"{body_line}\n\n"
        "Review the product on the page where you bought "
        "it:\n"
        "{{order.line_item.product.url}}"
        f"{reward_text}\n\n"
        f"-- The {name} team"
    )
    body_html = (
        f"<p>Hi {{{{first_name}}}},</p>"
        f"<p>{body_line}</p>"
        "<p><a href=\"{{order.line_item.product.url}}\" "
        "class=\"btn\">Leave a review</a></p>"
        f"{reward_html}"
        f"<p>-- The {name} team</p>"
    )
    return {
        "subject": subject,
        "preheader": preheader,
        "body_text": body_text,
        "body_html": body_html,
        "trigger": (
            f"{days_after_delivery} days after delivery"
        ),
        "incentive_code": code,
        "incentive_pct": pct,
    }


def render_review_emails_html(
    spec: dict[str, Any],
) -> str:
    """Render the review-request templates as a Shopify
    page body so the operator has a single reference to
    paste into Klaviyo / Shopify Email."""
    if not isinstance(spec, dict) or not spec.get("templates"):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    templates = spec.get("templates") or {}

    sections: list[str] = []
    for key in ("vanilla", "with_incentive"):
        tmpl = templates.get(key)
        if not isinstance(tmpl, dict):
            continue
        section_label = key.replace("_", " ").title()
        trigger = html.escape(
            tmpl.get("trigger", "") or "",
        )
        sections.append(
            "<section class=\"review-email-template\">"
            f"<h2>{html.escape(section_label)}</h2>"
            "<dl>"
            "<dt>Subject</dt>"
            f"<dd>{html.escape(tmpl.get('subject', ''))}</dd>"
            "<dt>Preheader</dt>"
            f"<dd>{html.escape(tmpl.get('preheader', ''))}</dd>"
            "<dt>Trigger</dt>"
            f"<dd>{trigger}</dd>"
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
        "<section class=\"review-emails\">"
        f"<h1>{name} -- Review Request Emails</h1>"
        "<p>Paste these into your email service. "
        "Trigger on order-delivered + the days-after-"
        "delivery in each section. Liquid placeholders "
        "(<code>{{first_name}}</code>, "
        "<code>{{order.line_item.product.url}}</code>) "
        "are recognised by Shopify-native and Klaviyo "
        "templates.</p>"
        + "".join(sections) +
        "</section>"
    )


def apply_review_emails(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist as Shopify page ``review-request-email``.

    Args:
        spec: Dict from :func:`generate_review_request_emails`.
        store_id: Optional per-store recording scope.
    """
    if not isinstance(spec, dict) or not spec.get("templates"):
        return {
            "applied": False,
            "handle": _REVIEW_EMAIL_PAGE_HANDLE,
            "error": "no_review_email_spec",
        }

    body_html = render_review_emails_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _REVIEW_EMAIL_PAGE_HANDLE,
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
            "handle": _REVIEW_EMAIL_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _REVIEW_EMAIL_PAGE_TITLE,
        "handle": _REVIEW_EMAIL_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "review_request_email router.execute "
            "raised: %s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _REVIEW_EMAIL_PAGE_HANDLE,
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
            "handle": _REVIEW_EMAIL_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _REVIEW_EMAIL_PAGE_HANDLE,
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
        "handle": _REVIEW_EMAIL_PAGE_HANDLE,
        "template_keys": sorted(templates.keys()),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_review_request_email",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _REVIEW_EMAIL_PAGE_HANDLE,
                "template_count": len(templates),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "review_request_email record_writeback "
            "raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "review_request_email router import "
            "failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "review_request_email capability resolve "
            "failed: %s", exc,
        )
        return None
