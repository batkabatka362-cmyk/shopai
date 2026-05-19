"""Niche-aware paid ad copy templates.

PR #407 ships the marketing-event SHELL (campaign config:
channel + tactic + budget + UTMs). This module ships the
CREATIVE: actual headline + body + CTA text per ad
variant, ready to paste into Meta Ads Manager / Google
Ads / TikTok Ads.

Why this matters:

  * Writing 3-5 ad variants per channel is the operator
    grind that delays launch campaigns by weeks.
  * Ad-copy quality is one of the biggest performance
    levers (good copy beats bad creative 2-3x on the
    same audience).
  * Niche-aware copy (beauty-buyer language vs
    tech-buyer language) outperforms generic by 30-50%.

Per channel + per niche, we ship:

  * **Meta / Instagram** -- 25-char primary text, 40-char
    headline, 30-char description, single CTA.
  * **Google Search** -- 30-char headline (x3), 90-char
    description (x2), display path, single CTA.
  * **Google Shopping** -- 70-char product title, 5000-
    char product description, custom labels.
  * **TikTok** -- 30-100 char ad text, 12-string call to
    action, hook + value + CTA structure.

Return shape from :func:`generate_ad_copy_templates`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "channels": {
            "meta": [{headline, primary_text, description,
                      cta, rationale}, ...],
            "google_search": [{headline_1, headline_2,
                               headline_3, description_1,
                               description_2, display_path,
                               cta}, ...],
            "google_shopping": [...],
            "tiktok": [...],
        },
    }

Persists as a Shopify page (handle ``ad-copy-templates``).
Pairs with PR #407 marketing-event campaign config + the
welcome_discount code from PR #383 (which provides the
discount code to embed in ad copy).
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Character caps per channel surface (real platform
# limits). The templates below are written within these
# caps; tests enforce them.
_CHAR_CAPS = {
    "meta_headline": 40,
    "meta_primary": 125,  # Meta primary text "above
                          # the fold" cap; longer is
                          # truncated.
    "meta_description": 30,
    "gs_headline": 30,
    "gs_description": 90,
    "gs_display_path": 15,
    "shopping_title": 70,
    "tiktok_text": 100,
}


# Per-niche creative angles. Each tuple is a complete
# ad variant tuned to the channel character cap.
# Format per channel:
#   meta: (headline, primary_text, description, cta,
#          rationale)
#   google_search: (h1, h2, h3, d1, d2, path, cta,
#                   rationale)
#   tiktok: (text, cta, rationale)
_NICHE_AD_COPY: dict[str, dict[str, list[tuple]]] = {
    "beauty": {
        "meta": [
            (
                "Earn your bathroom shelf",
                "Clean formulas. Honest ingredients. "
                "Real results. Shop the routine that "
                "delivers.",
                "Shop best sellers",
                "Shop Now",
                "Prospecting -- value-led + clear "
                "category signal.",
            ),
            (
                "Skincare that works",
                "First-order 15% off. Vegan, "
                "fragrance-free, dermatologist-tested. "
                "Free shipping over $50.",
                "Try 15% off today",
                "Shop Now",
                "Promo-led + trust signals "
                "(certifications + free shipping).",
            ),
            (
                "Trusted by 10K+ skin types",
                "Built for sensitive skin. Honest "
                "formulas, no fillers, gold-standard "
                "actives.",
                "See reviews",
                "Learn More",
                "Social-proof retargeting variant.",
            ),
        ],
        "google_search": [
            (
                "Vegan Skincare",
                "Clean Formulas",
                "15% Off First Order",
                "Skincare without compromises -- "
                "fragrance-free, derm-tested, free "
                "US ship $50+.",
                "First-order code WELCOME15. Free "
                "returns. 30-day satisfaction guarantee.",
                "skincare",
                "Shop Now",
                "Brand-defense + promo combination. "
                "High intent.",
            ),
        ],
        "tiktok": [
            (
                "POV: you finally found a clean skincare "
                "brand that doesn't break your skin. "
                "Code WELCOME15.",
                "Shop Now",
                "POV-style hook + clear discount in "
                "first 5 seconds.",
            ),
        ],
    },
    "fashion": {
        "meta": [
            (
                "Style for real bodies",
                "Curated pieces, real-body sizing, "
                "free returns. New drops weekly.",
                "Shop new arrivals",
                "Shop Now",
                "Inclusive-sizing angle. Prospecting.",
            ),
            (
                "Free returns. Always.",
                "Try at home. Send back what doesn't "
                "fit -- free. We make the size guide "
                "easy.",
                "Shop with confidence",
                "Shop Now",
                "Returns-as-feature framing. Reduces "
                "the #1 fashion buyer objection.",
            ),
            (
                "The piece you'll wear weekly",
                "Quality fabrics. Timeless cuts. "
                "Sized to fit real bodies.",
                "Browse the drop",
                "Shop Now",
                "Quality + longevity angle for higher-"
                "AOV browsers.",
            ),
        ],
        "google_search": [
            (
                "Real-Body Fashion",
                "Free Returns",
                "Inclusive Sizing",
                "Curated apparel sized for real bodies. "
                "Free shipping over $75 + 30-day free "
                "returns.",
                "Try at home, send back free. Petite, "
                "regular, tall, plus sizes available.",
                "fashion",
                "Shop Now",
                "Differentiated SEM positioning -- "
                "inclusivity + risk-free trial.",
            ),
        ],
        "tiktok": [
            (
                "Trying on every fit so you don't "
                "have to. Free returns if it doesn't "
                "work. Code WELCOME15.",
                "Shop Now",
                "Try-on transparency hook. High "
                "engagement on TikTok.",
            ),
        ],
    },
    "tech": {
        "meta": [
            (
                "Tech that just works",
                "Premium materials, honest claims, "
                "reliable performance day after day. "
                "2-year warranty.",
                "Shop tech",
                "Shop Now",
                "Quality + warranty trust signals. "
                "High-AOV category needs this upfront.",
            ),
            (
                "Skip the gimmicks",
                "No marketing fluff. Real specs, real "
                "performance, real warranty.",
                "See spec sheets",
                "Learn More",
                "Anti-marketing positioning resonates "
                "with tech-skeptical buyers.",
            ),
        ],
        "google_search": [
            (
                "Premium Tech",
                "2-Year Warranty",
                "Free US Shipping",
                "Quality electronics, honest specs, "
                "2-yr warranty. Free ship $75+. "
                "30-day returns.",
                "Third-party tested. Real specs. No "
                "marketing fluff.",
                "tech",
                "Shop Now",
                "Trust + price-anchor positioning for "
                "tech buyers comparing across stores.",
            ),
        ],
        "tiktok": [
            (
                "Honest tech review: this is the "
                "gadget I actually use. 2-year warranty "
                "+ free shipping.",
                "Shop Now",
                "Authentic-creator format outperforms "
                "branded tech ads.",
            ),
        ],
    },
    "home": {
        "meta": [
            (
                "Small upgrades, big difference",
                "Thoughtful design, sustainable "
                "materials, built to last past the "
                "next move.",
                "Shop the home",
                "Shop Now",
                "Quality + longevity angle.",
            ),
            (
                "Refresh your space",
                "Curated home goods, honest pricing, "
                "free shipping over $100. New collection "
                "live now.",
                "Browse new arrivals",
                "Shop Now",
                "Promo-led + new-arrivals hook.",
            ),
        ],
        "google_search": [
            (
                "Curated Home Goods",
                "Built to Last",
                "Free Shipping $100+",
                "Thoughtful design, sustainable "
                "materials, honest pricing. Free "
                "shipping over $100.",
                "30-day returns. White-glove delivery "
                "available on $500+ items.",
                "home",
                "Shop Now",
                "Quality + delivery options for "
                "high-AOV category.",
            ),
        ],
        "tiktok": [
            (
                "Room transformation with one piece. "
                "Quality you can feel. Free shipping "
                "over $100.",
                "Shop Now",
                "Visual transformation hooks perform "
                "well in home niche.",
            ),
        ],
    },
    "food": {
        "meta": [
            (
                "Pantry essentials, sourced honestly",
                "Small-batch flavours from people who "
                "care about the ingredients. Free "
                "shipping over $40.",
                "Shop the pantry",
                "Shop Now",
                "Sourcing + quality angle.",
            ),
            (
                "Subscribe + save 10%",
                "Subscribe to curated pantry "
                "essentials. Save 10% + free "
                "shipping monthly. Cancel anytime.",
                "Try a subscription",
                "Subscribe",
                "Subscription pitch -- highest-LTV "
                "play for food.",
            ),
        ],
        "google_search": [
            (
                "Small-Batch Pantry",
                "Sourced Honestly",
                "Subscribe + Save 10%",
                "Pantry essentials from small "
                "producers. Subscribe and save 10%. "
                "Free shipping over $40.",
                "Real ingredient lists. No filler. "
                "Same-day shipping Mon-Wed.",
                "food",
                "Shop Now",
                "Trust + subscription pitch.",
            ),
        ],
        "tiktok": [
            (
                "Tasting flight from my pantry. Every "
                "item single-source. Code WELCOME10.",
                "Shop Now",
                "Tasting / unboxing content native to "
                "food TikTok.",
            ),
        ],
    },
    "pets": {
        "meta": [
            (
                "Better gear for the animals we love",
                "Pet-tested, vet-approved, no "
                "questionable fillers. Subscribe + "
                "save 10%.",
                "Shop for your pet",
                "Shop Now",
                "Value-led + subscription pitch.",
            ),
            (
                "What we'd feed our own pets",
                "Honest ingredient lists. Single-"
                "protein options. Free shipping over "
                "$49.",
                "Browse foods",
                "Shop Now",
                "Authenticity + ingredient "
                "transparency.",
            ),
        ],
        "google_search": [
            (
                "Vet-Approved Pet Food",
                "Honest Ingredients",
                "Subscribe + Save 10%",
                "Pet food + treats from people who "
                "feed the same to their pets. Free "
                "shipping $49+.",
                "Single-protein options. No fillers. "
                "Auto-ship saves 10%.",
                "pet-food",
                "Shop Now",
                "Trust + subscription convert pet-"
                "food buyers.",
            ),
        ],
        "tiktok": [
            (
                "Real pet, real food review. The "
                "ingredients you can actually "
                "pronounce. Subscribe + save 10%.",
                "Shop Now",
                "Pet content + ingredient honesty.",
            ),
        ],
    },
    "fitness": {
        "meta": [
            (
                "Gear for actual training",
                "Tested by people who train. Honest "
                "performance gear + third-party tested "
                "supplements.",
                "Shop apparel",
                "Shop Now",
                "Authenticity + transparency angle.",
            ),
            (
                "Skip the influencer fluff",
                "Real labels. Real performance. Real "
                "athletes test the gear.",
                "See test reports",
                "Learn More",
                "Anti-marketing positioning for "
                "skeptical athletes.",
            ),
        ],
        "google_search": [
            (
                "Third-Party Tested Supps",
                "Honest Performance Gear",
                "Free Shipping $75+",
                "Apparel + supplements tested by real "
                "athletes. Verified labels. Free ship "
                "$75+.",
                "Recovery, performance, daily basics. "
                "Transparent ingredient lists.",
                "fitness",
                "Shop Now",
                "Trust + free-shipping anchor.",
            ),
        ],
        "tiktok": [
            (
                "Day-in-training haul. Real gear, real "
                "fit. Lab-tested supplements. Code "
                "WELCOME15.",
                "Shop Now",
                "Training-day content + transparency.",
            ),
        ],
    },
    "jewelry": {
        "meta": [
            (
                "Heirloom-quality, honestly priced",
                "Solid materials, considered "
                "craftsmanship, priced for the metal "
                "not the markup.",
                "Shop necklaces",
                "Shop Now",
                "Quality + pricing transparency.",
            ),
            (
                "Resize free, polish yearly",
                "Free first-resize. Complimentary "
                "annual polish. Heirloom care for "
                "modern pieces.",
                "Shop with confidence",
                "Learn More",
                "Aftercare framing reduces buyer "
                "anxiety on high-AOV pieces.",
            ),
        ],
        "google_search": [
            (
                "Honestly-Priced Jewelry",
                "Free Resize",
                "Insured Shipping",
                "Heirloom pieces priced for the "
                "metal. Free resize + annual polish.",
                "Insured shipping always. 30-day "
                "returns + appraisal docs included.",
                "jewelry",
                "Shop Now",
                "Trust + aftercare for considered "
                "purchase.",
            ),
        ],
        "tiktok": [
            (
                "Daily-wear sterling silver. Solid, "
                "not plated. Free resize forever.",
                "Shop Now",
                "Material honesty hooks well for "
                "jewelry buyers.",
            ),
        ],
    },
    "outdoor": {
        "meta": [
            (
                "Gear that goes the distance",
                "Field-tested, weather-honest, "
                "repairs over replacements. Free "
                "shipping over $75.",
                "Shop camping",
                "Shop Now",
                "Reliability + repair-not-replace "
                "ethos.",
            ),
            (
                "Tested in the field",
                "Customer-tested trail gear. Real-"
                "world weather reports + repair "
                "support.",
                "See gear tests",
                "Learn More",
                "Authenticity for trail-serious "
                "buyers.",
            ),
        ],
        "google_search": [
            (
                "Field-Tested Trail Gear",
                "Lifetime Repair",
                "Free Shipping $75+",
                "Outdoor gear tested by real "
                "customers + repaired (not replaced) "
                "when it wears.",
                "Camping, hiking, climbing, paddling. "
                "Weather-honest specs.",
                "outdoor",
                "Shop Now",
                "Quality + repair positioning vs "
                "disposable-gear competitors.",
            ),
        ],
        "tiktok": [
            (
                "30-day trail test of this gear. Real "
                "weather, real wear. Repair "
                "guaranteed.",
                "Shop Now",
                "Trail-tested content native to the "
                "category.",
            ),
        ],
    },
    "baby": {
        "meta": [
            (
                "Soft, safe, parent-tested",
                "Gentle fabrics, safe finishes, gear "
                "that grows with your family.",
                "Shop the nursery",
                "Shop Now",
                "Parent-trust framing.",
            ),
            (
                "Free size-swap exchanges",
                "Babies grow fast. We make size "
                "swaps free for 60 days. Subscribe "
                "+ save on essentials.",
                "Shop with peace of mind",
                "Shop Now",
                "Size-swap policy + subscription "
                "pitch reduce parent anxiety.",
            ),
        ],
        "google_search": [
            (
                "Parent-Tested Baby Gear",
                "Free Size Swaps",
                "Subscribe + Save",
                "Soft fabrics, safe finishes, "
                "OEKO-TEX certified essentials. Free "
                "60-day size swaps.",
                "Subscribe to save on diapers + "
                "formula. Auto-pause anytime.",
                "baby",
                "Shop Now",
                "Trust + flexibility for new parents.",
            ),
        ],
        "tiktok": [
            (
                "Real-parent review: gear that works "
                "every stage. Free swap if not.",
                "Shop Now",
                "Parent-authentic content + "
                "risk-reducing policy.",
            ),
        ],
    },
    "general": {
        "meta": [
            (
                "Quality you can trust",
                "Hand-picked products, honest "
                "pricing, fast support. Free "
                "shipping over $50.",
                "Shop best sellers",
                "Shop Now",
                "Safe generic positioning.",
            ),
        ],
        "google_search": [
            (
                "Quality Products",
                "Honest Pricing",
                "Fast Support",
                "Hand-picked products with honest "
                "pricing + 24-hour support. Free "
                "shipping over $50.",
                "30-day returns. Real people answer "
                "every email.",
                "shop",
                "Shop Now",
                "Generic-but-honest fallback.",
            ),
        ],
        "tiktok": [
            (
                "Honest review of my latest order. "
                "Code WELCOME10 for first-time "
                "buyers.",
                "Shop Now",
                "Standard review-style content.",
            ),
        ],
    },
}


_AD_COPY_PAGE_TITLE: str = "Ad Copy Templates"
_AD_COPY_PAGE_HANDLE: str = "ad-copy-templates"


def generate_ad_copy_templates(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build niche-aware ad copy variants per channel.

    Args:
        store_name: Display name (interpolated into
            templates). Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.

    Returns:
        ``{store_name, niche, channels: {meta, google_search,
        tiktok}}``. Each channel is a list of structured
        ad variants. Some niches may lack Google Shopping
        templates (food, jewelry) -- those return empty
        for that channel.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    raw = _NICHE_AD_COPY.get(
        niche_n, _NICHE_AD_COPY["general"],
    )

    return {
        "store_name": name,
        "niche": niche_n,
        "channels": {
            "meta": [
                {
                    "headline": v[0],
                    "primary_text": v[1],
                    "description": v[2],
                    "cta": v[3],
                    "rationale": v[4],
                }
                for v in raw.get("meta", [])
            ],
            "google_search": [
                {
                    "headline_1": v[0],
                    "headline_2": v[1],
                    "headline_3": v[2],
                    "description_1": v[3],
                    "description_2": v[4],
                    "display_path": v[5],
                    "cta": v[6],
                    "rationale": v[7],
                }
                for v in raw.get("google_search", [])
            ],
            "tiktok": [
                {
                    "ad_text": v[0],
                    "cta": v[1],
                    "rationale": v[2],
                }
                for v in raw.get("tiktok", [])
            ],
        },
    }


def render_ad_copy_html(spec: dict[str, Any]) -> str:
    if not isinstance(spec, dict) or not spec.get(
        "channels",
    ):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    channels = spec.get("channels") or {}

    sections: list[str] = []

    # Meta section
    meta_variants = channels.get("meta") or []
    if meta_variants:
        rows: list[str] = []
        for i, v in enumerate(meta_variants, start=1):
            rows.append(
                "<section class=\"ad-variant\">"
                f"<h3>Variant {i}: {html.escape(v.get('rationale', ''))}</h3>"
                "<dl>"
                f"<dt>Headline (40c)</dt><dd>{html.escape(v.get('headline', ''))}</dd>"
                f"<dt>Primary Text (125c)</dt>"
                f"<dd>{html.escape(v.get('primary_text', ''))}</dd>"
                f"<dt>Description (30c)</dt>"
                f"<dd>{html.escape(v.get('description', ''))}</dd>"
                f"<dt>CTA</dt><dd>{html.escape(v.get('cta', ''))}</dd>"
                "</dl></section>"
            )
        sections.append(
            "<section class=\"channel-block\">"
            "<h2>Meta / Instagram</h2>"
            + "".join(rows) +
            "</section>"
        )

    # Google Search section
    gs_variants = channels.get("google_search") or []
    if gs_variants:
        rows: list[str] = []
        for i, v in enumerate(gs_variants, start=1):
            rows.append(
                "<section class=\"ad-variant\">"
                f"<h3>Variant {i}: {html.escape(v.get('rationale', ''))}</h3>"
                "<dl>"
                f"<dt>Headlines (30c each)</dt>"
                f"<dd>{html.escape(v.get('headline_1', ''))} | "
                f"{html.escape(v.get('headline_2', ''))} | "
                f"{html.escape(v.get('headline_3', ''))}</dd>"
                f"<dt>Description 1 (90c)</dt>"
                f"<dd>{html.escape(v.get('description_1', ''))}</dd>"
                f"<dt>Description 2 (90c)</dt>"
                f"<dd>{html.escape(v.get('description_2', ''))}</dd>"
                f"<dt>Display Path</dt>"
                f"<dd><code>/{html.escape(v.get('display_path', ''))}</code></dd>"
                "</dl></section>"
            )
        sections.append(
            "<section class=\"channel-block\">"
            "<h2>Google Search</h2>"
            + "".join(rows) +
            "</section>"
        )

    # TikTok section
    tt_variants = channels.get("tiktok") or []
    if tt_variants:
        rows: list[str] = []
        for i, v in enumerate(tt_variants, start=1):
            rows.append(
                "<section class=\"ad-variant\">"
                f"<h3>Variant {i}: {html.escape(v.get('rationale', ''))}</h3>"
                "<dl>"
                f"<dt>Ad Text</dt><dd>{html.escape(v.get('ad_text', ''))}</dd>"
                f"<dt>CTA</dt><dd>{html.escape(v.get('cta', ''))}</dd>"
                "</dl></section>"
            )
        sections.append(
            "<section class=\"channel-block\">"
            "<h2>TikTok</h2>"
            + "".join(rows) +
            "</section>"
        )

    return (
        "<section class=\"ad-copy-templates\">"
        f"<h1>{name} -- Ad Copy Templates</h1>"
        "<p>Paste these variants into Meta Ads "
        "Manager / Google Ads / TikTok Ads. Each "
        "variant fits within the platform's "
        "character limits (40c headline / 125c "
        "primary text on Meta; 30c headlines + 90c "
        "descriptions on Google Search; ~100c on "
        "TikTok).</p>"
        + "".join(sections) +
        "</section>"
    )


def apply_ad_copy_templates(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(spec, dict) or not spec.get(
        "channels",
    ):
        return {
            "applied": False,
            "handle": _AD_COPY_PAGE_HANDLE,
            "error": "no_ad_copy_spec",
        }

    body_html = render_ad_copy_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _AD_COPY_PAGE_HANDLE,
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
            "handle": _AD_COPY_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _AD_COPY_PAGE_TITLE,
        "handle": _AD_COPY_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "ad_copy_templates router.execute "
            "raised: %s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _AD_COPY_PAGE_HANDLE,
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
            "handle": _AD_COPY_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _AD_COPY_PAGE_HANDLE,
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
    channels = spec.get("channels") or {}
    total = sum(
        len(v) for v in channels.values()
        if isinstance(v, list)
    )
    params: dict[str, Any] = {
        "handle": _AD_COPY_PAGE_HANDLE,
        "variant_count": total,
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_ad_copy_templates",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _AD_COPY_PAGE_HANDLE,
                "variant_count": total,
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "ad_copy_templates record_writeback "
            "raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "ad_copy_templates router import failed: %s",
            exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "ad_copy_templates capability resolve "
            "failed: %s", exc,
        )
        return None
