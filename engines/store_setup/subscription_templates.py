"""Niche-aware subscription / selling-plan templates.

Subscriptions are the single biggest LTV lever in any
repeat-purchase category. Industry benchmarks:

  * Food + pets + baby essentials: 30-50% of orders
    can become subscriptions within 12 months.
  * Subscriber LTV: 5-10x one-time buyer LTV.
  * Subscription churn: 5-10% monthly is healthy;
    >15% signals product / pricing issues.

Default Shopify stores don't offer subscriptions until
the operator manually sets up selling plans (or installs
ReCharge / Bold / etc.). This delays the highest-value
revenue line.

This module ships niche-aware subscription PLAN
recommendations -- which products to subscribe-enable,
at what frequency, with what discount. Output is
operator-facing reference content (no
SHOPIFY_CREATE_SELLING_PLAN write adapter exists yet,
though the existing
``SHOPIFY_LIST_SELLING_PLAN_GROUPS`` /
``SHOPIFY_PAUSE_SUBSCRIPTION_CONTRACT`` etc. cover the
runtime ops).

Per-niche cadence guidance:
  * Food: weekly / bi-weekly (perishables), monthly
    (pantry).
  * Pets: monthly (food + treats), quarterly
    (supplements).
  * Baby: monthly (diapers + wipes + formula),
    quarterly (clothing).
  * Fitness: monthly (supplements), quarterly
    (apparel).
  * Beauty: monthly (routine consumables),
    quarterly (refills + tools).

Return shape from
:func:`generate_subscription_templates`::

    {
        "store_name": "Acme Pets",
        "niche": "pets",
        "plans": [
            {name, frequency, frequency_label,
             discount_pct, eligible_categories,
             cancel_policy, rationale, priority},
            ...
        ],
        "pitch_strategy": str,  # operator note
    }
"""
from __future__ import annotations

import html
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Per-niche subscription plan recommendations.
# Each entry tuple:
#   (name, frequency_iso, frequency_label, discount_pct,
#    eligible_categories, cancel_policy, rationale,
#    priority)
#
# frequency_iso uses ISO-8601 duration so the spec is
# drop-in for Shopify's `SellingPlan.deliveryPolicy.
# intervalCount + interval`.
_NICHE_PLANS: dict[
    str,
    list[tuple[
        str, str, str, int, list[str], str, str, int,
    ]],
] = {
    "beauty": [
        (
            "Monthly Routine Refill",
            "P1M", "every 30 days", 10,
            ["skincare", "haircare"],
            "Cancel or pause anytime in your account.",
            "Routine consumables (serum / cleanser / "
            "moisturiser) typically last 30-45 days. "
            "Monthly cadence prevents stockouts + "
            "subscriber churn from product gaps.",
            1,
        ),
        (
            "Quarterly Refresh",
            "P3M", "every 90 days", 5,
            ["makeup", "tools", "fragrance"],
            "Cancel or pause anytime.",
            "Lower-cadence items (mascara, brushes, "
            "fragrance) where monthly would oversupply.",
            2,
        ),
    ],
    "fashion": [
        (
            "New Drops Subscription",
            "P1M", "every 30 days", 10,
            ["new-arrivals"],
            "Skip a month or cancel anytime.",
            "Curated new-drops box -- subscriber gets "
            "first access to limited drops. Drives "
            "FOMO + retention.",
            1,
        ),
    ],
    "tech": [
        (
            "Accessory Refresh",
            "P3M", "every 90 days", 5,
            ["accessories", "cables-power"],
            "Cancel anytime.",
            "Cables, cases, screen protectors wear out "
            "predictably. Low-AOV consumables = "
            "subscription target.",
            2,
        ),
    ],
    "home": [
        (
            "Seasonal Refresh",
            "P3M", "every 90 days", 5,
            ["candles", "throws", "linens"],
            "Skip a season or cancel anytime.",
            "Home goods rotate by season. Quarterly "
            "cadence aligns with how customers "
            "actually restock decorative items.",
            1,
        ),
    ],
    "food": [
        (
            "Weekly Fresh",
            "P1W", "every 7 days", 10,
            ["fresh", "produce", "prepared-meals"],
            "Skip a week or cancel anytime.",
            "Perishable items need weekly cadence -- "
            "monthly is too long for fresh + meal kits.",
            1,
        ),
        (
            "Bi-Weekly Pantry",
            "P2W", "every 14 days", 10,
            ["pantry", "drinks"],
            "Skip or cancel anytime.",
            "Pantry essentials (coffee / tea / sauces) "
            "consumed faster than monthly but slower "
            "than weekly.",
            2,
        ),
        (
            "Monthly Specialty",
            "P1M", "every 30 days", 15,
            ["specialty", "gifts", "single-origin"],
            "Skip or cancel anytime.",
            "Higher-AOV specialty items where monthly "
            "frequency + bigger discount drives "
            "high-LTV subscribers.",
            3,
        ),
    ],
    "pets": [
        (
            "Monthly Food",
            "P1M", "every 30 days", 10,
            ["food", "treats"],
            "Skip a month or cancel anytime. We auto-"
            "pause if your card declines.",
            "Pet food is the canonical subscription "
            "product -- 40% subscription attach rate "
            "is typical. Monthly cadence matches "
            "average bag duration for medium dogs.",
            1,
        ),
        (
            "Quarterly Supplements",
            "P3M", "every 90 days", 10,
            ["supplements", "dental"],
            "Cancel anytime.",
            "Supplements + dental chews last longer; "
            "quarterly avoids oversupply.",
            2,
        ),
    ],
    "fitness": [
        (
            "Monthly Supplements",
            "P1M", "every 30 days", 10,
            ["supplements", "protein"],
            "Skip or cancel anytime.",
            "Protein + pre-workout consumed in 30-day "
            "tubs. Monthly cadence + 10% off matches "
            "the category default.",
            1,
        ),
        (
            "Quarterly Apparel",
            "P3M", "every 90 days", 15,
            ["apparel"],
            "Cancel anytime.",
            "Apparel doesn't need monthly delivery; "
            "quarterly drop with a bigger discount "
            "drives committed-athlete LTV.",
            2,
        ),
    ],
    "jewelry": [
        # Jewelry doesn't typically subscribe; one
        # exception is care-product replenishment
        (
            "Care Kit Refresh",
            "P6M", "every 180 days", 10,
            ["care-products"],
            "Cancel anytime.",
            "Cleaning solutions + polishing cloths "
            "wear out on 6-month cadence. Niche "
            "subscription play.",
            3,
        ),
    ],
    "outdoor": [
        (
            "Seasonal Gear Drop",
            "P3M", "every 90 days", 5,
            ["seasonal"],
            "Skip a season or cancel anytime.",
            "Seasonal gear rotation -- spring / summer "
            "/ fall / winter alignment with how "
            "outdoor enthusiasts plan trips.",
            2,
        ),
    ],
    "baby": [
        (
            "Monthly Essentials",
            "P1M", "every 30 days", 10,
            ["diapers", "wipes", "formula"],
            "Skip a month or cancel anytime. Auto-"
            "scale: as your baby moves stages, the "
            "size auto-updates.",
            "Diapers + wipes + formula are the "
            "canonical baby subscription. Monthly "
            "cadence + auto-stage-update reduces "
            "operator support load.",
            1,
        ),
        (
            "Quarterly Clothing Box",
            "P3M", "every 90 days", 15,
            ["clothing"],
            "Skip or cancel anytime.",
            "Babies grow fast -- quarterly "
            "size-appropriate box drives strong LTV "
            "in 0-24 month range.",
            2,
        ),
    ],
    "general": [
        (
            "Monthly Auto-Refresh",
            "P1M", "every 30 days", 10,
            ["best-sellers"],
            "Cancel anytime.",
            "Generic monthly fallback for any "
            "consumable category.",
            1,
        ),
    ],
}


# Per-niche pitch strategy -- where to surface the
# subscription pitch in the customer journey.
_PITCH_STRATEGIES: dict[str, str] = {
    "beauty": (
        "PDP toggle (one-time vs subscribe + save) "
        "on every consumable. Subscription pitch "
        "email after order 2."
    ),
    "fashion": (
        "Subscription pitch above the fold on "
        "the homepage for new-drops audience. "
        "Optional add-on in cart."
    ),
    "tech": (
        "Subtle bundle option on PDP for "
        "consumable accessories (cables / cases). "
        "Skip aggressive pitch -- tech buyers are "
        "subscription-skeptical."
    ),
    "home": (
        "Seasonal email campaign (4 per year) "
        "pitching the seasonal-refresh box."
    ),
    "food": (
        "Subscription pitch ABOVE the fold on PDP, "
        "homepage hero, AND email after order 2. "
        "Highest-LTV play in the category."
    ),
    "pets": (
        "Subscribe-and-save toggle on every food "
        "PDP. Pitch in welcome email + post-purchase "
        "email. ~40% attach rate is achievable."
    ),
    "fitness": (
        "PDP toggle on every supplement. Auto-"
        "show subscription pitch after order 2."
    ),
    "jewelry": (
        "Don't surface subscription on the homepage. "
        "Only pitch care-kit refresh in post-purchase "
        "email after first piece."
    ),
    "outdoor": (
        "Seasonal subscription email (4 per year). "
        "Don't push subscription on the homepage."
    ),
    "baby": (
        "Subscribe-and-save toggle on every "
        "consumable PDP. Pitch in welcome series + "
        "in the order confirmation post-receipt "
        "block. Highest LTV play for new parents."
    ),
    "general": (
        "Generic monthly pitch in welcome series "
        "+ PDP toggle on bestsellers."
    ),
}


_SUBSCRIPTION_PAGE_TITLE: str = "Subscription Plans"
_SUBSCRIPTION_PAGE_HANDLE: str = "subscription-plans"


def generate_subscription_templates(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build niche-aware subscription plan recommendations.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.

    Returns:
        ``{store_name, niche, plans, pitch_strategy}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    raw_plans = _NICHE_PLANS.get(
        niche_n, _NICHE_PLANS["general"],
    )
    strategy = _PITCH_STRATEGIES.get(
        niche_n, _PITCH_STRATEGIES["general"],
    )

    plans: list[dict[str, Any]] = []
    for entry in raw_plans:
        (
            pname, freq_iso, freq_label, discount,
            categories, cancel, rationale, priority,
        ) = entry
        plans.append({
            "name": pname,
            "frequency": freq_iso,
            "frequency_label": freq_label,
            "discount_pct": int(discount),
            "eligible_categories": list(categories),
            "cancel_policy": cancel,
            "rationale": rationale,
            "priority": int(priority),
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "plans": plans,
        "pitch_strategy": strategy,
    }


def render_subscription_html(
    spec: dict[str, Any],
) -> str:
    if not isinstance(spec, dict) or not spec.get(
        "plans",
    ):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    plans = spec.get("plans") or []
    strategy = html.escape(
        spec.get("pitch_strategy", "") or "",
    )

    sections: list[str] = []
    for p in plans:
        if not isinstance(p, dict):
            continue
        categories = ", ".join(
            html.escape(c)
            for c in p.get("eligible_categories", [])
        )
        sections.append(
            "<section class=\"subscription-plan\">"
            f"<h2>{html.escape(p.get('name', ''))} "
            f"(priority {p.get('priority', 0)})</h2>"
            "<dl>"
            f"<dt>Frequency</dt>"
            f"<dd>{html.escape(p.get('frequency_label', ''))} "
            f"(<code>{html.escape(p.get('frequency', ''))}</code>)</dd>"
            f"<dt>Discount</dt>"
            f"<dd>{p.get('discount_pct', 0)}% off</dd>"
            f"<dt>Eligible Categories</dt>"
            f"<dd>{categories}</dd>"
            f"<dt>Cancel Policy</dt>"
            f"<dd>{html.escape(p.get('cancel_policy', ''))}</dd>"
            f"<dt>Rationale</dt>"
            f"<dd>{html.escape(p.get('rationale', ''))}</dd>"
            "</dl></section>"
        )

    return (
        "<section class=\"subscription-plans\">"
        f"<h1>{name} -- Subscription Plans</h1>"
        f"<p><strong>Pitch strategy:</strong> "
        f"{strategy}</p>"
        + "".join(sections) +
        "</section>"
    )


def apply_subscription_templates(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist as Shopify page
    ``subscription-plans``.

    No selling-plan write adapter exists; the operator
    pastes the plan configuration into Shopify Admin's
    Selling Plans section manually (or installs ReCharge
    / Bold / Skio etc.).
    """
    if not isinstance(spec, dict) or not spec.get(
        "plans",
    ):
        return {
            "applied": False,
            "handle": _SUBSCRIPTION_PAGE_HANDLE,
            "error": "no_subscription_spec",
        }

    body_html = render_subscription_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _SUBSCRIPTION_PAGE_HANDLE,
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
            "handle": _SUBSCRIPTION_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _SUBSCRIPTION_PAGE_TITLE,
        "handle": _SUBSCRIPTION_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "subscription_templates router.execute "
            "raised: %s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _SUBSCRIPTION_PAGE_HANDLE,
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
            "handle": _SUBSCRIPTION_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _SUBSCRIPTION_PAGE_HANDLE,
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
    plans = spec.get("plans") or []
    params: dict[str, Any] = {
        "handle": _SUBSCRIPTION_PAGE_HANDLE,
        "plan_count": len(plans),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_subscription_templates",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _SUBSCRIPTION_PAGE_HANDLE,
                "plan_count": len(plans),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "subscription_templates record_writeback "
            "raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "subscription_templates router import "
            "failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "subscription_templates capability "
            "resolve failed: %s", exc,
        )
        return None
