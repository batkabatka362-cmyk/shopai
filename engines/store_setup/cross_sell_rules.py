"""Niche-aware cross-sell + upsell rule templates.

Cross-sell ("buyers of X also bought Y") drives 20-35% of
ecommerce revenue across mature stores. Most newly-launched
Shopify stores ship with NO cross-sell rules -- the
"Related products" theme block falls back to random
collection picks, which converts at <1%.

This module ships niche-aware rule templates: structured
``{trigger, suggestion, location}`` triplets that map an
on-page context to a related-product strategy.

Example output for beauty::

    {
        "name": "skincare_to_makeup",
        "trigger": {"context": "PDP",
                    "filter": {"tag": "category:skincare"}},
        "suggestion": {"strategy": "tag_match",
                       "filter": {"tag": "category:makeup"}},
        "location": "PDP related-products",
        "rationale": "...",
    }

The rule shape is consumed two ways:

  1. **Today** -- operator pastes the rules into a Shopify
     app like Loox / Stamped / Recommendz (most accept
     CSV / JSON of trigger+suggestion pairs).
  2. **Tomorrow** -- a `cross_sell` engine reads the rules
     + does the join at request time, writing to product
     metafields that the theme renders.

Pairs with:

  * ``tag_library`` (#385) -- filter conditions use the
    `family:value` taxonomy.
  * ``smart_collection_rules`` (#393) -- same filter
    language; rule-driven categories on the catalog side.
  * ``metaobject_definitions`` (#392) -- could persist
    rules as a `cross_sell_rule` metaobject for theme
    consumption.

Return shape from :func:`generate_cross_sell_rules`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "rules": [
            {name, trigger, suggestion, location,
             rationale},
            ...
        ],
    }

Persists as a Shopify page (handle ``cross-sell-rules``)
laying out the structured JSON for operator paste-in.
Records via Pattern Z.
"""
from __future__ import annotations

import html
import json
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Locations a recommendation can render in. Operator-facing
# convention.
_LOCATIONS: frozenset[str] = frozenset({
    "PDP related-products",
    "Cart drawer upsell",
    "Cart page upsell",
    "Post-purchase upsell",
    "Email follow-up",
    "Collection page sidebar",
})


# Strategy values. Each defines how the suggestion is
# computed.
_STRATEGIES: frozenset[str] = frozenset({
    "tag_match",        # match products by tag filter
    "same_collection",  # other products in same coll
    "complementary",    # different category, paired use
    "price_anchor",     # similar price range
    "top_seller",       # bestseller fallback
    "bundle",           # explicit bundle pairing
})


