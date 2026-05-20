"""Niche-aware shipping zone + rate recommendations.

Shopify Admin lets operators configure:
  * Shipping zones (countries / regions covered)
  * Rate tiers (by weight, price, or flat)
  * Free shipping thresholds
  * Carrier-calculated rates (UPS, USPS, etc.)

Default stores ship with NO custom zones -- the merchant
has to set everything up before going live. Most defer
this until orders start coming in, which means the first
real customers see "shipping unavailable" or default
expensive rates.

This module ships niche-aware shipping zone + rate
recommendations per niche. Operator pastes into Shopify
Admin -> Shipping settings.

Niche-relevant differences:
  * Beauty: light items (50-200g), low shipping cost, free
    shipping threshold at $50.
  * Furniture / home: heavy + bulky (5-25kg), higher
    rates, white-glove option for $500+ items.
  * Food: temperature-controlled, insulated packaging
    fee, expedited shipping default.
  * Jewelry: insured + signature-required, lower weight
    but premium service.
  * Tech: medium weight + insurance for high-AOV items.

Return shape from
:func:`generate_shipping_zone_recommendations`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "zones": [
            {
                "zone_name": "Domestic (US)",
                "countries": ["US"],
                "rates": [
                    {name, weight_min_g, weight_max_g,
                     price_usd, delivery_days,
                     rationale},
                    ...
                ],
                "free_shipping_threshold_usd": 50.0,
            },
            ...
        ],
    }

Persists as a Shopify page (handle ``shipping-zones``).
No write adapter for delivery profiles yet, so this is
operator-facing reference content.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Per-niche tuning:
#   (
#     domestic_rates: list[(name, max_g, price, days)],
#     international_rates: list[(name, max_g, price, days)],
#     free_shipping_threshold,
#     extras: dict[str, str],  # niche-specific notes
#   )
#
# Weight bands tuned to the category's typical packaging:
# beauty (1 product = 100g) vs home (1 product = 5kg).
#
# Domestic = US; international = "rest of world".
_NICHE_RATES: dict[
    str,
    tuple[
        list[tuple[str, int, float, str]],
        list[tuple[str, int, float, str]],
        float,
        dict[str, str],
    ],
] = {
    "beauty": (
        # Domestic
        [
            ("Standard", 500, 5.99, "3-5"),
            ("Standard (heavy)", 2000, 8.99, "3-5"),
            ("Express", 500, 12.99, "1-2"),
        ],
        # International
        [
            ("Standard", 500, 18.00, "7-14"),
            ("Standard (heavy)", 2000, 28.00, "7-14"),
        ],
        50.0,
        {
            "packaging": (
                "Beauty products fit in padded "
                "envelopes for items <200g, small "
                "boxes above. Avoid bubble wrap on "
                "fragile glass; use crinkle-paper "
                "infill."
            ),
            "insurance": (
                "Optional. Most items <$100 -- "
                "self-insure via free reships."
            ),
        },
    ),
    "fashion": (
        [
            ("Standard", 1000, 7.99, "3-5"),
            ("Standard (heavy)", 3000, 11.99, "3-5"),
            ("Express", 1000, 16.99, "1-2"),
        ],
        [
            ("Standard", 1000, 25.00, "7-21"),
            ("Standard (heavy)", 3000, 38.00, "7-21"),
            ("Express", 1000, 55.00, "3-5"),
        ],
        75.0,
        {
            "packaging": (
                "Garment bags for delicate items; "
                "poly mailers for sturdy. Include "
                "free return label for first-time "
                "buyers."
            ),
            "free_returns": (
                "Critical in fashion -- 30% of "
                "online apparel orders are returned. "
                "Free returns drive conversion 2x."
            ),
        },
    ),
    "tech": (
        [
            ("Standard", 2000, 9.99, "3-5"),
            ("Standard (heavy)", 5000, 14.99, "3-5"),
            ("Express", 2000, 19.99, "1-2"),
        ],
        [
            ("Standard", 2000, 35.00, "7-14"),
            ("Express", 2000, 75.00, "3-5"),
        ],
        75.0,
        {
            "insurance": (
                "REQUIRED for orders >$200. Tech "
                "items are theft-prone in transit; "
                "uninsured loss is on you."
            ),
            "packaging": (
                "Original manufacturer boxes inside "
                "shipping boxes -- protects warranty "
                "claims + customer unboxing."
            ),
        },
    ),
    "home": (
        [
            ("Standard", 5000, 14.99, "5-7"),
            ("Standard (heavy)", 15000, 29.99, "5-7"),
            (
                "White-Glove (large items)",
                25000, 99.00, "7-14",
            ),
        ],
        [
            ("Standard", 5000, 60.00, "14-30"),
        ],
        100.0,
        {
            "packaging": (
                "Heavy + breakable items need "
                "double-wall corrugated + foam "
                "inserts. Budget $5-10 per item for "
                "packaging materials."
            ),
            "white_glove": (
                "Items over $500 + furniture: offer "
                "white-glove delivery (inside-the-"
                "room) at $99 surcharge. Drives "
                "AOV + reduces return rate."
            ),
        },
    ),
    "food": (
        [
            ("Standard (ambient)", 5000, 8.99, "3-5"),
            (
                "Refrigerated (insulated)",
                5000, 18.99, "1-3",
            ),
            ("Frozen (dry ice)", 5000, 24.99, "1-3"),
        ],
        # Food rarely ships internationally without
        # cold-chain partners; flat-rate placeholder.
        [
            ("Standard (ambient only)", 5000, 45.00, "10-21"),
        ],
        40.0,
        {
            "cold_chain": (
                "CRITICAL: temperature-controlled "
                "products require insulated boxes "
                "+ ice packs / dry ice. Build "
                "packaging cost into the rate "
                "(typically $5-15 per box)."
            ),
            "ship_days": (
                "Ship Mon-Wed only -- avoids "
                "weekend transit for perishables. "
                "Customers ordering Thu-Sun see "
                "'ships next Monday' messaging."
            ),
        },
    ),
    "pets": (
        [
            ("Standard", 2000, 7.99, "3-5"),
            ("Standard (heavy bag)", 10000, 14.99, "3-5"),
            ("Express", 2000, 14.99, "1-2"),
        ],
        [
            ("Standard", 2000, 30.00, "7-21"),
        ],
        49.0,
        {
            "subscription_discount": (
                "Auto-ship subscribers get free "
                "shipping on every order -- "
                "highest-LTV cohort, worth the "
                "shipping subsidy."
            ),
            "packaging": (
                "Pet food bags need water-resistant "
                "outer packaging. Treats: clearly "
                "label 'fragile' for biscuits."
            ),
        },
    ),
    "fitness": (
        [
            ("Standard", 2000, 8.99, "3-5"),
            ("Standard (heavy gear)", 10000, 19.99, "3-5"),
            ("Express", 2000, 17.99, "1-2"),
        ],
        [
            ("Standard", 2000, 30.00, "7-14"),
        ],
        75.0,
        {
            "packaging": (
                "Apparel: poly mailers. Supplements: "
                "rigid box (tamper-evident). "
                "Equipment: original manufacturer "
                "boxes."
            ),
            "express_for_supplements": (
                "Athletes running out of supplement "
                "stack will buy from competitors if "
                "shipping is slow. Always offer "
                "Express."
            ),
        },
    ),
    "jewelry": (
        [
            (
                "Standard (insured + signature)",
                500, 12.99, "3-5",
            ),
            (
                "Express (insured + signature)",
                500, 24.99, "1-2",
            ),
        ],
        [
            (
                "International (insured + signature)",
                500, 55.00, "7-14",
            ),
        ],
        100.0,
        {
            "insurance": (
                "REQUIRED for ALL jewelry shipments. "
                "Add to base rate; never make it "
                "optional."
            ),
            "signature": (
                "REQUIRED on delivery for orders "
                ">$100. Reduces theft + chargeback "
                "fraud risk."
            ),
            "packaging": (
                "Jewelry box inside padded outer "
                "box. Discreet exterior (no brand "
                "logos visible) reduces porch-pirate "
                "risk."
            ),
        },
    ),
    "outdoor": (
        [
            ("Standard", 3000, 9.99, "3-5"),
            ("Standard (bulky)", 10000, 19.99, "3-5"),
            ("Express", 3000, 19.99, "1-2"),
        ],
        [
            ("Standard", 3000, 40.00, "7-21"),
        ],
        75.0,
        {
            "packaging": (
                "Tents + sleep systems: rolled into "
                "long tube boxes. Apparel: poly "
                "mailers. Hard goods (cookware): "
                "double-wall boxes."
            ),
            "seasonal_rush": (
                "Spring + early summer = highest "
                "shipping volume for outdoor. Stock "
                "warehouses + add temporary "
                "Express capacity."
            ),
        },
    ),
    "baby": (
        [
            ("Standard", 2000, 6.99, "3-5"),
            ("Standard (heavy)", 8000, 12.99, "3-5"),
            ("Express", 2000, 14.99, "1-2"),
        ],
        [
            ("Standard", 2000, 28.00, "7-14"),
        ],
        50.0,
        {
            "subscription_discount": (
                "Diaper + formula auto-ship gets "
                "free shipping. Standard for the "
                "category."
            ),
            "packaging": (
                "Soft items in poly mailers; "
                "feeding gear (glass / ceramic) in "
                "double-wall boxes with foam."
            ),
            "express_for_essentials": (
                "Parents running out of diapers / "
                "formula need NEXT-DAY shipping. "
                "Offer Express even at lower "
                "margin -- retention is the win."
            ),
        },
    ),
    "general": (
        [
            ("Standard", 2000, 7.99, "3-5"),
            ("Express", 2000, 14.99, "1-2"),
        ],
        [
            ("Standard", 2000, 25.00, "7-14"),
        ],
        50.0,
        {
            "general": (
                "Generic fallback rates. Tune per "
                "category once you know your "
                "actual product weights + AOV."
            ),
        },
    ),
}


_SHIPPING_PAGE_TITLE: str = "Shipping Zones & Rates"
_SHIPPING_PAGE_HANDLE: str = "shipping-zones"


def generate_shipping_zone_recommendations(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build niche-aware shipping zone + rate spec.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.

    Returns:
        ``{store_name, niche, zones: [...]}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    tuning = _NICHE_RATES.get(
        niche_n, _NICHE_RATES["general"],
    )
    (
        domestic_rates, intl_rates,
        free_threshold, extras,
    ) = tuning

    zones: list[dict[str, Any]] = [
        {
            "zone_name": "Domestic (US)",
            "countries": ["US"],
            "rates": [
                {
                    "name": r[0],
                    "weight_max_g": int(r[1]),
                    "price_usd": float(r[2]),
                    "delivery_days": r[3],
                }
                for r in domestic_rates
            ],
            "free_shipping_threshold_usd": (
                float(free_threshold)
            ),
        },
        {
            "zone_name": "International",
            "countries": ["WORLD_EXCEPT_US"],
            "rates": [
                {
                    "name": r[0],
                    "weight_max_g": int(r[1]),
                    "price_usd": float(r[2]),
                    "delivery_days": r[3],
                }
                for r in intl_rates
            ],
            "free_shipping_threshold_usd": (
                float(free_threshold) * 2
            ),
        },
    ]

    return {
        "store_name": name,
        "niche": niche_n,
        "zones": zones,
        "operator_notes": extras,
    }


def render_shipping_html(spec: dict[str, Any]) -> str:
    if not isinstance(spec, dict) or not spec.get("zones"):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    zones = spec.get("zones") or []
    notes = spec.get("operator_notes") or {}

    zone_sections: list[str] = []
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        zname = html.escape(zone.get("zone_name", "") or "")
        countries = ", ".join(
            html.escape(c) for c in (
                zone.get("countries") or []
            )
        )
        free_thr = zone.get(
            "free_shipping_threshold_usd", 0,
        )
        rate_rows: list[str] = []
        for rate in zone.get("rates") or []:
            rate_rows.append(
                "<tr>"
                f"<td>{html.escape(rate.get('name', ''))}</td>"
                f"<td>up to {rate.get('weight_max_g', 0)}g</td>"
                f"<td>${rate.get('price_usd', 0):.2f}</td>"
                f"<td>{html.escape(rate.get('delivery_days', ''))} days</td>"
                "</tr>"
            )
        zone_sections.append(
            "<section class=\"shipping-zone\">"
            f"<h2>{zname}</h2>"
            f"<p>Countries: <code>{countries}</code></p>"
            f"<p>Free shipping over: "
            f"<strong>${free_thr:.2f}</strong></p>"
            "<table class=\"shipping-rates\">"
            "<thead><tr><th>Rate</th><th>Weight</th>"
            "<th>Price</th><th>Delivery</th></tr></thead>"
            "<tbody>"
            + "".join(rate_rows) +
            "</tbody></table>"
            "</section>"
        )

    notes_blocks: list[str] = []
    for key, text in notes.items():
        if not text:
            continue
        notes_blocks.append(
            f"<dt>{html.escape(key.replace('_', ' ').title())}"
            f"</dt><dd>{html.escape(text)}</dd>"
        )

    return (
        "<section class=\"shipping-zones\">"
        f"<h1>{name} -- Shipping Zones &amp; Rates</h1>"
        "<p>Paste these into Shopify Admin -> Settings -> "
        "Shipping &amp; Delivery. Rates tuned for the "
        "niche's typical product weight + delivery "
        "expectations.</p>"
        + "".join(zone_sections) +
        (
            "<h2>Operator Notes</h2>"
            "<dl>" + "".join(notes_blocks) + "</dl>"
            if notes_blocks else ""
        ) +
        "</section>"
    )


def apply_shipping_zones(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist as Shopify page ``shipping-zones``.

    No delivery-profile write adapter exists yet -- this
    is operator-facing reference content. The operator
    pastes the rate table into Shopify Admin's Shipping
    settings manually.
    """
    if not isinstance(spec, dict) or not spec.get("zones"):
        return {
            "applied": False,
            "handle": _SHIPPING_PAGE_HANDLE,
            "error": "no_shipping_spec",
        }

    body_html = render_shipping_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _SHIPPING_PAGE_HANDLE,
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
            "handle": _SHIPPING_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _SHIPPING_PAGE_TITLE,
        "handle": _SHIPPING_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "shipping_zones router.execute raised: %s",
            exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _SHIPPING_PAGE_HANDLE,
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
            "handle": _SHIPPING_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _SHIPPING_PAGE_HANDLE,
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
    zones = spec.get("zones") or []
    params: dict[str, Any] = {
        "handle": _SHIPPING_PAGE_HANDLE,
        "zone_count": len(zones),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_shipping_zones",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _SHIPPING_PAGE_HANDLE,
                "zone_count": len(zones),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "shipping_zones record_writeback raised: %s",
            exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "shipping_zones router import failed: %s",
            exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "shipping_zones capability resolve failed: "
            "%s", exc,
        )
        return None
