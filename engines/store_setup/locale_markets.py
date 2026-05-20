"""Niche-aware market + currency / locale recommender.

Every Shopify store opens with a single primary market
(usually US, currency USD, locale en). Operators add
international markets ad-hoc when they remember --
which means international customers see "shipping
unavailable" or default-broken currency display until
the operator gets around to it.

Each niche has different international demand patterns:

  * **Beauty / fashion** -- huge international demand;
    open EU + UK + Australia + Canada Day 1.
  * **Food** -- domestic-only typically (perishables +
    customs); US-only at launch.
  * **Jewelry** -- cherry-pick wealthy markets (UK,
    Switzerland, UAE, Australia).
  * **Pets / baby** -- highly regulated per-country
    (CPSIA / EN-71 / pet-food regs); domestic-first.
  * **Tech** -- broad market support; warranty
    logistics need consideration.
  * **Outdoor / fitness** -- core English-speaking
    markets (US / CA / AU / UK).

This module ships niche-aware market recommendations
ready to push via ``SHOPIFY_CREATE_MARKET``.

Return shape from
:func:`generate_market_recommendations`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "primary_market": {
            "name": "United States",
            "handle": "us",
            "country_codes": ["US"],
            "currency": "USD",
            "locale": "en",
        },
        "additional_markets": [
            {
                "name": "European Union",
                "handle": "eu",
                "country_codes": ["DE", "FR", "IT", "ES",
                                  "NL", "BE", "AT", "IE"],
                "currency": "EUR",
                "locale": "en",
                "rationale": "EU is the second-largest "
                  "beauty market after the US...",
                "when_to_open": "Day 1 -- always-on.",
            },
            ...
        ],
    }
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Primary market is US/USD/en for every niche by default;
# operators in other base markets override at apply time.
_DEFAULT_PRIMARY = {
    "name": "United States",
    "handle": "us",
    "country_codes": ["US"],
    "currency": "USD",
    "locale": "en",
}


# Niche-specific additional-market recommendations.
# Each entry: (name, handle, country_codes, currency,
#              locale, rationale, when_to_open).
_NICHE_MARKETS: dict[
    str,
    list[tuple[
        str, str, list[str], str, str, str, str,
    ]],
] = {
    "beauty": [
        (
            "Canada", "ca", ["CA"],
            "CAD", "en",
            "Canada is the highest-LTV English-speaking "
            "market adjacent to US. Beauty buyers "
            "convert 1.5-2x English-speaking averages.",
            "Day 1 -- minimal friction; same shipping "
            "carriers as US.",
        ),
        (
            "United Kingdom", "uk", ["GB"],
            "GBP", "en",
            "UK is the European beauty hub. Average UK "
            "beauty AOV is ~1.3x US. VAT-registered for "
            "duty-paid display.",
            "Day 1 -- always-on baseline.",
        ),
        (
            "European Union", "eu",
            [
                "DE", "FR", "IT", "ES", "NL", "BE",
                "AT", "IE",
            ],
            "EUR", "en",
            "EU is the second-largest beauty market "
            "after the US. Cosmetics regulation (EC "
            "1223/2009) requires CPNP notification "
            "before launching; account for 2-4 weeks "
            "lead time.",
            "Day 7+ -- after CPNP registration is "
            "complete.",
        ),
        (
            "Australia", "au", ["AU"],
            "AUD", "en",
            "Australia is small but high-AOV; "
            "English-speaking + similar regulatory "
            "regime to US for most categories.",
            "Day 14+ -- after primary markets stabilise.",
        ),
    ],
    "fashion": [
        (
            "Canada", "ca", ["CA"],
            "CAD", "en",
            "Adjacent market; same fashion seasons + "
            "size systems as US. Lowest-friction "
            "international expansion.",
            "Day 1 -- always-on.",
        ),
        (
            "United Kingdom", "uk", ["GB"],
            "GBP", "en",
            "UK fashion market has its own size system "
            "(UK 8 = US 4). Configure size charts "
            "carefully.",
            "Day 1 -- always-on.",
        ),
        (
            "European Union", "eu",
            [
                "DE", "FR", "IT", "ES", "NL", "SE",
                "DK", "FI",
            ],
            "EUR", "en",
            "EU fashion sizes (EU 36 = US 4). Mandatory "
            "fabric-composition labels under Regulation "
            "1007/2011.",
            "Day 7+ -- after size charts + labels are "
            "updated.",
        ),
        (
            "Australia + New Zealand", "anz",
            ["AU", "NZ"],
            "AUD", "en",
            "Reversed seasons -- southern hemisphere "
            "summer = US winter. Worth opening for "
            "off-season inventory clearance.",
            "Day 30+ -- coordinate with seasonal "
            "drops.",
        ),
    ],
    "tech": [
        (
            "Canada", "ca", ["CA"],
            "CAD", "en",
            "Adjacent market; same voltage + plug type. "
            "FCC + Industry Canada certification "
            "usually accepted on US-certified products.",
            "Day 1 -- always-on.",
        ),
        (
            "United Kingdom", "uk", ["GB"],
            "GBP", "en",
            "Different voltage (230V) + plug type (G "
            "vs A/B). Verify product compatibility "
            "before opening.",
            "Day 7+ -- after compatibility audit.",
        ),
        (
            "European Union", "eu",
            ["DE", "FR", "IT", "ES", "NL"],
            "EUR", "en",
            "CE marking required. Different voltage "
            "(230V) + plug type. RoHS + WEEE "
            "compliance for any e-waste category.",
            "Day 30+ -- after CE compliance is "
            "documented.",
        ),
    ],
    "home": [
        (
            "Canada", "ca", ["CA"],
            "CAD", "en",
            "Adjacent market; same plug types + room "
            "sizing conventions.",
            "Day 1 -- always-on.",
        ),
        (
            "United Kingdom", "uk", ["GB"],
            "GBP", "en",
            "UK voltage 230V + UK plug type. "
            "Furniture / decor: room sizes smaller "
            "than US -- account for in product "
            "descriptions.",
            "Day 7+ -- after voltage / plug "
            "compatibility check.",
        ),
        (
            "Australia", "au", ["AU"],
            "AUD", "en",
            "AU voltage 230V + Type I plug. Long "
            "shipping; consider higher rates.",
            "Day 14+ -- after shipping costs "
            "validated.",
        ),
    ],
    "food": [
        # Food rarely ships internationally; only the
        # core English-speaking markets that share food
        # regulations.
        (
            "Canada", "ca", ["CA"],
            "CAD", "en",
            "Adjacent market; CFIA labelling + "
            "bilingual requirements (English + "
            "French). Many US food companies expand "
            "here first.",
            "Day 14+ -- after CFIA labelling is "
            "ready.",
        ),
    ],
    "pets": [
        (
            "Canada", "ca", ["CA"],
            "CAD", "en",
            "Pet products: CFIA pet-food rules align "
            "with FDA. Treats + supplements: "
            "veterinary biologics review may apply.",
            "Day 14+ -- after CFIA verification.",
        ),
        (
            "United Kingdom", "uk", ["GB"],
            "GBP", "en",
            "Post-Brexit pet-food import requires "
            "GB-specific labels + DEFRA registration. "
            "Lead time ~4-6 weeks.",
            "Day 60+ -- regulatory + label updates.",
        ),
    ],
    "fitness": [
        (
            "Canada", "ca", ["CA"],
            "CAD", "en",
            "Supplements: Health Canada Natural "
            "Product Number (NPN) required for many "
            "categories. Apparel: minimal regulatory "
            "friction.",
            "Day 14+ -- supplements need NPN approval.",
        ),
        (
            "United Kingdom", "uk", ["GB"],
            "GBP", "en",
            "Apparel: low friction. Supplements: "
            "MHRA registration may apply to "
            "borderline products (joint health, "
            "etc.).",
            "Day 30+ -- after supplement classification "
            "review.",
        ),
        (
            "Australia", "au", ["AU"],
            "AUD", "en",
            "Therapeutic Goods Administration (TGA) "
            "registration required for many "
            "supplements. Apparel: low friction.",
            "Day 60+ -- TGA review process is slow.",
        ),
    ],
    "jewelry": [
        (
            "United Kingdom", "uk", ["GB"],
            "GBP", "en",
            "London is the European jewelry hub. "
            "Hallmarking Act requires UK assay "
            "office marks on precious-metal pieces -- "
            "lead time 2-4 weeks for unmarked stock.",
            "Day 14+ -- after hallmarking is "
            "arranged.",
        ),
        (
            "Australia", "au", ["AU"],
            "AUD", "en",
            "High AOV market; minimal regulatory "
            "friction. Insured shipping at $30-50 per "
            "package.",
            "Day 7+ -- always-on.",
        ),
        (
            "United Arab Emirates", "ae", ["AE"],
            "AED", "en",
            "Dubai is a growing premium jewelry "
            "market. No VAT on precious metals at "
            "import (purity-marked).",
            "Day 30+ -- payment processing + insured "
            "shipping setup.",
        ),
    ],
    "outdoor": [
        (
            "Canada", "ca", ["CA"],
            "CAD", "en",
            "Adjacent outdoor market with similar "
            "seasons + trail conditions. Very strong "
            "outdoor purchasing culture.",
            "Day 1 -- always-on baseline.",
        ),
        (
            "United Kingdom", "uk", ["GB"],
            "GBP", "en",
            "Strong hiking + climbing community; "
            "European trail standards differ slightly "
            "from US.",
            "Day 7+ -- always-on.",
        ),
        (
            "Australia + New Zealand", "anz",
            ["AU", "NZ"],
            "AUD", "en",
            "Reversed seasons useful for off-season "
            "inventory rotation.",
            "Day 30+ -- seasonal rotation play.",
        ),
    ],
    "baby": [
        (
            "Canada", "ca", ["CA"],
            "CAD", "en",
            "Canadian Consumer Product Safety Act "
            "labelling required for baby gear. "
            "Adjacent market with US-aligned safety "
            "standards.",
            "Day 14+ -- after CPSA labels are ready.",
        ),
        (
            "United Kingdom", "uk", ["GB"],
            "GBP", "en",
            "UK requires CE + UKCA marking on many "
            "baby products. Standards more stringent "
            "than US for some categories (toys / "
            "feeding).",
            "Day 30+ -- after UKCA conformity "
            "documented.",
        ),
        (
            "Australia", "au", ["AU"],
            "AUD", "en",
            "ACCC mandatory safety standards for "
            "many baby products. Verify each SKU "
            "before opening.",
            "Day 60+ -- ACCC compliance review.",
        ),
    ],
    "general": [
        (
            "Canada", "ca", ["CA"],
            "CAD", "en",
            "Adjacent market with the lowest expansion "
            "friction. Same shipping carriers, similar "
            "consumer expectations.",
            "Day 1 -- always-on.",
        ),
    ],
}


_MARKETS_PAGE_TITLE: str = "Market & Currency Recommendations"
_MARKETS_PAGE_HANDLE: str = "market-recommendations"


def generate_market_recommendations(
    *,
    store_name: str,
    niche: str = "general",
    primary_market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build niche-aware market + currency recommendations.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.
        primary_market: Override the default primary
            (US/USD/en) -- e.g. operators based in EU
            pass their home market here.

    Returns:
        ``{store_name, niche, primary_market,
           additional_markets}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    niche_entries = _NICHE_MARKETS.get(niche_n, [])

    primary = primary_market or dict(_DEFAULT_PRIMARY)

    additional: list[dict[str, Any]] = []
    for entry in niche_entries:
        (
            mname, handle, codes, currency, locale,
            rationale, when,
        ) = entry
        additional.append({
            "name": mname,
            "handle": handle,
            "country_codes": list(codes),
            "currency": currency,
            "locale": locale,
            "rationale": rationale,
            "when_to_open": when,
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "primary_market": primary,
        "additional_markets": additional,
    }


def hand_off_to_market_adapter(
    template: dict[str, Any],
) -> list[dict[str, Any]]:
    """Translate the recommendation into per-market
    kwargs ready for SHOPIFY_CREATE_MARKET.

    Excludes the primary market (already exists on every
    store by default). Returns one kwargs dict per
    additional market.

    Friendly call shape:
        {name, handle, status="active",
         regions: [{"country_code": "XX"}, ...]}
    """
    if (
        not isinstance(template, dict)
        or not template.get("additional_markets")
    ):
        return []
    out: list[dict[str, Any]] = []
    for m in template["additional_markets"]:
        if not isinstance(m, dict):
            continue
        out.append({
            "name": m["name"],
            "handle": m["handle"],
            "status": "active",
            "regions": [
                {"country_code": c}
                for c in m.get("country_codes", [])
            ],
        })
    return out


def render_markets_html(spec: dict[str, Any]) -> str:
    if not isinstance(spec, dict) or not spec.get(
        "primary_market",
    ):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    primary = spec.get("primary_market") or {}
    additional = spec.get("additional_markets") or []

    primary_block = (
        "<section class=\"primary-market\">"
        "<h2>Primary Market</h2>"
        "<dl>"
        f"<dt>Name</dt><dd>{html.escape(primary.get('name', ''))}</dd>"
        f"<dt>Countries</dt><dd><code>"
        f"{html.escape(', '.join(primary.get('country_codes', [])))}"
        "</code></dd>"
        f"<dt>Currency</dt><dd>{html.escape(primary.get('currency', ''))}</dd>"
        f"<dt>Locale</dt><dd>{html.escape(primary.get('locale', ''))}</dd>"
        "</dl></section>"
    )

    additional_rows: list[str] = []
    for m in additional:
        if not isinstance(m, dict):
            continue
        codes = ", ".join(m.get("country_codes", []))
        additional_rows.append(
            "<section class=\"additional-market\">"
            f"<h3>{html.escape(m.get('name', ''))}</h3>"
            "<dl>"
            f"<dt>Countries</dt><dd><code>{html.escape(codes)}</code></dd>"
            f"<dt>Currency</dt><dd>{html.escape(m.get('currency', ''))}</dd>"
            f"<dt>Locale</dt><dd>{html.escape(m.get('locale', ''))}</dd>"
            "<dt>When to open</dt>"
            f"<dd>{html.escape(m.get('when_to_open', ''))}</dd>"
            "<dt>Rationale</dt>"
            f"<dd>{html.escape(m.get('rationale', ''))}</dd>"
            "</dl></section>"
        )

    return (
        "<section class=\"market-recommendations\">"
        f"<h1>{name} -- Market &amp; Currency "
        "Recommendations</h1>"
        "<p>Per-niche international expansion "
        "recommendations. Apply via Shopify Admin -> "
        "Markets, or programmatically via "
        "<code>SHOPIFY_CREATE_MARKET</code>.</p>"
        + primary_block +
        (
            "<h2>Additional Markets</h2>"
            + "".join(additional_rows)
            if additional_rows else ""
        ) +
        "</section>"
    )


def apply_market_recommendations(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist recommendations as a Shopify page.

    Does NOT actually call SHOPIFY_CREATE_MARKET --
    market creation has scope + regulatory implications
    operators should review first. Use
    ``hand_off_to_market_adapter`` + manual router.execute
    for the actual write path.
    """
    if (
        not isinstance(spec, dict)
        or not spec.get("primary_market")
    ):
        return {
            "applied": False,
            "handle": _MARKETS_PAGE_HANDLE,
            "error": "no_market_spec",
        }

    body_html = render_markets_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _MARKETS_PAGE_HANDLE,
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
            "handle": _MARKETS_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _MARKETS_PAGE_TITLE,
        "handle": _MARKETS_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "locale_markets router.execute raised: %s",
            exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _MARKETS_PAGE_HANDLE,
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
            "handle": _MARKETS_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _MARKETS_PAGE_HANDLE,
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
    additional = spec.get("additional_markets") or []
    params: dict[str, Any] = {
        "handle": _MARKETS_PAGE_HANDLE,
        "additional_count": len(additional),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_market_recommendations",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _MARKETS_PAGE_HANDLE,
                "additional_count": len(additional),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "locale_markets record_writeback raised: %s",
            exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "locale_markets router import failed: %s",
            exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "locale_markets capability resolve failed: "
            "%s", exc,
        )
        return None
