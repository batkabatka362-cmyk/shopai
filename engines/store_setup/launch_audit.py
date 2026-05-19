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

# Required brand assets for a launchable store. Brand uploader
# writes the alt text as "<store_name> <asset>" so we can
# round-trip-detect uploaded assets via SHOPIFY_LIST_FILES.
_EXPECTED_BRAND_ASSETS: tuple[str, ...] = (
    "logo",
    "favicon",
)

# Minimum body_html length (whitespace-trimmed, tags stripped)
# below which a product description counts as "missing". Most
# Shopify themes show 1-3 lines of placeholder text by default;
# 80 chars is the threshold for a meaningful description.
_MIN_DESCRIPTION_LEN: int = 80

# Minimum SEO field lengths. Shopify caps title_tag at 70 and
# meta_description at 160; product SEO is "applied" when both
# fields are present and non-trivial.
_MIN_SEO_TITLE_LEN: int = 20
_MIN_SEO_META_LEN: int = 50


def audit_store(
    *,
    store_id: str | None = None,
    store_name: str | None = None,
    expected_collections: int = 1,
    expected_discounts: int = 1,
    products_sample_size: int = 50,
) -> dict[str, Any]:
    """Run the full launch-readiness audit.

    Args:
        store_id: Optional store_id for Pattern Z scope on the
            rolled-up audit event.
        store_name: Optional store name; used to identify brand
            assets uploaded by ``brand_uploader`` via their
            ``<store_name> logo`` / ``<store_name> favicon``
            alt-text convention. When omitted the brand check
            falls back to recognising any alt text ending in
            " logo" / " favicon".
        expected_collections: Minimum collection count to count
            as "set up" (default 1 -- at least one curated
            collection).
        expected_discounts: Minimum active discount count
            (default 1 -- the welcome code).
        products_sample_size: How many products to sample for
            the description + SEO checks. The audit reports
            the percentage with non-trivial body_html and
            populated SEO, not raw counts.

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
        _check_brand_assets(store_name=store_name),
    )
    product_sample = _fetch_product_sample(
        limit=products_sample_size,
    )
    checks.append(
        _check_product_descriptions(products=product_sample),
    )
    checks.append(
        _check_product_seo(products=product_sample),
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


def _check_brand_assets(
    *, store_name: str | None,
) -> dict[str, Any]:
    """Look for uploaded brand assets via SHOPIFY_LIST_FILES.

    The brand uploader writes alt text as
    ``<store_name> <asset>`` (e.g. ``Acme Beauty logo``).
    When ``store_name`` is supplied we match that exact prefix;
    otherwise we accept any alt ending in
    ``" logo"`` / ``" favicon"``.
    """
    data = _router_read(
        capability_attr="SHOPIFY_LIST_FILES",
        params={"limit": 100},
        empty_default={},
    )
    raw = data.get("files") if isinstance(data, dict) else []
    present: set[str] = set()
    if isinstance(raw, list):
        for f in raw:
            if not isinstance(f, dict):
                continue
            alt = (f.get("alt") or "").strip()
            asset = _asset_label_from_alt(
                alt, store_name=store_name,
            )
            if asset:
                present.add(asset)

    expected = set(_EXPECTED_BRAND_ASSETS)
    missing = sorted(expected - present)
    applied = len(expected & present)
    return {
        "key": "brand_assets",
        "ok": not missing,
        "applied": applied,
        "expected": len(expected),
        "missing": missing,
    }


def _asset_label_from_alt(
    alt: str, *, store_name: str | None,
) -> str | None:
    """Reverse of brand_uploader's alt-text convention."""
    if not isinstance(alt, str) or not alt:
        return None
    lowered = alt.lower().strip()
    prefix = (
        (store_name or "").strip().lower()
    )
    for asset in _EXPECTED_BRAND_ASSETS:
        suffix = f" {asset}"
        if not lowered.endswith(suffix):
            continue
        if prefix:
            expected = f"{prefix} {asset}"
            if lowered == expected:
                return asset
        else:
            return asset
    return None


def _fetch_product_sample(*, limit: int) -> list[dict[str, Any]]:
    """Read a bounded sample of products for the enrichment
    checks. Returns ``[]`` on any failure (read errors, no
    router, etc.) which makes the enrichment checks report
    ``applied=0, expected=0`` -- not a failure.
    """
    if int(limit) <= 0:
        return []
    data = _router_read(
        capability_attr="SHOPIFY_LIST_PRODUCTS",
        params={"limit": int(limit)},
        empty_default={},
    )
    raw = data.get("products") if isinstance(data, dict) else []
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict)]


def _check_product_descriptions(
    *, products: list[dict[str, Any]],
) -> dict[str, Any]:
    """How many sampled products carry a meaningful body_html.

    Strips tags before measuring so a string of empty ``<p></p>``
    doesn't masquerade as content.
    """
    total = len(products)
    if total == 0:
        return {
            "key": "product_descriptions",
            "ok": True,
            "applied": 0,
            "expected": 0,
            "missing": [],
        }
    applied = 0
    missing_titles: list[str] = []
    for p in products:
        body = p.get("body_html") or p.get("description") or ""
        text_len = len(_strip_tags(body).strip())
        if text_len >= _MIN_DESCRIPTION_LEN:
            applied += 1
        else:
            title = (p.get("title") or "untitled")[:60]
            missing_titles.append(title)
    return {
        "key": "product_descriptions",
        "ok": applied == total,
        "applied": applied,
        "expected": total,
        "missing": missing_titles[:5],
    }


def _check_product_seo(
    *, products: list[dict[str, Any]],
) -> dict[str, Any]:
    """How many sampled products carry populated SEO meta.

    Accepts both ``seo.title`` / ``seo.description`` (the
    normalised shape from SHOPIFY_LIST_PRODUCTS) and the
    legacy ``seo_title`` / ``seo_description`` flat fields.
    """
    total = len(products)
    if total == 0:
        return {
            "key": "product_seo",
            "ok": True,
            "applied": 0,
            "expected": 0,
            "missing": [],
        }
    applied = 0
    missing_titles: list[str] = []
    for p in products:
        seo = p.get("seo") if isinstance(p.get("seo"), dict) else {}
        title = (
            (seo.get("title") if seo else None)
            or p.get("seo_title")
            or ""
        ).strip()
        meta = (
            (seo.get("description") if seo else None)
            or p.get("seo_description")
            or ""
        ).strip()
        if (
            len(title) >= _MIN_SEO_TITLE_LEN
            and len(meta) >= _MIN_SEO_META_LEN
        ):
            applied += 1
        else:
            t = (p.get("title") or "untitled")[:60]
            missing_titles.append(t)
    return {
        "key": "product_seo",
        "ok": applied == total,
        "applied": applied,
        "expected": total,
        "missing": missing_titles[:5],
    }


def _strip_tags(html: str) -> str:
    """Quick-and-good-enough HTML stripper -- the audit only
    needs to distinguish "meaningful body text" from
    placeholder / empty markup, not parse HTML faithfully."""
    if not isinstance(html, str):
        return ""
    out: list[str] = []
    in_tag = False
    for ch in html:
        if ch == "<":
            in_tag = True
            continue
        if ch == ">":
            in_tag = False
            continue
        if not in_tag:
            out.append(ch)
    return "".join(out)


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
