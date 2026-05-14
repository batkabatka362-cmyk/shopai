"""Pricing Engine — Shopify variant price applier (strategic).

The pricing engine emits ONE ``recommended_price`` per product
(strategic, single-product). Pre-fix that recommendation was
advisory only — the merchant had to copy the calculated optimal
price out of the engine output and manually update each variant in
the Shopify admin.

This closes the loop. When opt-in is set and the engine returns a
confident recommendation, push the new price to every variant of
the input product via ``SHOPIFY_UPDATE_VARIANTS`` — the same
mutation dynamic_pricing uses, scoped to a single product.

Two opt-in modes match the established Phase 6/7 pattern:

  data.apply_strategic_price=True + data.require_approval=False
    → mint immediately
  data.apply_strategic_price=True + data.require_approval=True
    → enqueue to core.approval; merchant approves before the
      SHOPIFY_UPDATE_VARIANTS mutation lands

Skipped (no API call / no queue entry) when:

  * ``recommended_price`` is missing / non-positive.
  * Confidence < floor (default 0.60, configurable via
    ``store.strategic_pricing_confidence_floor``). Higher floor
    than tag-style writers — pricing decisions are higher-stakes
    and the engine's confidence ceiling is already in the 0.7-0.9
    range for confident outputs.
  * The product has no ``variants`` list (hydrator-fetched
    products from ``SHOPIFY_LIST_PRODUCTS`` don't include
    variants — same known limitation as dynamic_pricing). Callers
    wanting writeback need to pre-fetch via ``SHOPIFY_GET_PRODUCT``
    or supply enriched products.
  * The router is unavailable / adapter rejects (direct path).
  * The queue is unavailable (approval path).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.pricing.applier")


_DEFAULT_CONFIDENCE_FLOOR = 0.60


def apply_strategic_price(
    product: dict[str, Any],
    recommendation: dict[str, Any],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Push the recommended price onto every variant of *product*.

    Args:
        product: Engine input product dict — must carry a
            ``variants`` list of ``{id, ...}`` for the variant
            ids to update.
        recommendation: ``recommend_price`` output —
            ``{optimal_price, strategy, confidence, ...}``.
        store: Optional config carrying
            ``strategic_pricing_confidence_floor`` (default 0.60).

    Returns:
        ``{"applied", "product_id", "variants_updated",
        "new_price", "old_price_examples", "strategy", "error"}``
        on success or structured skip. ``None`` only when the
        upfront guardrails reject before any router work.
    """
    resolved = _resolve_proposal(product, recommendation, store)
    if resolved is None:
        return None

    pid = resolved["product_id"]
    new_price = resolved["new_price"]
    variant_ids = resolved["variant_ids"]
    old_prices = resolved["old_prices"]
    strategy = resolved["strategy"]

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        return {
            "applied": False,
            "product_id": pid,
            "variants_updated": 0,
            "new_price": new_price,
            "old_price_examples": old_prices,
            "strategy": strategy,
            "error": "router_unavailable",
        }

    price_str = f"{new_price:.2f}"
    variants_payload = [
        {"id": vid, "price": price_str} for vid in variant_ids
    ]

    recorder_params = {
        "product_id": pid,
        "new_price": new_price,
        "strategy": strategy,
        "variant_count": len(variant_ids),
    }
    try:
        result = router.execute(
            capability,
            {"product_id": pid, "variants": variants_payload},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "apply_strategic_price raised for %s: %s", pid, exc,
        )
        record_writeback(
            engine="pricing",
            action_type="apply_strategic_price",
            capability="SHOPIFY_UPDATE_VARIANTS",
            params=recorder_params,
            success=False,
            error=f"adapter_raised: {exc}",
        )
        return {
            "applied": False,
            "product_id": pid,
            "variants_updated": 0,
            "new_price": new_price,
            "old_price_examples": old_prices,
            "strategy": strategy,
            "error": f"adapter_raised: {exc}",
        }

    if not getattr(result, "ok", False):
        err = getattr(result, "error", "unknown")
        record_writeback(
            engine="pricing",
            action_type="apply_strategic_price",
            capability="SHOPIFY_UPDATE_VARIANTS",
            params=recorder_params,
            success=False,
            error=f"adapter_failed: {err}",
        )
        return {
            "applied": False,
            "product_id": pid,
            "variants_updated": 0,
            "new_price": new_price,
            "old_price_examples": old_prices,
            "strategy": strategy,
            "error": f"adapter_failed: {err}",
        }

    record_writeback(
        engine="pricing",
        action_type="apply_strategic_price",
        capability="SHOPIFY_UPDATE_VARIANTS",
        params=recorder_params,
        success=True,
    )
    return {
        "applied": True,
        "product_id": pid,
        "variants_updated": len(variant_ids),
        "new_price": new_price,
        "old_price_examples": old_prices,
        "strategy": strategy,
        "error": None,
    }