# Niche-specific rule templates. Each entry is a tuple
# (name, trigger_dict, suggestion_dict, location,
#  rationale).
_NICHE_RULES: dict[
    str,
    list[tuple[str, dict, dict, str, str]],
] = {
    "beauty": [
        (
            "skincare_to_makeup",
            {
                "context": "PDP",
                "filter": {"tag": "category:skincare"},
            },
            {
                "strategy": "complementary",
                "filter": {"tag": "category:makeup"},
                "max_results": 4,
            },
            "PDP related-products",
            "Skincare buyers convert to makeup at "
            "8-12% when shown complementary picks below "
            "the fold on PDPs.",
        ),
        (
            "complete_the_routine",
            {
                "context": "Cart drawer",
                "filter": {
                    "tag": "concern:hydration",
                },
            },
            {
                "strategy": "tag_match",
                "filter": {
                    "tag": "concern:hydration",
                },
                "exclude_in_cart": True,
                "max_results": 2,
            },
            "Cart drawer upsell",
            "Concern-based bundling lifts AOV ~15% in "
            "beauty -- customers building a routine want "
            "products that target the same goal.",
        ),
        (
            "fragrance_free_set",
            {
                "context": "PDP",
                "filter": {
                    "tag": "claims:fragrance-free",
                },
            },
            {
                "strategy": "tag_match",
                "filter": {
                    "tag": "claims:fragrance-free",
                },
                "exclude_self": True,
                "max_results": 3,
            },
            "PDP related-products",
            "Sensitive-skin buyers stay within the "
            "fragrance-free filter to avoid triggering "
            "reactions.",
        ),
    ],
    "fashion": [
        (
            "outfit_completer",
            {
                "context": "PDP",
                "filter": {"tag": "category:tops"},
            },
            {
                "strategy": "complementary",
                "filter": {"tag": "category:bottoms"},
                "max_results": 4,
            },
            "PDP related-products",
            "Outfit completion drives units-per-order "
            "in fashion. Show bottoms below tops on the "
            "PDP.",
        ),
        (
            "accessory_upsell",
            {
                "context": "Cart drawer",
                "filter": {
                    "tag": "category:apparel",
                },
            },
            {
                "strategy": "complementary",
                "filter": {
                    "tag": "category:accessories",
                },
                "price_max": 50,
                "max_results": 3,
            },
            "Cart drawer upsell",
            "Accessories cap the outfit + carry the "
            "highest cart-add rate (<$50 = impulse "
            "range).",
        ),
        (
            "size_match",
            {
                "context": "Email follow-up",
                "filter": {"tag": "fit-type:plus"},
            },
            {
                "strategy": "tag_match",
                "filter": {"tag": "fit-type:plus"},
                "exclude_purchased": True,
                "max_results": 6,
            },
            "Email follow-up",
            "Plus-size shoppers convert better with "
            "size-matched recommendations vs "
            "general-catalog suggestions.",
        ),
    ],
    "tech": [
        (
            "accessory_for_device",
            {
                "context": "PDP",
                "filter": {"tag": "category:audio"},
            },
            {
                "strategy": "complementary",
                "filter": {
                    "tag": "category:accessories",
                },
                "max_results": 4,
            },
            "PDP related-products",
            "Audio device buyers convert to "
            "accessories (cables / stands / cases) at "
            "20-30% within 30 days.",
        ),
        (
            "warranty_upgrade",
            {
                "context": "Cart page",
                "filter": {
                    "price_min": 100,
                },
            },
            {
                "strategy": "bundle",
                "filter": {
                    "tag": "category:warranty-extended",
                },
                "max_results": 1,
            },
            "Cart page upsell",
            "Extended warranties on $100+ items have "
            "the highest attach rate in tech (15-25%).",
        ),
    ],
    "home": [
        (
            "room_set",
            {
                "context": "PDP",
                "filter": {"tag": "room:bedroom"},
            },
            {
                "strategy": "tag_match",
                "filter": {"tag": "room:bedroom"},
                "exclude_self": True,
                "max_results": 4,
            },
            "PDP related-products",
            "Customers building out a room want "
            "matching pieces -- bedding to nightstand "
            "to lighting.",
        ),
        (
            "complementary_material",
            {
                "context": "Cart drawer",
                "filter": {"tag": "material:wood"},
            },
            {
                "strategy": "complementary",
                "filter": {"tag": "material:textile"},
                "max_results": 3,
            },
            "Cart drawer upsell",
            "Wood pieces benefit from soft textile "
            "complements (throws, rugs) -- visual "
            "balance + cart-add lift.",
        ),
    ],
    "food": [
        (
            "pantry_bundle",
            {
                "context": "PDP",
                "filter": {"tag": "category:pantry"},
            },
            {
                "strategy": "complementary",
                "filter": {"tag": "category:pantry"},
                "exclude_self": True,
                "max_results": 4,
            },
            "PDP related-products",
            "Pantry buyers stock up -- complementary "
            "pantry items (oil + vinegar, pasta + "
            "sauce) lift cart size 20-25%.",
        ),
        (
            "diet_match",
            {
                "context": "Collection page",
                "filter": {"tag": "diet:gluten-free"},
            },
            {
                "strategy": "tag_match",
                "filter": {"tag": "diet:gluten-free"},
                "max_results": 6,
            },
            "Collection page sidebar",
            "Diet-restricted shoppers stay within the "
            "diet filter -- saves search clicks + lifts "
            "session AOV.",
        ),
        (
            "drinks_with_food",
            {
                "context": "Cart drawer",
                "filter": {"tag": "category:snacks"},
            },
            {
                "strategy": "complementary",
                "filter": {"tag": "category:drinks"},
                "max_results": 2,
            },
            "Cart drawer upsell",
            "Snack + drink pairings = highest cart-add "
            "rate at checkout (impulse).",
        ),
    ],
    "pets": [
        (
            "treat_with_food",
            {
                "context": "PDP",
                "filter": {"tag": "category:food"},
            },
            {
                "strategy": "complementary",
                "filter": {"tag": "category:treats"},
                "max_results": 3,
            },
            "PDP related-products",
            "Pet food customers add treats at high "
            "rates -- pair on the food PDP.",
        ),
        (
            "species_match",
            {
                "context": "Cart drawer",
                "filter": {"tag": "species:dog"},
            },
            {
                "strategy": "tag_match",
                "filter": {"tag": "species:dog"},
                "exclude_in_cart": True,
                "max_results": 3,
            },
            "Cart drawer upsell",
            "Species-locked filtering avoids "
            "irrelevant suggestions (cat litter for "
            "dog owners = bounce).",
        ),
        (
            "age_match",
            {
                "context": "PDP",
                "filter": {"tag": "life-stage:puppy"},
            },
            {
                "strategy": "tag_match",
                "filter": {"tag": "life-stage:puppy"},
                "exclude_self": True,
                "max_results": 4,
            },
            "PDP related-products",
            "Age-stage matching is critical -- adult "
            "food for a puppy is a customer-service "
            "complaint waiting to happen.",
        ),
    ],
    "fitness": [
        (
            "apparel_completer",
            {
                "context": "PDP",
                "filter": {"tag": "category:apparel"},
            },
            {
                "strategy": "tag_match",
                "filter": {"tag": "category:apparel"},
                "exclude_self": True,
                "max_results": 4,
            },
            "PDP related-products",
            "Athletes build outfits -- top/bottom/"
            "accessory bundling lifts units-per-order.",
        ),
        (
            "supplement_pair",
            {
                "context": "Cart drawer",
                "filter": {
                    "tag": "category:supplements",
                },
            },
            {
                "strategy": "complementary",
                "filter": {
                    "tag": "category:supplements",
                },
                "exclude_in_cart": True,
                "max_results": 2,
            },
            "Cart drawer upsell",
            "Supplement-stack buyers add complements "
            "(protein + recovery, multivitamin + "
            "joint).",
        ),
    ],
    "jewelry": [
        (
            "matching_piece",
            {
                "context": "PDP",
                "filter": {
                    "tag": "metal:sterling-silver",
                },
            },
            {
                "strategy": "tag_match",
                "filter": {
                    "tag": "metal:sterling-silver",
                },
                "exclude_self": True,
                "max_results": 4,
            },
            "PDP related-products",
            "Metal-matched recommendations: customers "
            "building a sterling silver set don't want "
            "gold suggestions next to their pick.",
        ),
        (
            "bridal_set",
            {
                "context": "PDP",
                "filter": {"tag": "category:bridal"},
            },
            {
                "strategy": "tag_match",
                "filter": {"tag": "category:bridal"},
                "exclude_self": True,
                "max_results": 6,
            },
            "PDP related-products",
            "Bridal is purchased in sets (ring + band "
            "+ matching pieces) -- show the full set "
            "on every bridal PDP.",
        ),
    ],
    "outdoor": [
        (
            "trip_kit",
            {
                "context": "PDP",
                "filter": {"tag": "activity:camping"},
            },
            {
                "strategy": "tag_match",
                "filter": {"tag": "activity:camping"},
                "exclude_self": True,
                "max_results": 4,
            },
            "PDP related-products",
            "Camping shoppers buy kits -- tent + sleep "
            "system + pack matched suggestions.",
        ),
        (
            "weather_layer",
            {
                "context": "Cart drawer",
                "filter": {
                    "tag": "category:apparel",
                },
            },
            {
                "strategy": "complementary",
                "filter": {
                    "tag": "weather:waterproof",
                },
                "max_results": 2,
            },
            "Cart drawer upsell",
            "Outdoor apparel buyers add weather "
            "protection (rain shells, gaiters) at "
            "checkout when prompted.",
        ),
    ],
    "baby": [
        (
            "age_stage_match",
            {
                "context": "PDP",
                "filter": {"tag": "age-stage:0-3mo"},
            },
            {
                "strategy": "tag_match",
                "filter": {"tag": "age-stage:0-3mo"},
                "exclude_self": True,
                "max_results": 4,
            },
            "PDP related-products",
            "Baby age-stages don't overlap -- "
            "recommending 12-month gear to a 0-3mo "
            "buyer is irrelevant.",
        ),
        (
            "essentials_bundle",
            {
                "context": "Cart drawer",
                "filter": {"tag": "category:clothing"},
            },
            {
                "strategy": "complementary",
                "filter": {
                    "tag": "category:feeding",
                },
                "max_results": 3,
            },
            "Cart drawer upsell",
            "New parents shop in essentials sweeps -- "
            "clothing + feeding + nursery is the "
            "natural cart bundle.",
        ),
    ],
    "general": [
        (
            "top_sellers",
            {"context": "PDP", "filter": {}},
            {
                "strategy": "top_seller",
                "filter": {},
                "exclude_self": True,
                "max_results": 4,
            },
            "PDP related-products",
            "Fallback: top-sellers on every PDP. Beats "
            "the random-collection-pick default that "
            "themes ship with.",
        ),
    ],
}


