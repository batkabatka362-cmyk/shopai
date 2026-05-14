"""Bundle Engine — Shopify bundle-product applier.

The bundle engine emits ``{bundles, best_bundle,
cannibalization_risk}``. ``best_bundle`` is the
highest-uplift bundle proposal carrying component product
ids/titles, bundle price, savings_pct, and estimated
revenue uplift. Pre-fix that proposal was advisory — the
merchant had to create a Shopify product, set up the
component links, and write the body copy by hand.

This applier closes the loop. When opt-in is set and the
guardrails clear, create a DRAFT Shopify product representing
the bundle via SHOPIFY_CREATE_PRODUCT — title summarises the
components, body copy lists each component with the savings
breakdown, tags include ``shopai-bundle`` plus one
``shopai-bundle-component-{pid}`` per component product so
the merchant can filter the admin by bundle membership.

DRAFT-by-default (not auto-published) because:
  * Cross-product linking (real component-tracking via the
    Shopify Bundles app's ``productBundleCreate``) isn't in
    the adapter layer yet — the merchant still needs to wire
    components manually before publishing.
  * Auto-publishing a bundle could conflict with existing
    listings; defer that judgement to the merchant.

Two opt-in modes match the Phase 6/7 pattern:

  data.apply_bundle=True + data.require_approval=False
    → SHOPIFY_CREATE_PRODUCT immediately
  data.apply_bundle=True + data.require_approval=True
    → enqueue to core.approval; merchant approves before the
      mutation lands

Skipped (no API call / no queue entry) when:
  * ``best_bundle`` is missing or has fewer than 2 component
    products (a "bundle of one" is just a product).
  * ``savings_pct`` <= 0 — no actual saving, no compelling
    reason to bundle.
  * The bundle's cannibalization recommendation is
    ``reconsider_bundle`` (high risk — would steal sales
    from existing listings without offsetting uplift).
  * Router unavailable / adapter rejects (direct path).
  * Approval queue unavailable (approval path).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.bundle.applier")


_DEFAULT_STATUS = "DRAFT"
_BUNDLE_TAG = "shopai-bundle"
_COMPONENT_TAG_PREFIX = "shopai-bundle-component-"
_BLOCKED_RECOMMENDATION = "reconsider_bundle"
_MIN_COMPONENT_COUNT = 2


def apply_bundle_product(
    best_bundle: dict[str, Any] | None,
    cannibalization_risk: list[dict[str, Any]],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Create a DRAFT Shopify product representing the bundle.

    Args:
        best_bundle: Per-bundle dict carrying ``product_ids``,
            ``product_titles``, ``bundle_price``,
            ``savings_pct``, ``estimated_uplift``, optionally
            ``bundle_id`` (used to look up cannibalization).
        cannibalization_risk: List of cannibalization-checker
            results; the entry whose ``bundle_id`` matches the
            best bundle is consulted for the
            ``reconsider_bundle`` guard.
        store: Optional config — currently unused, reserved
            for future status/tag overrides.

    Returns:
        ``{"applied", "bundle_product_id", "title", "components",
        "savings_pct", "status", "error"}`` on success or
        structured skip; ``None`` only when the upfront
        guardrails reject before any router work.
    """
    proposal = _build_proposal(best_bundle, cannibalization_risk, store)
    if proposal is None:
        return None

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        return {
            "applied": False,
            "bundle_product_id": "",
            "title": proposal["title"],
            "components": proposal["components"],
            "savings_pct": proposal["savings_pct"],
            "status": _DEFAULT_STATUS,
            "error": "router_unavailable",
        }

    recorder_params = {
        "title": proposal["title"],
        "component_count": len(proposal["components"]),
        "savings_pct": proposal["savings_pct"],
        "bundle_price": proposal["bundle_price"],
    }
    try:
        result = router.execute(capability, proposal["adapter_params"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("apply_bundle_product raised: %s", exc)
        record_writeback(
            engine="bundle",
            action_type="apply_bundle_product",
            capability="SHOPIFY_CREATE_PRODUCT",
            params=recorder_params,
            success=False,
            error=f"adapter_raised: {exc}",
        )
        return {
            "applied": False,
            "bundle_product_id": "",
            "title": proposal["title"],
            "components": proposal["components"],
            "savings_pct": proposal["savings_pct"],
            "status": _DEFAULT_STATUS,
            "error": f"adapter_raised: {exc}",
        }

    if not getattr(result, "ok", False):
        err = getattr(result, "error", "unknown")
        record_writeback(
            engine="bundle",
            action_type="apply_bundle_product",
            capability="SHOPIFY_CREATE_PRODUCT",
            params=recorder_params,
            success=False,
            error=f"adapter_failed: {err}",
        )
        return {
            "applied": False,
            "bundle_product_id": "",
            "title": proposal["title"],
            "components": proposal["components"],
            "savings_pct": proposal["savings_pct"],
            "status": _DEFAULT_STATUS,
            "error": f"adapter_failed: {err}",
        }

    data = getattr(result, "data", {}) or {}
    product = data.get("product") or {}
    record_writeback(
        engine="bundle",
        action_type="apply_bundle_product",
        capability="SHOPIFY_CREATE_PRODUCT",
        params=recorder_params,
        success=True,
    )
    return {
        "applied": True,
        "bundle_product_id": product.get("id", "") or "",
        "title": product.get("title", proposal["title"]),
        "components": proposal["components"],
        "savings_pct": proposal["savings_pct"],
        "status": product.get("status", _DEFAULT_STATUS),
        "error": None,
    }


def enqueue_bundle_for_approval(
    best_bundle: dict[str, Any] | None,
    cannibalization_risk: list[dict[str, Any]],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Park the bundle proposal in the approval queue.

    Same upfront guards as :func:`apply_bundle_product`. Returns
    the standard ``{pending_action_id, narrative, params}`` shape
    used across Phase 6/7 enqueue helpers; ``None`` on guardrail
    rejection or queue failure.
    """
    proposal = _build_proposal(best_bundle, cannibalization_risk, store)
    if proposal is None:
        return None

    components_summary = ", ".join(
        c["title"] for c in proposal["components"][:3]
    )
    if len(proposal["components"]) > 3:
        components_summary += f", +{len(proposal['components']) - 3}"

    narrative = (
        f"Create DRAFT bundle product '{proposal['title']}': "
        f"{len(proposal['components'])} components "
        f"({components_summary}), "
        f"{proposal['savings_pct']:g}% off, "
        f"~{proposal['estimated_uplift']:.2f}x uplift"
    )
    params = {
        "title": proposal["title"],
        "components": proposal["components"],
        "bundle_price": proposal["bundle_price"],
        "savings_pct": proposal["savings_pct"],
        "estimated_uplift": proposal["estimated_uplift"],
        "adapter_params": proposal["adapter_params"],
    }

    try:
        from core.approval import get_approval_queue
        action = get_approval_queue().enqueue(
            engine="bundle",
            action_type="apply_bundle_product",
            capability="SHOPIFY_CREATE_PRODUCT",
            params=params,
            narrative=narrative,
        )
    except Exception:  # noqa: BLE001
        return None

    return {
        "pending_action_id": action.id,
        "narrative": narrative,
        "params": params,
    }


# ── Proposal builder ──────────────────────────────────────────


def _build_proposal(
    best_bundle: dict[str, Any] | None,
    cannibalization_risk: list[dict[str, Any]] | None,
    store: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate inputs and assemble the adapter-ready proposal.

    Returns ``None`` when any guardrail rejects (no bundle, too
    few components, no savings, blocked-cannibalization
    recommendation).
    """
    if not isinstance(best_bundle, dict) or not best_bundle:
        return None

    product_ids = best_bundle.get("product_ids") or []
    product_titles = best_bundle.get("product_titles") or []
    if not isinstance(product_ids, list) or not isinstance(
        product_titles, list,
    ):
        return None
    components = _pair_components(product_ids, product_titles)
    if len(components) < _MIN_COMPONENT_COUNT:
        return None

    savings_pct = _safe_float(best_bundle.get("savings_pct")) or 0.0
    if savings_pct <= 0:
        return None

    bundle_price = _safe_float(best_bundle.get("bundle_price")) or 0.0
    estimated_uplift = (
        _safe_float(best_bundle.get("estimated_uplift")) or 0.0
    )

    if _is_blocked_by_cannibalization(
        best_bundle, cannibalization_risk,
    ):
        return None

    title = _build_title(components)
    body_html = _build_body(components, savings_pct, bundle_price)
    tags = [_BUNDLE_TAG] + [
        f"{_COMPONENT_TAG_PREFIX}{_short_id(c['id'])}"
        for c in components
    ]

    adapter_params: dict[str, Any] = {
        "title": title,
        "status": _DEFAULT_STATUS,
        "product_type": "Bundle",
        "tags": tags,
        "body_html": body_html,
    }
    return {
        "title": title,
        "components": components,
        "bundle_price": bundle_price,
        "savings_pct": savings_pct,
        "estimated_uplift": estimated_uplift,
        "adapter_params": adapter_params,
    }


def _pair_components(
    product_ids: list[Any], product_titles: list[Any],
) -> list[dict[str, str]]:
    """Build per-component ``{id, title}`` pairs.

    Lists may have different lengths if the engine partially
    resolved titles; pair by index, drop entries with blank
    ids. Missing titles fall back to a short id label.
    """
    pairs: list[dict[str, str]] = []
    max_len = min(len(product_ids), len(product_titles))
    for i in range(max_len):
        pid = str(product_ids[i] or "").strip()
        if not pid:
            continue
        title = str(product_titles[i] or "").strip()
        if not title:
            title = f"Product {_short_id(pid)}"
        pairs.append({"id": pid, "title": title})
    # Handle the case where ids list is longer than titles.
    for j in range(max_len, len(product_ids)):
        pid = str(product_ids[j] or "").strip()
        if not pid:
            continue
        pairs.append({
            "id": pid,
            "title": f"Product {_short_id(pid)}",
        })
    return pairs


def _is_blocked_by_cannibalization(
    best_bundle: dict[str, Any],
    cannibalization_risk: list[dict[str, Any]] | None,
) -> bool:
    """Match best_bundle.bundle_id to the cannibalization
    results and reject when the recommendation is
    ``reconsider_bundle``. When no matching entry exists,
    default to allowing (the optimizer ranked it as best, so
    absence of a cannibalization verdict is treated as the
    safer default rather than a blanket rejection).
    """
    if not isinstance(cannibalization_risk, list):
        return False
    bid = best_bundle.get("bundle_id")
    if not bid:
        return False
    for entry in cannibalization_risk:
        if not isinstance(entry, dict):
            continue
        if entry.get("bundle_id") != bid:
            continue
        rec = str(entry.get("recommendation", "")).lower()
        return rec == _BLOCKED_RECOMMENDATION
    return False


def _build_title(components: list[dict[str, str]]) -> str:
    """``Bundle: A + B`` for 2 items, ``Bundle: A + B + C`` for
    3+, capped at 3 with ``+N more`` when longer."""
    names = [c["title"] for c in components[:3]]
    base = " + ".join(names)
    if len(components) > 3:
        base += f" + {len(components) - 3} more"
    return f"Bundle: {base}"


def _build_body(
    components: list[dict[str, str]],
    savings_pct: float,
    bundle_price: float,
) -> str:
    """Plain-HTML body summarising components and savings.

    Body HTML is the safest input shape — Shopify renders it
    on the storefront and the merchant can hand-edit later.
    """
    items = "".join(
        f"<li>{c['title']}</li>" for c in components
    )
    return (
        f"<p>Bundle includes {len(components)} products at "
        f"<strong>{savings_pct:g}% off</strong> "
        f"(${bundle_price:.2f}):</p>"
        f"<ul>{items}</ul>"
    )


def _short_id(gid: str) -> str:
    """Take the numeric tail of a Shopify GID for slug use.

    ``gid://shopify/Product/12345`` → ``12345``
    Blank / non-GID input falls back to the original string,
    truncated to 16 chars.
    """
    if not gid:
        return "unknown"
    tail = gid.rstrip("/").rsplit("/", 1)[-1] or gid
    safe = "".join(c for c in tail if c.isalnum())
    return safe[:16] or "unknown"


def _safe_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# ── Router boilerplate ────────────────────────────────────────


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router
    except Exception as exc:  # noqa: BLE001
        logger.debug("router import failed: %s", exc)
        return None
    try:
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("router init failed: %s", exc)
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return Capability.SHOPIFY_CREATE_PRODUCT
