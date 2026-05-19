"""Niche-aware marketing event campaign templates.

Shopify's ``MarketingActivity`` API lets stores log paid /
organic marketing campaigns (Meta / TikTok / Google /
email / SEO) so the admin can join attribution back to
orders + revenue. The autonomous merchant needs these
campaigns set up at launch -- otherwise the ROAS engine
(``engines/roas_guardrails``) and the marketing
optimiser have nothing to attribute against.

Default Shopify stores have ZERO marketing activities
configured. Most operators set them up ad-hoc when they
remember.

This module ships **niche-aware launch campaign
templates** -- the 4-6 evergreen campaigns every store
benefits from running, ready to push via
``SHOPIFY_CREATE_MARKETING_ACTIVITY``. Each spec
carries the friendly call shape the existing adapter
expects:

  {
    "title", "channel", "tactic",
    "remote_url",        # dashboard link
    "budget",            # daily / total
    "utm_source", "utm_medium", "utm_campaign",
    "status",            # paused at create (operator
                         # confirms before going live)
  }

Engines + operators consume the spec list and decide
which to actually push. Pattern Z records each event.

Return shape from
:func:`generate_marketing_event_templates`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "campaigns": [
            {name, channel, tactic, status,
             utm_source, utm_medium, utm_campaign,
             budget_daily_usd, rationale,
             when_to_launch},
            ...
        ],
    }
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Universal launch campaigns ──────────────────────────────


# Each tuple: (name, channel, tactic, budget_daily,
# utm_source, utm_medium, utm_campaign, rationale,
# when_to_launch).
_UNIVERSAL_CAMPAIGNS: list[tuple[
    str, str, str, float, str, str, str, str, str,
]] = [
    (
        "Google Brand Search",
        "google_ads", "search", 10.0,
        "google", "cpc", "brand_search",
        "Defend your brand-name searches. Cheap (low "
        "competition on own brand) + critical (someone "
        "typing your store name has the highest intent).",
        "Day 1 of launch -- always-on baseline.",
    ),
    (
        "Meta Prospecting (top-of-funnel)",
        "facebook", "ad", 25.0,
        "facebook", "cpc", "prospecting_tof",
        "Cold-audience prospecting on Meta. Targets "
        "interest-based lookalikes for the niche. "
        "Mid-CPL (~$8-15) but highest cohort scale.",
        "Day 1-7 -- start, then optimise creative weekly.",
    ),
    (
        "Meta Retargeting",
        "facebook", "retargeting", 15.0,
        "facebook", "cpc", "retargeting_btf",
        "Bottom-of-funnel retargeting: site visitors + "
        "cart abandoners. Highest ROAS bucket in most "
        "stores (3-5x prospecting).",
        "Day 7+ -- need website pixel + 30+ pixel "
        "events before targeting works.",
    ),
    (
        "TikTok Spark Ads",
        "tiktok", "ad", 15.0,
        "tiktok", "cpc", "tiktok_spark",
        "Boost organic / UGC content as paid spark ads. "
        "Authentic-creator style outperforms branded "
        "in 70% of consumer niches.",
        "Day 14+ -- once you have 3-5 organic posts "
        "to boost.",
    ),
    (
        "Email -- Welcome series",
        "email", "newsletter", 0.0,
        "klaviyo", "email", "welcome_series",
        "Welcome email -> day-3 nurture -> day-7 "
        "discount. Pairs with `email_content.py` welcome "
        "template + welcome_discount code. Free to run.",
        "Day 1 -- enable in Klaviyo / Shopify Email.",
    ),
]


# ── Niche-specific campaigns ────────────────────────────────


_NICHE_CAMPAIGNS: dict[
    str,
    list[tuple[
        str, str, str, float, str, str, str, str, str,
    ]],
] = {
    "beauty": [
        (
            "Pinterest Visual Search",
            "pinterest", "search", 12.0,
            "pinterest", "cpc", "pinterest_visual",
            "Beauty audiences search visually for "
            "routines + ingredient swaps. Pinterest "
            "ROAS is consistently 2-3x Meta in "
            "skincare / makeup.",
            "Day 7+ -- after you have pin-worthy "
            "creative.",
        ),
        (
            "Influencer Affiliate Program",
            "social", "affiliate", 30.0,
            "influencer", "affiliate", "creator_program",
            "Pay creators % commission per attributed "
            "sale. Beauty has the deepest creator "
            "ecosystem. Aim for 10-15 micro-influencers "
            "before scaling to mid-tier.",
            "Month 2+ -- after first 100 orders / 50 "
            "reviews validate the product line.",
        ),
    ],
    "fashion": [
        (
            "Instagram Shopping Tags",
            "instagram", "post", 5.0,
            "instagram", "social", "shoppable_posts",
            "Tag products in organic posts + Stories. "
            "Free to enable; reach amplifies organic "
            "Instagram audience.",
            "Day 1 -- enable from Shopify Admin -> Sales "
            "Channels -> Facebook.",
        ),
        (
            "Pinterest Style Inspiration",
            "pinterest", "search", 15.0,
            "pinterest", "cpc", "pinterest_style",
            "Fashion buyers save outfit pins to plan "
            "purchases. Pinterest ROAS in apparel "
            "consistently 2-4x cost.",
            "Day 14+ -- after lookbook content is "
            "live.",
        ),
    ],
    "tech": [
        (
            "Google Shopping",
            "google_ads", "display", 30.0,
            "google", "cpc", "shopping_feed",
            "Product-level Shopping ads on Google. "
            "Required for any tech product over $50 "
            "AOV -- ~50% of category search starts "
            "here.",
            "Day 1-3 -- needs the Google Merchant feed "
            "configured first.",
        ),
        (
            "Reddit Niche Subs",
            "reddit", "ad", 10.0,
            "reddit", "cpc", "reddit_targeted",
            "Promoted posts in audio / gaming / "
            "productivity subs. Tech audiences trust "
            "Reddit recommendations more than ads.",
            "Day 30+ -- after community sentiment is "
            "positive.",
        ),
    ],
    "home": [
        (
            "Pinterest Home Inspiration",
            "pinterest", "search", 18.0,
            "pinterest", "cpc", "pinterest_home",
            "Home buyers research for weeks before "
            "purchase. Pinterest is the primary "
            "research surface for home + decor.",
            "Day 1 -- always-on baseline.",
        ),
        (
            "Houzz Marketplace",
            "houzz", "search", 12.0,
            "houzz", "cpc", "houzz_pro",
            "Direct sales channel for trade / "
            "designer buyers. Lower volume, higher "
            "AOV ($300+).",
            "Month 2+ -- after the trade pricing "
            "sheet is ready.",
        ),
    ],
    "food": [
        (
            "Email -- Subscribe & Save Pitch",
            "email", "newsletter", 0.0,
            "klaviyo", "email", "subscribe_save",
            "Triggered after 2nd order: pitch the "
            "subscribe-and-save discount. Highest LTV "
            "driver for food (10x non-subscriber LTV).",
            "Triggered automation: enable Day 1 + fires "
            "per-customer at order 2.",
        ),
        (
            "Local Food Bloggers",
            "social", "affiliate", 20.0,
            "blogger", "affiliate", "food_blogger",
            "Recipe bloggers + Instagram food creators. "
            "Aim for 5-10 local micro-influencers "
            "(2-10k followers) first.",
            "Month 2+ -- after recipe content is on "
            "the blog.",
        ),
    ],
    "pets": [
        (
            "Email -- Auto-Refill Pitch",
            "email", "newsletter", 0.0,
            "klaviyo", "email", "autoship_pitch",
            "Triggered after 2nd order: pitch the "
            "auto-ship subscription for food + treats. "
            "Pet food has highest subscription "
            "attach rate (~40%).",
            "Day 1 enable; fires per-customer at order "
            "2.",
        ),
        (
            "Pet Influencer (Instagram + TikTok)",
            "social", "affiliate", 25.0,
            "pet_creator", "affiliate", "pet_creators",
            "Pet-account creators (Instagram + TikTok). "
            "Highest engagement rate in consumer goods. "
            "Aim for 5-10 micro pet accounts before "
            "scaling.",
            "Month 1 -- pet content is fast to "
            "produce.",
        ),
    ],
    "fitness": [
        (
            "YouTube Pre-Roll",
            "youtube", "ad", 20.0,
            "youtube", "cpv", "youtube_preroll",
            "Pre-roll on workout / cooking / "
            "supplement-review videos. Skippable ads "
            "perform 3x better than display in "
            "fitness.",
            "Day 30+ -- after first creative test on "
            "Meta validates messaging.",
        ),
        (
            "Athlete Affiliate Network",
            "social", "affiliate", 35.0,
            "athlete", "affiliate", "athlete_program",
            "Pro / semi-pro athletes + coaches. "
            "Commission-based ($N per attributed sale) "
            "scales without upfront cost.",
            "Month 2+ -- after first 500 orders + "
            "positive reviews.",
        ),
    ],
    "jewelry": [
        (
            "Google Branded Search (high-intent)",
            "google_ads", "search", 30.0,
            "google", "cpc", "jewelry_branded",
            "Jewelry buyers search with brand + product "
            "names. CPCs are high but CTR + conversion "
            "are 5x display.",
            "Day 1 -- always-on baseline.",
        ),
        (
            "Pinterest Wedding & Bridal",
            "pinterest", "search", 20.0,
            "pinterest", "cpc", "pinterest_bridal",
            "Bridal buyers research for 6+ months on "
            "Pinterest. Long attribution window but "
            "highest LTV in jewelry.",
            "Day 1 -- always-on.",
        ),
        (
            "Editorial Press Outreach",
            "social", "affiliate", 0.0,
            "press", "referral", "editorial_press",
            "PR + earned-media coverage in wedding / "
            "style publications. Free; ROAS measured "
            "by referral traffic.",
            "Quarterly -- coordinate with collection "
            "drops.",
        ),
    ],
    "outdoor": [
        (
            "YouTube Gear Reviews",
            "youtube", "ad", 18.0,
            "youtube", "cpv", "youtube_gear",
            "Pre-roll on gear-review / trail-vlog "
            "channels. Outdoor buyers heavily "
            "research-driven; YouTube is the primary "
            "decision surface.",
            "Day 14+ -- after creative content is "
            "ready.",
        ),
        (
            "Hiking / Climbing Affiliate Network",
            "social", "affiliate", 25.0,
            "outdoor_creator", "affiliate",
            "outdoor_creators",
            "Outdoor athletes + bloggers. Aim for 10-15 "
            "creators across hiking / climbing / "
            "skiing.",
            "Month 1-2 -- align with season start.",
        ),
    ],
    "baby": [
        (
            "Pinterest Parenting Boards",
            "pinterest", "search", 15.0,
            "pinterest", "cpc", "pinterest_parenting",
            "New parents research for months before + "
            "after baby arrives. Pinterest is the "
            "primary planning surface.",
            "Day 1 -- always-on.",
        ),
        (
            "Email -- Age-Stage Drip Campaign",
            "email", "newsletter", 0.0,
            "klaviyo", "email", "age_stage_drip",
            "Triggered email by baby age (0-3mo, "
            "3-6mo, 6-12mo, 12-24mo, 2-3y). Pitch "
            "age-appropriate gear at each stage.",
            "Triggered automation: enable Day 1, "
            "fires per-customer on signup birthday "
            "field.",
        ),
        (
            "Mom Blogger Affiliate",
            "social", "affiliate", 20.0,
            "mom_blogger", "affiliate", "mom_creators",
            "Mom Instagram + blog network. Authentic "
            "use-with-real-baby content outperforms "
            "studio shots 5-10x.",
            "Month 1 -- new parents recruit quickly.",
        ),
    ],
    "general": [],
}


def generate_marketing_event_templates(
    *,
    store_name: str,
    niche: str = "general",
    create_status: str = "paused",
) -> dict[str, Any]:
    """Build niche-aware marketing campaign templates.

    Args:
        store_name: Display name (for the campaign title +
            UTM defaults). Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general
            (universal-only).
        create_status: ``paused`` (default) or ``active``.
            Best practice: create paused, let operator
            review + activate manually.

    Returns:
        ``{store_name, niche, campaigns: [...]}``. Each
        campaign carries full spec ready for
        ``SHOPIFY_CREATE_MARKETING_ACTIVITY``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    status = (create_status or "paused").strip().lower()
    if status not in ("paused", "active"):
        status = "paused"

    niche_entries = _NICHE_CAMPAIGNS.get(niche_n, [])

    campaigns: list[dict[str, Any]] = []
    for entry in _UNIVERSAL_CAMPAIGNS + niche_entries:
        (
            camp_name, channel, tactic, budget,
            utm_source, utm_medium, utm_campaign,
            rationale, when_to_launch,
        ) = entry
        campaigns.append({
            "name": camp_name,
            "title": f"{name} -- {camp_name}",
            "channel": channel,
            "tactic": tactic,
            "status": status,
            "utm_source": utm_source,
            "utm_medium": utm_medium,
            "utm_campaign": (
                f"{utm_campaign}_{niche_n}"
            ),
            "budget_daily_usd": float(budget),
            "rationale": rationale,
            "when_to_launch": when_to_launch,
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "campaigns": campaigns,
    }


def hand_off_to_marketing_adapter(
    template: dict[str, Any],
) -> list[dict[str, Any]]:
    """Translate the campaign list into per-campaign
    kwargs dicts ready for
    ``SHOPIFY_CREATE_MARKETING_ACTIVITY``.

    The adapter expects: ``title``, ``channel``,
    ``tactic``, ``status``, ``utm.source``, ``utm.medium``,
    ``utm.campaign``, optional ``budget`` (with amount +
    currency_code), ``remote_url``.

    Returns one dict per campaign, drop-in for
    ``router.execute(Capability.SHOPIFY_CREATE_MARKETING_ACTIVITY, params)``.
    """
    if (
        not isinstance(template, dict)
        or not template.get("campaigns")
    ):
        return []
    out: list[dict[str, Any]] = []
    for c in template["campaigns"]:
        if not isinstance(c, dict):
            continue
        params: dict[str, Any] = {
            "title": c["title"],
            "channel": c["channel"],
            "tactic": c["tactic"],
            "status": c["status"],
            "utm": {
                "source": c["utm_source"],
                "medium": c["utm_medium"],
                "campaign": c["utm_campaign"],
            },
            "remote_url": (
                # Operator-facing placeholder until the
                # campaign is actually created in the
                # ad platform. ShopAI generates the
                # placeholder so the adapter doesn't
                # reject the call on the Pattern C
                # required-field guard.
                f"https://example.com/marketing/"
                f"{c['name'].lower().replace(' ', '-')}"
            ),
        }
        if c["budget_daily_usd"] > 0:
            params["budget"] = {
                "amount": str(c["budget_daily_usd"]),
                "currency_code": "USD",
            }
        out.append(params)
    return out
