"""Niche-aware customer service canned response templates.

Different from ``support_kb.py`` (which generates a
storefront Q&A PAGE customers READ): this module
generates OPERATOR-FACING reply drafts the support team
PASTES INTO outbound emails.

Every ecommerce store gets the same 8-12 recurring
inbound questions:

  * "Where is my order?"
  * "I need to return / exchange this."
  * "It arrived damaged."
  * "I want to cancel my order."
  * "Do you ship to [country]?"
  * "How do I use my discount code?"
  * "Is this product right for [my use case]?"
  * "I never received my confirmation email."

Default support inbox = the operator typing each reply
from scratch. After the 100th "Where is my order?",
operators rage-quit support.

This module ships niche-aware canned response templates:
operator pastes into Gorgias / Zendesk / Help Scout /
their own inbox as a one-click reply. Pairs with
``support_kb`` -- the storefront PAGE deflects FAQs;
these templates handle what slips through.

Return shape from
:func:`generate_support_responses`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "responses": [
            {
                "trigger": "Where is my order?",
                "subject": "Re: Order tracking",
                "body": "Hi {{first_name}},\n\nLet me ...",
                "tone": "informational",
                "next_action": "verify tracking link",
            },
            ...
        ],
    }

Persists as a Shopify page (handle
``customer-support-responses``).
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Universal canned-response templates -- every store needs
# these regardless of niche.
# Each tuple: (trigger, subject, body, tone, next_action).
_UNIVERSAL_RESPONSES: list[
    tuple[str, str, str, str, str]
] = [
    (
        "Where is my order?",
        "Re: Order #{{order.number}} tracking",
        "Hi {{first_name}},\n\nThanks for reaching out. "
        "Your order shipped on {{order.shipped_at}} and "
        "tracking is here: {{order.tracking_url}}.\n\n"
        "Standard delivery takes 3-7 business days "
        "domestic / 7-21 international. If the tracking "
        "hasn't updated in 48+ hours, the carrier "
        "occasionally lags; reach back out if it's not "
        "moving by tomorrow.\n\n"
        "-- The {{store.name}} team",
        "informational",
        "verify tracking link works + tracking event is "
        "recent",
    ),
    (
        "Return / exchange request",
        "Re: Return for order #{{order.number}}",
        "Hi {{first_name}},\n\nHappy to help -- "
        "{{store.name}} accepts returns within 30 days "
        "(unused, original packaging). Reply with:\n\n"
        "  1. Order # (#{{order.number}} -- got it)\n"
        "  2. Which item(s) you'd like to return\n"
        "  3. Reason (sizing / didn't match expectations "
        "/ etc.)\n\nWe'll send a prepaid return label "
        "within 24 hours.\n\n"
        "-- The {{store.name}} team",
        "helpful",
        "wait for item list + reason",
    ),
    (
        "Damaged on arrival",
        "Re: Damaged item -- order #{{order.number}}",
        "Hi {{first_name}},\n\nReally sorry to hear "
        "that. We'll fix this immediately. Please reply "
        "with:\n\n  1. Photo of the damaged item\n"
        "  2. Photo of the packaging (helps us file "
        "a carrier claim)\n\nReplacement goes out within "
        "1 business day of seeing the photos -- no need "
        "to return the damaged piece.\n\n"
        "-- The {{store.name}} team",
        "apologetic",
        "ship replacement on photo receipt",
    ),
    (
        "Cancel order before shipping",
        "Re: Cancel order #{{order.number}}",
        "Hi {{first_name}},\n\nLet me check whether "
        "the order has shipped. If it's still in our "
        "warehouse I can pull it before it leaves.\n\n"
        "Reply 'cancel' and I'll confirm within an hour.\n"
        "If it's already shipped I'll send a return "
        "label for when it arrives.\n\n"
        "-- The {{store.name}} team",
        "responsive",
        "check fulfillment status; pull or ship label",
    ),
    (
        "International shipping question",
        "Re: International shipping",
        "Hi {{first_name}},\n\nThanks for the interest. "
        "{{store.name}} ships to most countries. Delivery "
        "estimate to your address is at checkout once "
        "you add items + shipping address.\n\n"
        "Customs duties + taxes are the buyer's "
        "responsibility -- we can't pre-pay them; the "
        "carrier collects on delivery. Cost varies by "
        "country.\n\n"
        "-- The {{store.name}} team",
        "informational",
        "(no action; informational reply)",
    ),
    (
        "Discount code not working",
        "Re: Discount code issue",
        "Hi {{first_name}},\n\nLet me check the code. "
        "Could you confirm:\n\n"
        "  1. The exact code you're entering (case "
        "matters)?\n"
        "  2. Your cart subtotal (some codes require a "
        "minimum)?\n  3. Whether you've used the code "
        "before (some are one-per-customer)?\n\n"
        "I'll verify the code and send a one-time "
        "manual discount if there's a system issue.\n\n"
        "-- The {{store.name}} team",
        "helpful",
        "check code status + send manual fix if "
        "needed",
    ),
    (
        "Product fit / recommendation",
        "Re: Help choosing the right product",
        "Hi {{first_name}},\n\nHappy to help. To "
        "recommend the right pick, tell me a bit "
        "about:\n\n  1. What you're trying to "
        "[solve / achieve / find]\n  2. What you've "
        "tried before (so I don't suggest the same)\n"
        "  3. Any constraints (budget / allergies / "
        "specific brands you avoid)\n\nI'll send 2-3 "
        "tailored picks within a day.\n\n"
        "-- The {{store.name}} team",
        "consultative",
        "wait for context; send 2-3 picks",
    ),
    (
        "No confirmation email received",
        "Re: Missing order confirmation",
        "Hi {{first_name}},\n\nNo problem. Two quick "
        "checks:\n\n  1. Spam / promotions folder -- "
        "confirmation emails frequently land there.\n"
        "  2. Email address you entered at checkout "
        "-- reply with the email you EXPECTED to use "
        "+ the order # if you have it.\n\n"
        "I'll resend the confirmation manually within "
        "the hour.\n\n"
        "-- The {{store.name}} team",
        "responsive",
        "resend confirmation + (optional) update email "
        "on order",
    ),
]


# Niche-specific canned responses on top of the
# universal set.
_NICHE_RESPONSES: dict[
    str, list[tuple[str, str, str, str, str]],
] = {
    "beauty": [
        (
            "Sensitive skin / allergy concern",
            "Re: Sensitive-skin product question",
            "Hi {{first_name}},\n\nThanks for asking "
            "before buying -- smart. Full ingredient "
            "list for the product is on the PDP under "
            "'Ingredients'. If you have a specific "
            "allergen, reply with it + the product "
            "name and I'll cross-check before you "
            "order.\n\nFor sensitive skin: patch test "
            "a pea-sized amount on the inside of your "
            "wrist; wait 24 hours.\n\n"
            "-- The {{store.name}} team",
            "consultative",
            "verify ingredients vs allergen",
        ),
        (
            "Routine recommendation",
            "Re: Routine for [skin concern]",
            "Hi {{first_name}},\n\nLet's build you a "
            "routine. Reply with:\n\n  1. Skin type "
            "(dry / oily / combo / sensitive)\n"
            "  2. Primary concern (acne / aging / "
            "hydration / dullness / etc.)\n  3. Current "
            "routine (so I can flag overlap)\n\n"
            "I'll send a 3-step routine within a day -- "
            "products tagged for your skin type + "
            "concern.\n\n"
            "-- The {{store.name}} team",
            "consultative",
            "wait for context; send 3-step routine",
        ),
    ],
    "fashion": [
        (
            "Sizing question",
            "Re: Size advice for [item]",
            "Hi {{first_name}},\n\nSize guides are on "
            "every product page (Size Guide button "
            "near the size selector). Quickest path: "
            "measure a similar item you already own "
            "(chest / waist / inseam) and match it to "
            "our garment measurements -- not the "
            "letter size.\n\nWhen in doubt: size up. "
            "Returns are free within 30 days.\n\n"
            "-- The {{store.name}} team",
            "informational",
            "(self-serve; offer free returns)",
        ),
        (
            "Exchange (size swap)",
            "Re: Size swap for order #{{order.number}}",
            "Hi {{first_name}},\n\nSize swap is "
            "free within 30 days. Reply with the "
            "size you want and I'll:\n\n  1. Reserve "
            "the new size in our warehouse\n"
            "  2. Email a return label for the "
            "current piece\n  3. Ship the new size as "
            "soon as the return label is scanned by "
            "the carrier\n\nTotal turnaround: 7-10 "
            "days door-to-door.\n\n"
            "-- The {{store.name}} team",
            "responsive",
            "reserve stock + ship label",
        ),
    ],
    "tech": [
        (
            "Compatibility question",
            "Re: Compatibility -- {{product_title}}",
            "Hi {{first_name}},\n\nLet me check. "
            "Reply with the exact model number of "
            "your device (settings -> about -> model). "
            "I'll confirm compatibility before you "
            "order so there are no surprises.\n\n"
            "-- The {{store.name}} team",
            "consultative",
            "verify compatibility against device model",
        ),
        (
            "Warranty claim",
            "Re: Warranty claim -- order "
            "#{{order.number}}",
            "Hi {{first_name}},\n\nSorry to hear it's "
            "not working as expected. Most items carry "
            "a 1-2 year manufacturer warranty. Please "
            "send:\n\n  1. Order # (#{{order.number}} "
            "-- got it)\n  2. Brief description of the "
            "issue\n  3. Photo or short video showing "
            "the problem\n\nI'll route to the manufacturer "
            "+ confirm next steps within 1 business "
            "day.\n\n"
            "-- The {{store.name}} team",
            "responsive",
            "submit warranty claim to manufacturer",
        ),
    ],
    "food": [
        (
            "Allergen check",
            "Re: Allergen question",
            "Hi {{first_name}},\n\nFull ingredient "
            "list + allergens are on every product "
            "page. If you have a specific allergen "
            "+ product, reply with both and I'll "
            "double-check our supplier's most recent "
            "spec sheet.\n\n"
            "-- The {{store.name}} team",
            "consultative",
            "verify allergen against supplier spec",
        ),
        (
            "Expired or off-flavour item",
            "Re: Item issue -- order "
            "#{{order.number}}",
            "Hi {{first_name}},\n\nReally sorry. "
            "Photos help -- could you reply with:\n\n"
            "  1. Photo of the product + best-before "
            "date on the package\n  2. Brief "
            "description of the issue (taste / smell "
            "/ appearance)\n\nReplacement goes out "
            "within a day; refund is also fine if "
            "you'd prefer.\n\n"
            "-- The {{store.name}} team",
            "apologetic",
            "verify issue + ship replacement",
        ),
    ],
    "pets": [
        (
            "My pet doesn't like it",
            "Re: Product not a hit -- order "
            "#{{order.number}}",
            "Hi {{first_name}},\n\nThat happens -- "
            "pets are picky. {{store.name}} has a "
            "satisfaction guarantee. Tell me:\n\n"
            "  1. Which product\n  2. Your pet's "
            "species / age\n  3. What didn't work "
            "(taste / texture / size)\n\nWe'll either "
            "swap it for a different formula OR "
            "refund. No need to ship anything back -- "
            "donate to a local shelter.\n\n"
            "-- The {{store.name}} team",
            "helpful",
            "refund / send swap recommendation",
        ),
        (
            "Recommend food for [age / breed]",
            "Re: Food recommendation for your pet",
            "Hi {{first_name}},\n\nHappy to help. "
            "Reply with:\n\n  1. Species + breed\n"
            "  2. Age + weight\n  3. Any dietary needs "
            "(grain-free / single-protein / "
            "kidney-friendly / etc.)\n  4. Current "
            "food (so I don't recommend the same)\n\n"
            "I'll send 2-3 picks within a day.\n\n"
            "-- The {{store.name}} team",
            "consultative",
            "wait for context; send 2-3 picks",
        ),
    ],
    "fitness": [
        (
            "Supplement stack advice",
            "Re: Stack recommendation",
            "Hi {{first_name}},\n\nHappy to help -- "
            "but a real disclaimer first: I'm not a "
            "doctor + can only suggest based on "
            "general industry usage. Reply with:\n\n"
            "  1. Goal (recovery / performance / "
            "endurance / etc.)\n  2. Current stack\n"
            "  3. Any medical conditions or meds\n\n"
            "I'll send 2-3 picks. If anything looks "
            "complex I'll suggest checking with your "
            "doctor first.\n\n"
            "-- The {{store.name}} team",
            "consultative",
            "wait for context; send picks + DR "
            "disclaimer",
        ),
    ],
    "jewelry": [
        (
            "Resize / repair",
            "Re: Resize request",
            "Hi {{first_name}},\n\nResizes are "
            "complimentary for the first resize within "
            "a year of purchase. Reply with:\n\n"
            "  1. Current size + desired size\n"
            "  2. Order # (#{{order.number}})\n\n"
            "I'll send a prepaid insured shipping "
            "label. Resize takes 2-3 weeks from when "
            "we receive the piece.\n\n"
            "-- The {{store.name}} team",
            "premium",
            "ship insured label; flag resize ticket",
        ),
        (
            "Appraisal / insurance docs",
            "Re: Appraisal documents",
            "Hi {{first_name}},\n\nAppraisal documents "
            "for pieces over $500 are emailed "
            "automatically within 48 hours of "
            "purchase. If you didn't see one:\n\n"
            "  1. Check your spam folder\n"
            "  2. Confirm the order # (this gets the "
            "fastest response)\n\nI'll resend manually "
            "if it's missing.\n\n"
            "-- The {{store.name}} team",
            "premium",
            "resend appraisal PDF",
        ),
    ],
    "outdoor": [
        (
            "Gear repair / warranty",
            "Re: Gear repair claim",
            "Hi {{first_name}},\n\nLet me route this. "
            "We partner with the manufacturer on most "
            "warranty repairs. Reply with:\n\n"
            "  1. Order # (#{{order.number}})\n"
            "  2. Description of the issue + photos\n"
            "  3. Whether it's a manufacturing defect "
            "or wear-and-tear\n\nFor manufacturing "
            "defects: replacement within 1-2 weeks.\n"
            "For wear-and-tear: many brands offer "
            "discounted repairs; I'll quote within "
            "2 business days.\n\n"
            "-- The {{store.name}} team",
            "consultative",
            "route warranty claim; provide quote if "
            "wear",
        ),
    ],
    "baby": [
        (
            "Sizing -- baby grew out of it before "
            "wearing",
            "Re: Size swap -- order "
            "#{{order.number}}",
            "Hi {{first_name}},\n\nThat happens often "
            "-- babies grow faster than shipping. "
            "{{store.name}} offers free size-swap "
            "exchanges within 60 days for clothing "
            "that didn't fit by the time it arrived. "
            "Reply with the size you need and I'll:\n\n"
            "  1. Reserve the new size\n"
            "  2. Email a return label\n"
            "  3. Ship the new size as soon as the "
            "return is scanned by the carrier\n\n"
            "-- The {{store.name}} team",
            "responsive",
            "reserve new size; ship label",
        ),
        (
            "Safety certification question",
            "Re: Safety certifications",
            "Hi {{first_name}},\n\nGreat question. "
            "All products meet CPSIA + EN-71 safety "
            "standards. Specific certifications "
            "(OEKO-TEX / GOTS / BPA-free / etc.) are "
            "listed on each product page. Tell me "
            "which product + certification you're "
            "checking, and I'll send the cert PDF "
            "directly.\n\n"
            "-- The {{store.name}} team",
            "informational",
            "send specific cert PDF",
        ),
    ],
    "home": [
        (
            "Care instructions for [material]",
            "Re: Care instructions",
            "Hi {{first_name}},\n\nGreat question. "
            "Care varies by material; the product "
            "page has the full care guide under "
            "'Care' on the PDP. Quick basics:\n\n"
            "  * Wood: dust weekly, oil yearly\n"
            "  * Ceramic: hand-wash or dishwasher "
            "(check page)\n  * Linen: wash cold, "
            "hang dry\n\nIf you want material-"
            "specific guidance, reply with the "
            "product name and I'll send the full "
            "care PDF.\n\n"
            "-- The {{store.name}} team",
            "informational",
            "(self-serve; send PDF if needed)",
        ),
    ],
    "general": [],
}


_RESPONSE_PAGE_TITLE: str = "Customer Support Responses"
_RESPONSE_PAGE_HANDLE: str = "customer-support-responses"


def generate_support_responses(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build niche-aware canned response templates.

    Args:
        store_name: Display name (interpolated into
            templates). Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general
            (universal-only).

    Returns:
        ``{store_name, niche, responses: [...]}``.
        Universal responses always present + niche-
        specific stacked on top.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    niche_entries = _NICHE_RESPONSES.get(niche_n, [])

    responses: list[dict[str, Any]] = []
    for entry in _UNIVERSAL_RESPONSES + niche_entries:
        trigger, subject, body, tone, next_action = entry
        responses.append({
            "trigger": trigger,
            "subject": subject,
            "body": body,
            "tone": tone,
            "next_action": next_action,
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "responses": responses,
    }


def render_responses_html(spec: dict[str, Any]) -> str:
    if not isinstance(spec, dict) or not spec.get(
        "responses",
    ):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    responses = spec.get("responses") or []

    sections: list[str] = []
    for r in responses:
        if not isinstance(r, dict):
            continue
        sections.append(
            "<section class=\"response-template\">"
            f"<h2>{html.escape(r.get('trigger', ''))}</h2>"
            "<dl>"
            "<dt>Subject</dt>"
            f"<dd><code>{html.escape(r.get('subject', ''))}</code></dd>"
            "<dt>Tone</dt>"
            f"<dd>{html.escape(r.get('tone', ''))}</dd>"
            "<dt>Body</dt>"
            f"<dd><pre>{html.escape(r.get('body', ''))}</pre></dd>"
            "<dt>Next Action</dt>"
            f"<dd>{html.escape(r.get('next_action', ''))}</dd>"
            "</dl>"
            "</section>"
        )

    return (
        "<section class=\"support-responses\">"
        f"<h1>{name} -- Customer Support Response "
        "Templates</h1>"
        "<p>Operator-facing canned reply drafts. Paste "
        "into Gorgias / Zendesk / Help Scout / your "
        "inbox as one-click responses. Liquid "
        "placeholders like <code>{{first_name}}</code> "
        "and <code>{{order.number}}</code> work in "
        "most helpdesk tools.</p>"
        + "".join(sections) +
        "</section>"
    )


def apply_support_responses(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(spec, dict) or not spec.get(
        "responses",
    ):
        return {
            "applied": False,
            "handle": _RESPONSE_PAGE_HANDLE,
            "error": "no_responses_spec",
        }

    body_html = render_responses_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _RESPONSE_PAGE_HANDLE,
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
            "handle": _RESPONSE_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _RESPONSE_PAGE_TITLE,
        "handle": _RESPONSE_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "support_response_templates router.execute "
            "raised: %s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _RESPONSE_PAGE_HANDLE,
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
            "handle": _RESPONSE_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _RESPONSE_PAGE_HANDLE,
        "error": str(error or "rejected"),
    }


# ── Helpers ──────────────────────────────────────────────────


def _record(
    *,
    success: bool,
    store_id: str | None,
    error: str | None,
    spec: dict[str, Any],
) -> None:
    responses = spec.get("responses") or []
    params: dict[str, Any] = {
        "handle": _RESPONSE_PAGE_HANDLE,
        "response_count": len(responses),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_support_responses",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _RESPONSE_PAGE_HANDLE,
                "response_count": len(responses),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "support_response_templates "
            "record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "support_response_templates router import "
            "failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "support_response_templates capability "
            "resolve failed: %s", exc,
        )
        return None
