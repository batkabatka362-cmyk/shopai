"""Niche-aware thank-you card / physical insert content.

The card included in every shipment is the most underused
touchpoint in ecommerce. It's:

  * IRL -- read at the moment of unboxing (peak
    customer happiness).
  * Cheap -- ~$0.10-0.30 per card at volume.
  * High-impact -- a clear ask drives 3-5x more
    reviews + social shares than email.

Most stores either skip the card OR print a generic
"Thanks for your order!" with no ask. This module ships
niche-aware card copy with:

  * **Greeting + brand voice** -- personal opening.
  * **Single clear ask** -- review / share / referral
    / subscription pitch (pick ONE based on niche).
  * **Optional discount code** -- next-order nudge.
  * **QR-code target URL** -- where the QR code should
    point (reviews page / Instagram / referral landing).

Each niche has different optimal asks:
  * Beauty / fashion -> photo + review (drives UGC)
  * Food / pets -> subscribe + save (highest LTV)
  * Jewelry -> care guide (premium-experience)
  * Tech -> warranty registration (reduces support)
  * Baby -> age-stage signup (segmentation)
  * Fitness -> referral (athlete networks compound)

Return shape from
:func:`generate_thank_you_card_content`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "card": {
            "greeting": "Hi {{first_name}},",
            "value_statement": "We're thrilled ...",
            "ask_type": "review_with_photo",
            "ask_copy": "Loved it? Snap a photo + ...",
            "qr_target_url": "{{shop.url}}/products/...",
            "discount_code": "THANKS10",
            "discount_pct": 10,
            "signature": "-- The Acme Beauty team",
        },
        "design_notes": "Use brand palette ...",
    }

The output is operator-facing -- the print shop / design
tool ingests the text + design notes. Persists as a
Shopify page so the content lives somewhere reviewable.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Per-niche card tuning:
#   (
#     value_statement,
#     ask_type,
#     ask_copy,
#     qr_target_url_template,
#     design_notes,
#   )
#
# qr_target_url_template uses Liquid-style
# placeholders the print shop / operator replaces.
_NICHE_CARDS: dict[
    str, tuple[str, str, str, str, str],
] = {
    "beauty": (
        "We're thrilled you're starting your routine "
        "with us. Every formula here was picked "
        "because it works -- not because it sells.",
        "review_with_photo",
        "Loved it? Snap a photo + leave a quick "
        "review. Customer routines feature on our "
        "homepage weekly.",
        "{{shop.url}}/pages/reviews",
        "Use the brand palette (warm cream + soft "
        "brown). Card stock: matte 350gsm. Single-"
        "fold tent style works better than flat for "
        "this niche -- stands on the bathroom shelf.",
    ),
    "fashion": (
        "Thanks for ordering. Every piece was sized "
        "+ tested on real bodies -- if the fit isn't "
        "right, free returns cover it.",
        "share_with_tag",
        "Tag us in the fit -- we feature real "
        "customers on Instagram + the homepage "
        "weekly. Use #{{store.handle}}fit.",
        "https://instagram.com/{{store.handle}}",
        "Use brand palette + a fashion editorial "
        "photo on the back. Matte uncoated 300gsm. "
        "Flat postcard style preferred -- looks "
        "intentional in unboxing photos.",
    ),
    "tech": (
        "Thanks for ordering. Spec sheets + "
        "warranty docs are at the URL below -- "
        "register within 30 days to activate the "
        "2-year coverage.",
        "warranty_registration",
        "Scan to register the warranty + access "
        "spec sheets + quickstart guides.",
        "{{shop.url}}/pages/warranty",
        "Clean minimal design -- white + brand "
        "accent color. Single fold. Matte 300gsm. "
        "Avoid feeling 'thank-you-card cute' -- "
        "tech buyers want utility.",
    ),
    "home": (
        "Thanks for finding us. Every piece was "
        "chosen for materials + craft, not "
        "for trends. We hope it earns a place in "
        "your space.",
        "share_in_space",
        "Show us where it landed -- tag us on "
        "Instagram. Featured customer spaces win a "
        "$25 store credit each month.",
        "https://instagram.com/{{store.handle}}",
        "Premium matte cardstock 350gsm. Square "
        "format works well for home niche. Lifestyle "
        "photo on the back.",
    ),
    "food": (
        "Thanks for finding us. Every item in this "
        "box was sourced from someone who actually "
        "cares about it -- recipes + sourcing "
        "stories at the URL below.",
        "subscribe_and_save",
        "Try the subscription -- subscribe + save "
        "10% on recurring shipments. Scan to set up.",
        "{{shop.url}}/pages/subscriptions",
        "Recipe-style design -- food photo + serif "
        "headline. Heavy uncoated stock 350gsm. "
        "Folded card with recipe on the inside flap "
        "is high-touch.",
    ),
    "pets": (
        "Thanks for trusting us with your pet's "
        "treats / food / gear. We feed the same to "
        "our own pets -- if it doesn't work for "
        "yours, swap or refund (no need to return).",
        "subscribe_and_save",
        "Auto-ship saves 10% + free shipping on "
        "every order. Scan to set up + never "
        "run out.",
        "{{shop.url}}/pages/autoship",
        "Pet illustration / paw print on front. "
        "Warm color palette. Add a sticker -- pet "
        "owners love bonus stickers + so do "
        "kids in the household.",
    ),
    "fitness": (
        "Thanks for ordering. Every supplement is "
        "third-party tested + every apparel piece "
        "is tested by athletes who actually train.",
        "referral",
        "Share with a training partner -- they get "
        "15% off their first order + you get $20 "
        "credit when they buy.",
        "{{shop.url}}/pages/referral",
        "Bold typography + brand color accent. "
        "Matte 300gsm. Athletic / motion photo on "
        "back. Resist over-design -- athletes "
        "tolerate minimalism better than "
        "decoration.",
    ),
    "jewelry": (
        "Thank you for choosing a piece that's "
        "made to be worn daily. We've included a "
        "care guide -- a quick read keeps the "
        "piece looking new for years.",
        "care_guide",
        "Scan to read the care guide for your "
        "specific metal + stone. Free first-resize "
        "+ annual polish included.",
        "{{shop.url}}/pages/care-guide",
        "Premium feel -- gold foil accent on heavy "
        "cardstock 400gsm. Single fold. Brand logo "
        "embossed if budget allows. Match the "
        "jewelry-box aesthetic.",
    ),
    "outdoor": (
        "Thanks for ordering. Every piece of gear "
        "was tested in the field -- if it fails on "
        "the trail, we repair it (not replace it). "
        "Trip stories at the URL below.",
        "share_trip_photo",
        "Send us a trip photo with the gear in "
        "action. Real trail shots earn 10% credit "
        "for the next order.",
        "{{shop.url}}/pages/trip-stories",
        "Kraft paper / recycled stock -- matches "
        "outdoor ethos. Topographic line art on "
        "back. Single-fold + waterproof coating "
        "if budget allows.",
    ),
    "baby": (
        "Welcome to {{store.name}}. Every piece "
        "was tested by real parents -- soft "
        "fabrics, safe finishes, gear that grows "
        "with your little one.",
        "age_stage_signup",
        "Tell us your baby's birth date + we'll "
        "send stage-appropriate picks every month. "
        "Scan to sign up.",
        "{{shop.url}}/pages/age-stage",
        "Soft pastel palette + rounded typography. "
        "Matte uncoated 300gsm. Sticker include "
        "(baby-themed) is a high-touch addition.",
    ),
    "general": (
        "Thanks for ordering. We're a small team "
        "and every order matters to us.",
        "review",
        "Leave a review at the URL below -- "
        "customer reviews are how we keep "
        "growing.",
        "{{shop.url}}/pages/reviews",
        "Brand palette + minimalist design. "
        "Matte 300gsm card stock.",
    ),
}


_THANK_YOU_PAGE_TITLE: str = "Thank-You Card Content"
_THANK_YOU_PAGE_HANDLE: str = "thank-you-card-content"


def generate_thank_you_card_content(
    *,
    store_name: str,
    niche: str = "general",
    discount_code: str | None = None,
    discount_pct: int | None = None,
) -> dict[str, Any]:
    """Build niche-aware thank-you card content.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.
        discount_code: Optional next-order discount code
            printed on the card. Pair with welcome_discount
            output or skip to no-code variant.
        discount_pct: Discount percentage. Required if
            ``discount_code`` is set.

    Returns:
        ``{store_name, niche, card, design_notes}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    tuning = _NICHE_CARDS.get(
        niche_n, _NICHE_CARDS["general"],
    )
    (
        value_statement, ask_type, ask_copy,
        qr_target_template, design_notes,
    ) = tuning

    code_clean = (discount_code or "").strip().upper() or None
    pct_clean = (
        int(discount_pct)
        if discount_pct is not None
        and int(discount_pct) > 0
        else None
    )

    card: dict[str, Any] = {
        "greeting": "Hi {{first_name}},",
        "value_statement": value_statement,
        "ask_type": ask_type,
        "ask_copy": ask_copy,
        "qr_target_url": qr_target_template,
        "signature": f"-- The {name} team",
    }

    if code_clean and pct_clean is not None:
        card["discount_code"] = code_clean
        card["discount_pct"] = pct_clean
        card["discount_copy"] = (
            f"Save {pct_clean}% on your next order "
            f"with code {code_clean}. Valid 60 days."
        )
    else:
        card["discount_code"] = None
        card["discount_pct"] = None
        card["discount_copy"] = None

    return {
        "store_name": name,
        "niche": niche_n,
        "card": card,
        "design_notes": design_notes,
    }