def enqueue_strategic_price_for_approval(
    product: dict[str, Any],
    recommendation: dict[str, Any],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Park the strategic-price proposal in the approval queue.

    Per-engine alternative to :func:`apply_strategic_price` —
    same upfront guards. Returns the standard
    ``{pending_action_id, narrative, params}`` shape used across
    Phase 6/7 enqueue helpers; on guardrail rejection or queue
    failure, returns ``None``.
    """
    resolved = _resolve_proposal(product, recommendation, store)
    if resolved is None:
        return None

    pid = resolved["product_id"]
    new_price = resolved["new_price"]
    variant_ids = resolved["variant_ids"]
    strategy = resolved["strategy"]
    confidence = resolved["confidence"]
    old_prices = resolved["old_prices"]
    delta = (
        new_price - old_prices[0] if old_prices else None
    )

    narrative_parts = [
        f"Set {pid} to ${new_price:.2f}",
    ]
    if delta is not None:
        sign = "+" if delta >= 0 else ""
        narrative_parts.append(f"({sign}${delta:.2f} vs current)")
    narrative_parts.append(f"strategy={strategy}")
    narrative_parts.append(f"confidence={confidence:.2f}")
    narrative_parts.append(f"{len(variant_ids)} variant(s)")
    narrative = " — ".join([narrative_parts[0]] + narrative_parts[1:])

    params = {
        "product_id": pid,
        "new_price": new_price,
        "strategy": strategy,
        "confidence": confidence,
        "variant_ids": list(variant_ids),
        "old_price_examples": old_prices,
    }

    try:
        from core.approval import get_approval_queue
        action = get_approval_queue().enqueue(
            engine="pricing",
            action_type="apply_strategic_price",
            capability="SHOPIFY_UPDATE_VARIANTS",
            params=params,
            narrative=narrative,
            confidence=confidence,
        )
    except Exception:  # noqa: BLE001
        return None

    return {
        "pending_action_id": action.id,
        "narrative": narrative,
        "params": params,
    }


# ── Proposal builder ──────────────────────────────────────────


def _resolve_proposal(
    product: dict[str, Any] | None,
    recommendation: dict[str, Any] | None,
    store: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve product + recommendation into an actionable shape.

    Returns ``None`` when any guardrail rejects (no product, no
    variants, zero / non-numeric price, sub-floor confidence).
    """
    if not isinstance(product, dict) or not product:
        return None
    if not isinstance(recommendation, dict) or not recommendation:
        return None

    pid = str(product.get("id", "")).strip()
    if not pid:
        return None

    new_price = _safe_float(
        recommendation.get("optimal_price")
        or recommendation.get("recommended_price"),
    )
    if new_price is None or new_price <= 0:
        return None

    confidence = _safe_float(recommendation.get("confidence")) or 0.0
    floor = _resolve_confidence_floor(store)
    if confidence < floor:
        return None

    variants = product.get("variants") or []
    if not isinstance(variants, list):
        return None
    variant_ids: list[str] = []
    old_prices: list[float] = []
    for v in variants:
        if not isinstance(v, dict):
            continue
        vid = str(v.get("id", "")).strip()
        if not vid:
            continue
        variant_ids.append(vid)
        old = _safe_float(v.get("price"))
        if old is not None:
            old_prices.append(old)
    if not variant_ids:
        return None

    strategy = str(recommendation.get("strategy", "")) or "cost_plus"

    return {
        "product_id": pid,
        "new_price": new_price,
        "variant_ids": variant_ids,
        "old_prices": old_prices[:3],
        "strategy": strategy,
        "confidence": confidence,
    }


# ── Config helpers ────────────────────────────────────────────


def _resolve_confidence_floor(store: dict[str, Any] | None) -> float:
    if not isinstance(store, dict):
        return _DEFAULT_CONFIDENCE_FLOOR
    raw = store.get("strategic_pricing_confidence_floor")
    if raw is None:
        return _DEFAULT_CONFIDENCE_FLOOR
    try:
        floor = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_CONFIDENCE_FLOOR
    return max(0.0, min(1.0, floor))


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
    return Capability.SHOPIFY_UPDATE_VARIANTS