_RULES_PAGE_TITLE: str = "Cross-Sell Recommendation Rules"
_RULES_PAGE_HANDLE: str = "cross-sell-rules"


def generate_cross_sell_rules(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build niche-aware cross-sell rule specs.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.

    Returns:
        ``{store_name, niche, rules: [...]}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    entries = _NICHE_RULES.get(
        niche_n, _NICHE_RULES["general"],
    )

    rules: list[dict[str, Any]] = []
    for entry in entries:
        rule_name, trigger, suggestion, location, rationale = (
            entry
        )
        rules.append({
            "name": rule_name,
            # Deep-copy trigger + suggestion so caller
            # mutation doesn't poison the library.
            "trigger": dict(trigger),
            "suggestion": dict(suggestion),
            "location": location,
            "rationale": rationale,
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "rules": rules,
    }


def render_rules_html(spec: dict[str, Any]) -> str:
    if not isinstance(spec, dict) or not spec.get("rules"):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    rules = spec.get("rules") or []

    rows: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_name = html.escape(rule.get("name", "") or "")
        location = html.escape(
            rule.get("location", "") or "",
        )
        rationale = html.escape(
            rule.get("rationale", "") or "",
        )
        trigger_json = html.escape(
            json.dumps(rule.get("trigger", {}), indent=2),
        )
        suggestion_json = html.escape(
            json.dumps(
                rule.get("suggestion", {}), indent=2,
            ),
        )
        rows.append(
            "<section class=\"cross-sell-rule\">"
            f"<h2>{rule_name}</h2>"
            f"<p><strong>Where:</strong> {location}</p>"
            f"<p>{rationale}</p>"
            "<h3>Trigger</h3>"
            f"<pre>{trigger_json}</pre>"
            "<h3>Suggestion</h3>"
            f"<pre>{suggestion_json}</pre>"
            "</section>"
        )

    return (
        "<section class=\"cross-sell-rules\">"
        f"<h1>{name} -- Cross-Sell Rule Library</h1>"
        "<p>Operator-facing reference for setting up "
        "product recommendations. Each rule maps a "
        "<strong>trigger</strong> (what the buyer is "
        "viewing) to a <strong>suggestion</strong> "
        "(what to recommend). Paste into your "
        "recommendations app (Loox / Stamped / "
        "Recommendz) or wire via a future "
        "<code>cross_sell</code> engine that joins to "
        "product metafields.</p>"
        + "".join(rows) +
        "</section>"
    )


def apply_rules(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist as Shopify page ``cross-sell-rules``."""
    if not isinstance(spec, dict) or not spec.get("rules"):
        return {
            "applied": False,
            "handle": _RULES_PAGE_HANDLE,
            "error": "no_rules_spec",
        }

    body_html = render_rules_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _RULES_PAGE_HANDLE,
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
            "handle": _RULES_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _RULES_PAGE_TITLE,
        "handle": _RULES_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cross_sell_rules router.execute raised: "
            "%s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _RULES_PAGE_HANDLE,
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
            "handle": _RULES_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _RULES_PAGE_HANDLE,
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
    rules = spec.get("rules") or []
    params: dict[str, Any] = {
        "handle": _RULES_PAGE_HANDLE,
        "rule_count": len(rules),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_cross_sell_rules",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _RULES_PAGE_HANDLE,
                "rule_count": len(rules),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cross_sell_rules record_writeback raised: "
            "%s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cross_sell_rules router import failed: %s",
            exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cross_sell_rules capability resolve "
            "failed: %s", exc,
        )
        return None