def render_card_html(spec: dict[str, Any]) -> str:
    if not isinstance(spec, dict) or not spec.get("card"):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    card = spec.get("card") or {}
    design_notes = html.escape(
        spec.get("design_notes", "") or "",
    )

    discount_block = ""
    if card.get("discount_copy"):
        discount_block = (
            f"<dt>Discount Block</dt>"
            f"<dd>{html.escape(card.get('discount_copy', ''))}</dd>"
        )

    return (
        "<section class=\"thank-you-card\">"
        f"<h1>{name} -- Thank-You Card Content</h1>"
        "<p>Print-ready copy for the physical card "
        "included in every shipment. Send to your "
        "print shop or design tool.</p>"
        "<section class=\"card-copy\">"
        "<h2>Card Copy</h2>"
        "<dl>"
        f"<dt>Greeting</dt>"
        f"<dd>{html.escape(card.get('greeting', ''))}</dd>"
        f"<dt>Value Statement</dt>"
        f"<dd>{html.escape(card.get('value_statement', ''))}</dd>"
        f"<dt>Ask Type</dt>"
        f"<dd><code>{html.escape(card.get('ask_type', ''))}</code></dd>"
        f"<dt>Ask Copy</dt>"
        f"<dd>{html.escape(card.get('ask_copy', ''))}</dd>"
        f"<dt>QR Code Target</dt>"
        f"<dd><code>{html.escape(card.get('qr_target_url', ''))}</code></dd>"
        f"{discount_block}"
        f"<dt>Signature</dt>"
        f"<dd>{html.escape(card.get('signature', ''))}</dd>"
        "</dl></section>"
        "<section class=\"design-notes\">"
        "<h2>Design Notes</h2>"
        f"<p>{design_notes}</p>"
        "</section></section>"
    )


def apply_thank_you_card_content(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(spec, dict) or not spec.get("card"):
        return {
            "applied": False,
            "handle": _THANK_YOU_PAGE_HANDLE,
            "error": "no_thank_you_spec",
        }

    body_html = render_card_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _THANK_YOU_PAGE_HANDLE,
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
            "handle": _THANK_YOU_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _THANK_YOU_PAGE_TITLE,
        "handle": _THANK_YOU_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "thank_you_card router.execute raised: %s",
            exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _THANK_YOU_PAGE_HANDLE,
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
            "handle": _THANK_YOU_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _THANK_YOU_PAGE_HANDLE,
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
    card = spec.get("card") or {}
    params: dict[str, Any] = {
        "handle": _THANK_YOU_PAGE_HANDLE,
        "ask_type": card.get("ask_type"),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_thank_you_card",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _THANK_YOU_PAGE_HANDLE,
                "ask_type": card.get("ask_type"),
                "has_discount": bool(card.get("discount_code")),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "thank_you_card record_writeback raised: %s",
            exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "thank_you_card router import failed: %s",
            exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "thank_you_card capability resolve "
            "failed: %s", exc,
        )
        return None
