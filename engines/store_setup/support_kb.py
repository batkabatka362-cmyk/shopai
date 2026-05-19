"""Niche-aware customer-support knowledge base generator.

The page_generator's FAQ page covers ~5 universal questions
(shipping / returns / tracking / authenticity). Real
customer support takes 10-20 niche-specific questions:

  * Beauty: ingredients, allergies, patch testing, expiry.
  * Fashion: sizing, fit, fabric care, gift returns.
  * Tech: warranty, compatibility, software updates.
  * Pets: ingredient transparency, age-appropriateness.
  * Fitness: sizing for active wear, supplement dosing.
  * Jewelry: metal types, sizing, engraving, resizing.
  * Outdoor: warranty repairs, weather-rating.
  * Baby: safety standards, age-stages.

This module fills that gap. Generates a structured Q&A
knowledge base per niche -- the operator pastes the output
into their helpdesk (Gorgias / Zendesk / Intercom) as canned
responses, OR the autonomous applier persists it as a
``customer-support`` Shopify page (handle ``customer-support``)
via the existing ``SHOPIFY_CREATE_PAGE`` adapter.

Return shape from :func:`generate_support_kb`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "entries": [
            {
                "question": "Are your products vegan?",
                "answer":   "Yes, every product at Acme...",
                "category": "ingredients",
            },
            ...
        ],
    }

Records each push via Pattern Z.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Universal Q&A entries -- apply to every store regardless of
# niche. The niche-specific entries below STACK on top of
# these.
_UNIVERSAL_ENTRIES: list[tuple[str, str, str]] = [
    (
        "How long until my order ships?",
        "Orders typically ship within 1-3 business days of "
        "payment. You'll get a tracking email once your "
        "package leaves the warehouse.",
        "shipping",
    ),
    (
        "Do you ship internationally?",
        "Yes, we ship to most countries. International "
        "delivery takes 7-21 business days; customs delays "
        "may apply.",
        "shipping",
    ),
    (
        "How can I track my order?",
        "Once shipped, you'll get a tracking link by email. "
        "If you can't find it, check your spam folder before "
        "reaching out -- mailbox filters catch shipping "
        "notifications surprisingly often.",
        "shipping",
    ),
    (
        "What's your return policy?",
        "Most items are returnable in original condition. "
        "See our refund policy page for the full terms by "
        "niche (some items, like perishables, are final "
        "sale).",
        "returns",
    ),
    (
        "How long do refunds take?",
        "Approved refunds are processed within 5-10 "
        "business days to the original payment method.",
        "returns",
    ),
    (
        "I haven't received my order confirmation -- now what?",
        "Check your spam folder first. If it's not there, "
        "reach out with the email + name you used at "
        "checkout and we'll look up the order.",
        "orders",
    ),
    (
        "Can I change or cancel my order?",
        "If the order hasn't shipped yet, yes -- contact "
        "us as fast as possible. Once it's left the "
        "warehouse, we can't recall it.",
        "orders",
    ),
]


# Niche-specific Q&A entries. Each STACKS on top of the
# universal set, so beauty stores get the 7 universals +
# these category-specific ones.
_NICHE_ENTRIES: dict[
    str, list[tuple[str, str, str]],
] = {
    "beauty": [
        (
            "Are your products vegan / cruelty-free?",
            "Check the product page -- vegan and "
            "cruelty-free items are tagged explicitly. "
            "Anything without a tag is not guaranteed "
            "vegan; reach out before ordering if it's "
            "essential.",
            "ingredients",
        ),
        (
            "I have sensitive skin. How do I patch test?",
            "Apply a pea-sized amount to the inside of your "
            "wrist or behind your ear. Wait 24 hours. No "
            "reaction = safe to use as directed.",
            "usage",
        ),
        (
            "What's the shelf life after opening?",
            "Most products have a Period After Opening (PAO) "
            "symbol on the packaging -- usually 6-12 months "
            "for skincare, 12-24 for makeup.",
            "shelf-life",
        ),
        (
            "I'm allergic to X. Can you confirm it's not in "
            "this product?",
            "Yes -- email us the product + allergen and we'll "
            "check the full ingredient list before you "
            "order.",
            "ingredients",
        ),
    ],
    "fashion": [
        (
            "How do I know my size?",
            "Every product page has a size guide with "
            "garment measurements (cm + inches). When in "
            "doubt, size up -- our return policy covers "
            "fit issues.",
            "sizing",
        ),
        (
            "How should I care for this fabric?",
            "Care instructions are on the inner label of "
            "every garment. Hand wash cold preserves color "
            "and shape best for most items.",
            "care",
        ),
        (
            "Can I return a gift without a receipt?",
            "Yes -- the gift giver can email us the order "
            "number, OR we can look up the order by their "
            "name + email. Refund goes back to the original "
            "payment method.",
            "returns",
        ),
        (
            "Do you offer alterations?",
            "We don't offer in-house alterations, but our "
            "size guides are accurate -- order true to size "
            "and most pieces fit without tailoring.",
            "sizing",
        ),
    ],
    "tech": [
        (
            "What's the warranty?",
            "Most products carry a 1-year manufacturer "
            "warranty against defects. Email us with your "
            "order number to start a warranty claim.",
            "warranty",
        ),
        (
            "Is this compatible with [my device]?",
            "Check the compatibility section on the product "
            "page. If it's not listed and you're unsure, "
            "email us the exact model number -- we'll "
            "confirm before you order.",
            "compatibility",
        ),
        (
            "How do I get software updates?",
            "Updates push automatically to connected "
            "devices. Manual update instructions are in the "
            "product's quickstart guide -- usually on the "
            "Connect step.",
            "software",
        ),
        (
            "What if it stops working after the warranty?",
            "Email us anyway. We often help out-of-warranty "
            "customers at-cost when repairs are feasible.",
            "warranty",
        ),
    ],
    "home": [
        (
            "How do I care for this material?",
            "Care instructions for natural materials (wood, "
            "linen, ceramic) are on the product page. Avoid "
            "direct sun + extreme moisture for textiles + "
            "wood.",
            "care",
        ),
        (
            "Is assembly required?",
            "Check the product description -- if assembly is "
            "needed, the tools list and a full instructions "
            "PDF are linked from the page.",
            "assembly",
        ),
        (
            "Do you offer trade / interior-designer pricing?",
            "Yes -- email us a brief on your project and "
            "we'll send the trade pricing sheet.",
            "trade",
        ),
    ],
    "food": [
        (
            "What's the expiry date?",
            "Each product page lists a typical shelf life "
            "from production. Best-before dates are printed "
            "on the packaging when you receive it.",
            "shelf-life",
        ),
        (
            "Do you ship refrigerated / frozen?",
            "Where temperature control matters, we ship "
            "with insulated packaging + ice packs. Order "
            "by Wednesday for delivery before the weekend "
            "to avoid sitting in transit over Saturday + "
            "Sunday.",
            "shipping",
        ),
        (
            "Is this gluten-free / vegan / kosher / halal?",
            "Dietary certifications are tagged on the "
            "product page. Anything without an explicit tag "
            "is not certified -- contact us for ingredient "
            "lists before ordering.",
            "diet",
        ),
        (
            "I received a damaged package. What now?",
            "Email us within 48 hours with photos. "
            "Damaged-in-transit items get replaced at no "
            "charge.",
            "damaged",
        ),
    ],
    "pets": [
        (
            "Is this safe for puppies / kittens?",
            "Age-stage labels are on every product page. "
            "Foods labelled \"all life stages\" are safe; "
            "supplements for adults are clearly marked.",
            "safety",
        ),
        (
            "What's in this food / treat?",
            "Full ingredient list + guaranteed analysis on "
            "every product page. We don't carry products "
            "with vague filler labels.",
            "ingredients",
        ),
        (
            "My pet has an allergy. Can you recommend?",
            "Email us the allergen + your pet's species + "
            "weight. We'll send 3-5 options we'd feed our "
            "own pets in the same situation.",
            "recommendations",
        ),
        (
            "What if my pet doesn't like it?",
            "We offer a satisfaction guarantee -- email us "
            "and we'll either swap or refund. Food + treats "
            "don't have to come back; donate them to a "
            "local shelter.",
            "returns",
        ),
    ],
    "fitness": [
        (
            "How do I size active wear?",
            "Size guides on every product page. Compression "
            "fits run 1 size smaller than relaxed fits -- "
            "size up if you're between sizes for "
            "compression gear.",
            "sizing",
        ),
        (
            "Are your supplements third-party tested?",
            "Yes -- tested batches are noted on the product "
            "page with the testing lab name. Untested "
            "items aren't on our site.",
            "testing",
        ),
        (
            "What's the dosing protocol?",
            "Suggested use is on every supplement page. "
            "Consult your physician before starting anything "
            "new, especially if you're on medication.",
            "dosing",
        ),
        (
            "Can I use the gear for outdoor / cold-weather "
            "training?",
            "Each apparel item has a recommended temperature "
            "range. Layering pieces stack for cold-weather "
            "use.",
            "usage",
        ),
    ],
    "jewelry": [
        (
            "What metals do you use?",
            "Every piece has a materials list on the product "
            "page. We carry solid sterling silver, 14k + "
            "18k gold, and titanium -- no plated or "
            "filled pieces unless explicitly labelled.",
            "materials",
        ),
        (
            "Will this turn my skin green?",
            "Solid metals (silver, gold, titanium) don't "
            "discolour skin. Plated pieces are labelled as "
            "such -- they may discolour over time depending "
            "on body chemistry.",
            "materials",
        ),
        (
            "Can I get a ring resized?",
            "Most rings can be resized once after purchase. "
            "Email us the order number + desired size and "
            "we'll arrange the resize at cost.",
            "sizing",
        ),
        (
            "Do you offer engraving?",
            "Engraving is available on pieces tagged "
            "\"engraveable\" -- limit 25 characters. Add "
            "engraving text in the cart note before "
            "checkout.",
            "customization",
        ),
        (
            "How do I care for this piece?",
            "Store away from other jewelry to prevent "
            "scratches. Clean with a soft cloth; for silver, "
            "an anti-tarnish bag between wears keeps "
            "polish.",
            "care",
        ),
    ],
    "outdoor": [
        (
            "Is this weatherproof?",
            "Weather ratings (waterproof / water-resistant / "
            "wind-blocking) are on every product page. "
            "Read the spec sheet for the exact rating "
            "(e.g. 10000mm waterhead).",
            "weather",
        ),
        (
            "What's the temperature rating?",
            "Sleeping bags + insulation pieces carry "
            "temperature ratings (comfort / lower limit) on "
            "the product page.",
            "weather",
        ),
        (
            "Do you offer warranty repairs?",
            "Yes -- we partner with the manufacturer for "
            "warranty repairs on most brands. Email us with "
            "the issue + photos and we'll route it.",
            "warranty",
        ),
        (
            "Can I rent gear instead of buying?",
            "We don't rent, but several rental partners are "
            "linked from the product page where available.",
            "rental",
        ),
    ],
    "baby": [
        (
            "Are these products certified safe?",
            "All products meet CPSIA + EN-71 safety "
            "standards. Specific certifications "
            "(OEKO-TEX, GOTS, BPA-free, etc.) are listed on "
            "each product page.",
            "safety",
        ),
        (
            "What age is this for?",
            "Age stages are on every product page "
            "(0-3mo / 3-6mo / 6-12mo / 12-24mo for "
            "clothing; comparable stages for gear).",
            "age",
        ),
        (
            "Is the fabric organic?",
            "Organic-cotton items are tagged + carry the "
            "GOTS or OEKO-TEX certification on the product "
            "page.",
            "materials",
        ),
        (
            "I'm a first-time parent. What do I actually "
            "need?",
            "Email us your baby's age + due date -- we'll "
            "send a niche-tested starter list from real "
            "parents.",
            "recommendations",
        ),
    ],
    "general": [
        (
            "How do I contact support?",
            "Email us directly or use the contact form. We "
            "respond to most inquiries within 24 business "
            "hours.",
            "contact",
        ),
        (
            "What payment methods do you accept?",
            "All major credit cards, plus Shop Pay, Apple "
            "Pay, Google Pay where supported.",
            "payment",
        ),
    ],
}


_KB_PAGE_TITLE: str = "Customer Support"
_KB_PAGE_HANDLE: str = "customer-support"


def generate_support_kb(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build a structured customer-support knowledge base.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general
            entries (just the universal + general subset).

    Returns:
        ``{store_name, niche, entries: list[Q&A dict]}``.
        Entries are universal-first then niche-specific.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    niche_entries = _NICHE_ENTRIES.get(
        niche_n, _NICHE_ENTRIES["general"],
    )

    entries: list[dict[str, str]] = []
    for q, a, cat in _UNIVERSAL_ENTRIES:
        entries.append({
            "question": q,
            "answer": a,
            "category": cat,
        })
    for q, a, cat in niche_entries:
        entries.append({
            "question": q,
            "answer": a,
            "category": cat,
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "entries": entries,
    }


def render_kb_html(spec: dict[str, Any]) -> str:
    """Render the support KB as a Shopify page body.

    Groups questions by category for readable browsing. Each
    Q is an <h3>; each A is a <p>.
    """
    if not isinstance(spec, dict) or not spec.get("entries"):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    entries = spec.get("entries") or []

    # Group by category in entry-order so the universal
    # categories come first.
    grouped: dict[str, list[dict[str, str]]] = {}
    cat_order: list[str] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        cat = (e.get("category") or "general").lower()
        if cat not in grouped:
            cat_order.append(cat)
            grouped[cat] = []
        grouped[cat].append(e)

    sections: list[str] = []
    for cat in cat_order:
        cat_label = cat.replace("-", " ").title()
        body: list[str] = [
            f"<h2>{html.escape(cat_label)}</h2>",
        ]
        for e in grouped[cat]:
            q = html.escape(e.get("question", "") or "")
            a = html.escape(e.get("answer", "") or "")
            body.append(f"<h3>{q}</h3><p>{a}</p>")
        sections.append("".join(body))

    return (
        "<section class=\"support-kb\">"
        f"<h1>{name} -- Customer Support</h1>"
        f"<p>If you can't find what you need below, contact "
        f"us via the form on the Contact page.</p>"
        + "".join(sections) +
        "</section>"
    )


def apply_support_kb(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist the KB as a Shopify page with handle
    ``customer-support`` via the existing
    ``SHOPIFY_CREATE_PAGE`` adapter.

    Args:
        spec: Dict from :func:`generate_support_kb`.
        store_id: Optional per-store Pattern Z scope.

    Returns:
        ``{applied, handle, error}``.
    """
    if not isinstance(spec, dict) or not spec.get("entries"):
        return {
            "applied": False,
            "handle": _KB_PAGE_HANDLE,
            "error": "no_kb_spec",
        }

    body_html = render_kb_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _KB_PAGE_HANDLE,
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
            "handle": _KB_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _KB_PAGE_TITLE,
        "handle": _KB_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "support_kb router.execute raised: %s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _KB_PAGE_HANDLE,
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
            "handle": _KB_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _KB_PAGE_HANDLE,
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
        "handle": _KB_PAGE_HANDLE,
        "entry_count": len(spec.get("entries") or []),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_support_kb",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _KB_PAGE_HANDLE,
                "entry_count": len(
                    spec.get("entries") or [],
                ),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "support_kb record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "support_kb router import failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "support_kb capability resolve failed: %s", exc,
        )
        return None
