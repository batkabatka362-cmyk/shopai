"""Shipping Optimization Engine — Shopify automatic-free-shipping
applier.

The shipping_optimization engine's strategy recommender returns
one of four candidate strategies:

  * ``free_over_threshold`` — free shipping above a calculated
    cart subtotal threshold (e.g. free over $75)
  * ``flat_rate`` — flat-rate per order
  * ``calculated`` — pass through real-time carrier rates
  * ``free_for_members`` — free for loyalty / subscription tier

Of the four, only ``free_over_threshold`` maps to a single
Shopify mutation today —
``discountAutomaticFreeShippingCreate`` with a
``minimumRequirement.subtotal.greaterThanOrEqualToSubtotal``
gate. The other three require multi-zone delivery-profile
config that's merchant-specific and dangerous to auto-apply.

So the applier scope is narrow: when the winner is
``free_over_threshold``, mint ONE automatic free-shipping
discount with the recommended threshold; otherwise no-op with
a structured ``skipped`` result so the engine output is
explicit about why.

Two opt-in modes match the established Phase 6/7 pattern:

  data.apply_shipping_strategy=True + data.require_approval=False
    → mint immediately
  data.apply_shipping_strategy=True + data.require_approval=True
    → enqueue to core.approval; merchant approves before the
      SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING mutation lands

Skipped (no API call / no queue entry) when:
  * Strategy is not ``free_over_threshold``.
  * Threshold <= 0 (the optimizer returned no recommended gate).
  * Confidence below ``store.shipping_confidence_floor``
    (default 0.55 — the strategy_recommender's confidence
    ceiling for free_over_threshold is 0.95, floor of 0.55
    rejects only the weakest signals).
  * Router unavailable / adapter rejects (direct path).
  * Approval queue unavailable (approval path).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.shipping_optimization.applier")


_DEFAULT_TTL_DAYS = 30
_DEFAULT_CONFIDENCE_FLOOR = 0.55
_TITLE_PREFIX = "ShopAI: Free shipping over"
_STRATEGY_ID = "free_over_threshold"


def apply_shipping_strategy(
    recommendation: dict[str, Any],
    estimated_savings_monthly: float,
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Mint a Shopify automatic free-shipping discount.

    Returns ``None`` when the upstream guards reject (wrong
    strategy / zero threshold / low confidence). Otherwise
    returns ``{"applied": bool, "strategy_id", "threshold",
    "title", "starts_at", "ends_at", "discount_id", "error"}``.
    """
    proposal = _build_proposal(recommendation, store)
    if proposal is None:
        return None

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        return {
            "applied": False,
            "strategy_id": _STRATEGY_ID,
            "threshold": proposal["minimum_subtotal"],
            "title": proposal["title"],
            "starts_at": proposal["starts_at"],
            "ends_at": proposal["ends_at"],
            "discount_id": "",
            "error": "router_unavailable",
        }

    recorder_params = {
        "strategy_id": _STRATEGY_ID,
        "threshold": proposal["minimum_subtotal"],
        "ttl_days": proposal["ttl_days"],
        "estimated_savings_monthly": estimated_savings_monthly,
    }
    try:
        result = router.execute(capability, proposal["adapter_params"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("apply_shipping_strategy raised: %s", exc)
        record_writeback(
            engine="shipping_optimization",
            action_type="apply_shipping_strategy",
            capability="SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING",
            params=recorder_params,
            success=False,
            error=f"adapter_raised: {exc}",
        )
        return {
            "applied": False,
            "strategy_id": _STRATEGY_ID,
            "threshold": proposal["minimum_subtotal"],
            "title": proposal["title"],
            "starts_at": proposal["starts_at"],
            "ends_at": proposal["ends_at"],
            "discount_id": "",
            "error": f"adapter_raised: {exc}",
        }

    if not getattr(result, "ok", False):
        err = getattr(result, "error", "unknown")
        record_writeback(
            engine="shipping_optimization",
            action_type="apply_shipping_strategy",
            capability="SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING",
            params=recorder_params,
            success=False,
            error=f"adapter_failed: {err}",
        )
        return {
            "applied": False,
            "strategy_id": _STRATEGY_ID,
            "threshold": proposal["minimum_subtotal"],
            "title": proposal["title"],
            "starts_at": proposal["starts_at"],
            "ends_at": proposal["ends_at"],
            "discount_id": "",
            "error": f"adapter_failed: {err}",
        }

    data = getattr(result, "data", {}) or {}
    record_writeback(
        engine="shipping_optimization",
        action_type="apply_shipping_strategy",
        capability="SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING",
        params=recorder_params,
        success=True,
    )
    return {
        "applied": True,
        "strategy_id": _STRATEGY_ID,
        "threshold": proposal["minimum_subtotal"],
        "title": data.get("title", proposal["title"]),
        "starts_at": data.get("starts_at", proposal["starts_at"]),
        "ends_at": data.get("ends_at", proposal["ends_at"]),
        "discount_id": data.get("id", ""),
        "error": None,
    }


def enqueue_shipping_for_approval(
    recommendation: dict[str, Any],
    estimated_savings_monthly: float,
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Park the free-shipping proposal in the approval queue.

    Mirrors :func:`apply_shipping_strategy` — same upfront
    filters (strategy_id, positive threshold, confidence floor).
    Returns the standard
    ``{pending_action_id, narrative, params}`` shape used
    across Phase 6/7 enqueue helpers.
    """
    proposal = _build_proposal(recommendation, store)
    if proposal is None:
        return None

    narrative = (
        f"Create automatic free shipping over "
        f"${proposal['minimum_subtotal']:.2f} "
        f"(~${estimated_savings_monthly:.2f}/mo savings, "
        f"{proposal['ttl_days']}d window)"
    )
    params = {
        "strategy_id": _STRATEGY_ID,
        "threshold": proposal["minimum_subtotal"],
        "title": proposal["title"],
        "starts_at": proposal["starts_at"],
        "ends_at": proposal["ends_at"],
        "ttl_days": proposal["ttl_days"],
        "estimated_savings_monthly": estimated_savings_monthly,
        "adapter_params": proposal["adapter_params"],
    }

    try:
        from core.approval import get_approval_queue
        action = get_approval_queue().enqueue(
            engine="shipping_optimization",
            action_type="apply_shipping_strategy",
            capability="SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING",
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
    recommendation: dict[str, Any] | None,
    store: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve the inputs into an adapter-ready proposal.

    Returns ``None`` when any guardrail rejects (wrong strategy,
    zero threshold, sub-floor confidence).
    """
    if not isinstance(recommendation, dict):
        return None
    if str(recommendation.get("strategy_id", "")) != _STRATEGY_ID:
        return None

    parameters = recommendation.get("parameters") or {}
    if not isinstance(parameters, dict):
        return None
    threshold = _safe_float(parameters.get("threshold"))
    if threshold is None or threshold <= 0:
        return None

    confidence = _safe_float(recommendation.get("confidence")) or 0.0
    floor = _resolve_confidence_floor(store)
    if confidence < floor:
        return None

    ttl_days = _resolve_ttl_days(store)
    starts_at = datetime.now(timezone.utc).replace(microsecond=0)
    ends_at = starts_at + timedelta(days=ttl_days)
    starts_iso = starts_at.isoformat().replace("+00:00", "Z")
    ends_iso = ends_at.isoformat().replace("+00:00", "Z")

    title = f"{_TITLE_PREFIX} ${threshold:.2f}"

    adapter_params = {
        "title": title,
        "starts_at": starts_iso,
        "ends_at": ends_iso,
        "minimum_subtotal": threshold,
    }
    return {
        "minimum_subtotal": threshold,
        "title": title,
        "starts_at": starts_iso,
        "ends_at": ends_iso,
        "ttl_days": ttl_days,
        "adapter_params": adapter_params,
    }


# ── Config helpers ────────────────────────────────────────────


def _resolve_ttl_days(store: dict[str, Any] | None) -> int:
    if not isinstance(store, dict):
        return _DEFAULT_TTL_DAYS
    raw = store.get("free_shipping_ttl_days")
    if raw is None:
        return _DEFAULT_TTL_DAYS
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_DAYS
    return max(1, days)


def _resolve_confidence_floor(store: dict[str, Any] | None) -> float:
    if not isinstance(store, dict):
        return _DEFAULT_CONFIDENCE_FLOOR
    raw = store.get("shipping_confidence_floor")
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
    return Capability.SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING
