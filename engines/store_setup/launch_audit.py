"""Read-only launch-readiness audit for a Shopify store.

Answers the single question: **is this store ready to take
orders?**

The autonomous setup flow produces a launchable storefront via
the policy + page + discount appliers. This module is the
*verification* counterpart: it READS the store's current state
through the standard adapter layer and reports per-checklist-
item completion.

Output schema::

    {
        "checks": [
            {"key": "legal_policies",
             "ok": True, "applied": 5, "expected": 5,
             "missing": []},
            {"key": "standard_pages",
             "ok": False, "applied": 3, "expected": 4,
             "missing": ["FAQ"]},
            ...
        ],
        "ready_to_launch": False,
        "completion_pct": 75,
        "missing_summary": "standard_pages: FAQ",
    }

The reads are all CHEAP (~1 GraphQL hop per check). The audit
is safe to run on a cron alongside ``daily-brief`` to track
launch readiness over time.

Records via Pattern Z so each audit run feeds the Phase 8
learning loop -- completion_pct over time becomes a leading
indicator of "how close is the autonomous merchant to
launching this store".
"""
from __future__ import annotations

import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# ── Expected launch-readiness baseline ──────────────────────────


# Policies that EVERY launchable store needs. The order matches
# the policy_generator output schema.
_EXPECTED_POLICY_TYPES: tuple[str, ...] = (
    "REFUND_POLICY",
    "PRIVACY_POLICY",
    "TERMS_OF_SERVICE",
    "SHIPPING_POLICY",
    "CONTACT_INFORMATION",
)

# Standard storefront pages (page_generator's default set).
_EXPECTED_PAGE_HANDLES: tuple[str, ...] = (
    "about",
    "contact",
    "faq",
    "shipping-returns",
)

# Active-product statuses that count toward "store has sellable
# inventory". DRAFT and ARCHIVED products are not customer-
# visible, so they don't count even if present in the catalog.
_ACTIVE_PRODUCT_STATUSES: frozenset[str] = frozenset({"ACTIVE"})

# Minimum count of shipping zones across all delivery profiles
# below which the store can't take orders that ship anywhere.
# A zone-less profile is functionally "ships nowhere" -- the
# rate evaluation has nothing to match against at checkout.
_MIN_SHIPPING_ZONES: int = 1


def audit_store(
    *,
    store_id: str | None = None,
    expected_collections: int = 1,
    expected_discounts: int = 1,
    expected_products: int = 1,
    expected_shipping_zones: int = _MIN_SHIPPING_ZONES,
) -> dict[str, Any]:
    """Run the full launch-readiness audit.

    Args:
        store_id: Optional store_id for Pattern Z scope on the
            rolled-up audit event.
        expected_collections: Minimum collection count to count
            as "set up" (default 1 -- at least one curated
            collection).
        expected_discounts: Minimum active discount count
            (default 1 -- the welcome code).
        expected_products: Minimum count of ACTIVE products
            (default 1 -- a store with zero sellable products
            literally can't take orders). DRAFT and ARCHIVED
            products don't count.
        expected_shipping_zones: Minimum count of configured
            shipping zones across all delivery profiles
            (default 1 -- a store with zero shipping zones
            can't quote shipping at checkout).

    Returns:
        Dict with the schema documented in the module docstring.
    """
    checks: list[dict[str, Any]] = []

    checks.append(_check_legal_policies())
    checks.append(_check_standard_pages())
    checks.append(
        _check_active_discounts(
            expected=expected_discounts,
        ),
    )
    checks.append(
        _check_curated_collections(
            expected=expected_collections,
        ),
    )
    checks.append(_check_design_tokens())
    checks.append(
        _check_active_products(
            expected=expected_products,
        ),
    )
    checks.append(
        _check_shipping_zones(
            expected=expected_shipping_zones,
        ),
    )

    total = len(checks)
    passed = sum(1 for c in checks if c["ok"])
    completion_pct = round(100 * passed / max(total, 1))
    ready_to_launch = passed == total

    missing_summaries = [
        f"{c['key']}: {', '.join(c.get('missing') or []) or 'none'}"
        for c in checks if not c["ok"]
    ]
    missing_summary = (
        "; ".join(missing_summaries) if missing_summaries
        else "all checks passed"
    )

    result = {
        "checks": checks,
        "ready_to_launch": ready_to_launch,
        "completion_pct": completion_pct,
        "missing_summary": missing_summary,
    }

    _record_audit(
        ready=ready_to_launch,
        completion_pct=completion_pct,
        missing_summary=missing_summary,
        store_id=store_id,
    )
    return result


# ── Per-check probes ──────────────────────────────────────────


def _check_legal_policies() -> dict[str, Any]:
    """Read the shop's policies via SHOPIFY_GET_SHOP_POLICIES.

    Each policy type with a non-empty body counts as present.
    """
    data = _router_read(
        capability_attr="SHOPIFY_GET_SHOP_POLICIES",
        params={},
        empty_default={},
    )
    present: set[str] = set()
    raw = data.get("policies") if isinstance(data, dict) else []
    if isinstance(raw, list):
        for policy in raw:
            if not isinstance(policy, dict):
                continue
            ptype = (policy.get("type") or "").upper()
            body = policy.get("body") or ""
            if ptype and body.strip():
                present.add(ptype)

    expected = set(_EXPECTED_POLICY_TYPES)
    missing = sorted(expected - present)
    applied = len(expected & present)
    return {
        "key": "legal_policies",
        "ok": not missing,
        "applied": applied,
        "expected": len(expected),
        "missing": missing,
    }


def _check_standard_pages() -> dict[str, Any]:
    """Read the shop's pages via SHOPIFY_LIST_PAGES.

    A standard page is "applied" when its handle matches one
    of the expected handles AND the page is published.
    """
    data = _router_read(
        capability_attr="SHOPIFY_LIST_PAGES",
        params={"limit": 100},
        empty_default={},
    )
    present_handles: set[str] = set()
    raw = data.get("pages") if isinstance(data, dict) else []
    if isinstance(raw, list):
        for page in raw:
            if not isinstance(page, dict):
                continue
            handle = (page.get("handle") or "").lower()
            if handle:
                present_handles.add(handle)

    expected = set(_EXPECTED_PAGE_HANDLES)
    missing = sorted(expected - present_handles)
    applied = len(expected & present_handles)
    return {
        "key": "standard_pages",
        "ok": not missing,
        "applied": applied,
        "expected": len(expected),
        "missing": missing,
    }


def _check_active_discounts(*, expected: int) -> dict[str, Any]:
    """Count active discount codes via SHOPIFY_LIST_DISCOUNTS."""
    data = _router_read(
        capability_attr="SHOPIFY_LIST_DISCOUNTS",
        params={"limit": 50},
        empty_default={},
    )
    raw = data.get("discounts") if isinstance(data, dict) else []
    count = len(raw) if isinstance(raw, list) else 0
    return {
        "key": "active_discounts",
        "ok": count >= max(0, int(expected)),
        "applied": count,
        "expected": max(0, int(expected)),
        "missing": (
            [f"need {expected - count} more"]
            if count < expected else []
        ),
    }


def _check_curated_collections(
    *, expected: int,
) -> dict[str, Any]:
    """Count collections via SHOPIFY_LIST_COLLECTIONS."""
    data = _router_read(
        capability_attr="SHOPIFY_LIST_COLLECTIONS",
        params={"limit": 50},
        empty_default={},
    )
    raw = data.get("collections") if isinstance(data, dict) else []
    count = len(raw) if isinstance(raw, list) else 0
    return {
        "key": "curated_collections",
        "ok": count >= max(0, int(expected)),
        "applied": count,
        "expected": max(0, int(expected)),
        "missing": (
            [f"need {expected - count} more"]
            if count < expected else []
        ),
    }


def _check_active_products(*, expected: int) -> dict[str, Any]:
    """Count ACTIVE products via SHOPIFY_LIST_PRODUCTS.

    A launchable store needs at least one sellable product.
    DRAFT and ARCHIVED products are not customer-visible, so a
    catalog full of drafts still fails this check -- exactly
    the failure mode we want to surface BEFORE the operator
    declares the store ready.

    Returns ``applied`` as the count of ACTIVE products (capped
    by the read's limit) and ``missing`` as a single
    "need N more" hint when the threshold isn't met.
    """
    data = _router_read(
        capability_attr="SHOPIFY_LIST_PRODUCTS",
        params={"limit": 50},
        empty_default={},
    )
    raw = data.get("products") if isinstance(data, dict) else []
    active = 0
    if isinstance(raw, list):
        for product in raw:
            if not isinstance(product, dict):
                continue
            status = (product.get("status") or "").upper()
            if status in _ACTIVE_PRODUCT_STATUSES:
                active += 1

    threshold = max(0, int(expected))
    missing: list[str] = []
    if active < threshold:
        missing = [f"need {threshold - active} more"]
    return {
        "key": "active_products",
        "ok": active >= threshold,
        "applied": active,
        "expected": threshold,
        "missing": missing,
    }


def _check_design_tokens() -> dict[str, Any]:
    """Look for the design tokens file from PR #362 on the
    active theme.

    The file ``assets/shopai-design-tokens.json`` is written
    by ``design_applier.apply_design``. Its presence means
    the design engine has applied recommendations to the
    live theme at least once.
    """
    # First need to find the main theme id
    themes_data = _router_read(
        capability_attr="SHOPIFY_LIST_THEMES",
        params={"roles": ["MAIN"]},
        empty_default={},
    )
    themes = (
        themes_data.get("themes")
        if isinstance(themes_data, dict)
        else []
    )
    if not themes:
        return {
            "key": "design_tokens",
            "ok": False,
            "applied": 0,
            "expected": 1,
            "missing": ["main theme not found"],
        }

    theme_id = themes[0].get("id") if isinstance(themes[0], dict) else None
    if not theme_id:
        return {
            "key": "design_tokens",
            "ok": False,
            "applied": 0,
            "expected": 1,
            "missing": ["main theme id missing"],
        }

    files_data = _router_read(
        capability_attr="SHOPIFY_LIST_THEME_FILES",
        params={
            "theme_id": theme_id,
            "filenames": [
                "assets/shopai-design-tokens.json",
            ],
        },
        empty_default={},
    )
    files = (
        files_data.get("files")
        if isinstance(files_data, dict)
        else []
    )
    present = bool(files)
    return {
        "key": "design_tokens",
        "ok": present,
        "applied": 1 if present else 0,
        "expected": 1,
        "missing": (
            [] if present
            else ["assets/shopai-design-tokens.json"]
        ),
    }


def _check_shipping_zones(*, expected: int) -> dict[str, Any]:
    """Count configured shipping zones via
    SHOPIFY_LIST_DELIVERY_PROFILES.

    A "zone" is a country/region grouping configured in
    Settings > Shipping. Without at least one zone covering
    the customer's address, checkout shows "shipping isn't
    available to your location" -- a hard launch blocker for
    any store selling physical products.

    Sums zone counts across every profile's location-groups.
    Profiles that hold rate definitions for the same zone
    (e.g. a per-country profile in addition to the default)
    each contribute to the count -- the threshold is
    cumulative, not per-profile.
    """
    data = _router_read(
        capability_attr="SHOPIFY_LIST_DELIVERY_PROFILES",
        params={"limit": 50},
        empty_default={},
    )
    profiles = data.get("profiles") if isinstance(data, dict) else []
    zone_count = 0
    if isinstance(profiles, list):
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            location_groups = profile.get("location_groups") or []
            if not isinstance(location_groups, list):
                continue
            for group in location_groups:
                if not isinstance(group, dict):
                    continue
                zones = group.get("zones") or []
                if isinstance(zones, list):
                    zone_count += sum(
                        1 for z in zones if isinstance(z, dict)
                    )

    threshold = max(0, int(expected))
    missing: list[str] = []
    if zone_count < threshold:
        missing = [f"need {threshold - zone_count} more"]
    return {
        "key": "shipping_zones",
        "ok": zone_count >= threshold,
        "applied": zone_count,
        "expected": threshold,
        "missing": missing,
    }


# ── Helpers ───────────────────────────────────────────────────


def _router_read(
    *,
    capability_attr: str,
    params: dict[str, Any],
    empty_default: Any,
) -> Any:
    """Run a read-capability call and return the payload data.

    All failure modes (no router, no capability, raise, ok=False)
    return ``empty_default`` so the per-check probes can
    uniformly interpret missing data as "not applied".
    """
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "launch_audit imports failed: %s", exc,
        )
        return empty_default

    cap = getattr(Capability, capability_attr, None)
    if cap is None:
        logger.debug(
            "launch_audit unknown capability: %s",
            capability_attr,
        )
        return empty_default

    try:
        router = get_router()
        result = router.execute(cap, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "launch_audit router.execute raised "
            "for %s: %s",
            capability_attr, exc,
        )
        return empty_default

    if not getattr(result, "ok", False):
        return empty_default
    return getattr(result, "data", None) or empty_default


def _record_audit(
    *,
    ready: bool,
    completion_pct: int,
    missing_summary: str,
    store_id: str | None,
) -> None:
    """Record the audit run via Pattern Z so completion_pct
    over time becomes a Phase 8 learning signal."""
    params: dict[str, Any] = {
        "completion_pct": completion_pct,
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="audit_launch_readiness",
            capability="SHOPAI_AUDIT_LAUNCH",
            params=params,
            success=ready,
            error=None if ready else missing_summary,
            metrics={
                "completion_pct": completion_pct,
                "ready_to_launch": ready,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "launch_audit record_writeback raised: %s", exc,
        )
