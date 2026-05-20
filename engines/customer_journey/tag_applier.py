"""Customer Journey Engine -- per-customer stage tag applier.

The engine classifies every customer's *furthest stage* in the
purchase funnel (``awareness`` -> ``consideration`` ->
``purchase`` -> ``retention``). Pre-fix the classifications
landed in the engine output only -- the operator had to
manually translate "this customer is in the consideration
stage" into a Shopify action (segment them, target with a
mid-funnel email, etc.).

This applier closes the loop. For each journey, push a tag
``shopai-journey-{stage}`` via ``SHOPIFY_TAG_CUSTOMER`` (the
``tagsAdd`` GraphQL mutation -- additive). Merchants then
save a Shopify admin search for the tag, or downstream
engines (email_marketing / loyalty / browse_recovery) filter
on it to trigger stage-aware retention plays.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern (reference: ``customer_segmentation`` and
``churn_prediction``):

  data.apply_journey_tags=True + data.require_approval=False
    -> SHOPIFY_TAG_CUSTOMER immediately per customer.
  data.apply_journey_tags=True + data.require_approval=True
    (default) -> enqueue each tag-update proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The journey has no Shopify customer id
  * ``furthest_stage`` isn't one of the four canonical values
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-customer; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.customer_journey.tag_applier")


_TAG_PREFIX = "shopai-journey-"
_VALID_STAGES = frozenset({
    "awareness", "consideration", "purchase", "retention",
})


def apply_journey_tags(
    journeys: list[dict[str, Any]],
    *,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-journey-{stage}`` on each journey's customer.

    Returns per-customer list with
    ``{customer_id, furthest_stage, tag, applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries -- the actual tag lands when
    the dispatcher executes the approved action.
    ``pending_action_id`` is populated for those entries.
    """
    proposals = _build_proposals(journeys)
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    journeys: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter the engine's per-customer journeys to actionable rows."""
    proposals: list[dict[str, Any]] = []
    if not isinstance(journeys, list):
        return proposals
    for j in journeys:
        if not isinstance(j, dict):
            continue
        customer_id = str(j.get("customer_id") or "").strip()
        furthest_stage = str(
            j.get("furthest_stage") or "",
        ).strip().lower()
        if not customer_id:
            continue
        if furthest_stage not in _VALID_STAGES:
            continue
        proposals.append({
            "customer_id": customer_id,
            "furthest_stage": furthest_stage,
            "tag": f"{_TAG_PREFIX}{furthest_stage}",
        })
    return proposals


def _apply_each_direct(
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Direct ``SHOPIFY_TAG_CUSTOMER`` per proposal."""
    router = _get_router()
    capability = _get_tag_capability()
    if router is None or capability is None:
        return [
            {
                "customer_id": p["customer_id"],
                "furthest_stage": p["furthest_stage"],
                "tag": p["tag"],
                "applied": False,
                "error": "router_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        try:
            result = router.execute(capability, {
                "id": p["customer_id"],
                "tags": [p["tag"]],
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "customer_journey tag_customer raised for %s: %s",
                p["customer_id"], exc,
            )
            _record_writeback_safely(
                customer_id=p["customer_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "customer_id": p["customer_id"],
                "furthest_stage": p["furthest_stage"],
                "tag": p["tag"],
                "applied": False,
                "error": f"adapter_raised: {exc}",
            })
            continue

        ok = bool(getattr(result, "ok", False))
        error = getattr(result, "error", None)
        if ok:
            _record_writeback_safely(
                customer_id=p["customer_id"],
                tag=p["tag"], success=True,
            )
            results.append({
                "customer_id": p["customer_id"],
                "furthest_stage": p["furthest_stage"],
                "tag": p["tag"],
                "applied": True,
                "error": None,
            })
        else:
            err_str = str(error or "rejected")
            _record_writeback_safely(
                customer_id=p["customer_id"],
                tag=p["tag"], success=False, error=err_str,
            )
            results.append({
                "customer_id": p["customer_id"],
                "furthest_stage": p["furthest_stage"],
                "tag": p["tag"],
                "applied": False,
                "error": f"adapter_failed: {err_str}",
            })
    return results


def _enqueue_each(
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enqueue each proposal via the approval queue."""
    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "customer_id": p["customer_id"],
                "furthest_stage": p["furthest_stage"],
                "tag": p["tag"],
                "applied": False,
                "error": "approval_queue_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        # Enqueue uses ``customer_id`` + ``tag`` (singular).
        # Dispatcher (``tag_journey_customer``) translates to
        # ``{id, tags: [tag]}`` -- the adapter's accepted shape.
        params = {
            "customer_id": p["customer_id"],
            "tag": p["tag"],
            "furthest_stage": p["furthest_stage"],
        }
        narrative = (
            f"customer_journey: tag customer {p['customer_id']} "
            f"with their funnel stage ({p['furthest_stage']}) "
            f"-> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="customer_journey",
                action_type="tag_journey_customer",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "customer_journey enqueue raised for %s: %s",
                p["customer_id"], exc,
            )
            results.append({
                "customer_id": p["customer_id"],
                "furthest_stage": p["furthest_stage"],
                "tag": p["tag"],
                "applied": False,
                "error": f"enqueue_raised: {exc}",
            })
            continue

        _record_writeback_safely(
            customer_id=p["customer_id"],
            tag=p["tag"], success=True,
        )
        results.append({
            "customer_id": p["customer_id"],
            "furthest_stage": p["furthest_stage"],
            "tag": p["tag"],
            "applied": False,  # queued, not applied yet
            "pending_action_id": action.id,
            "error": None,
        })
    return results


def _record_writeback_safely(
    *,
    customer_id: str,
    tag: str,
    success: bool,
    error: str | None = None,
) -> None:
    """Best-effort Phase 8 recording."""
    try:
        record_writeback(
            engine="customer_journey",
            action_type="tag_journey_customer",
            capability="SHOPIFY_TAG_CUSTOMER",
            params={"customer_id": customer_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "customer_journey record_writeback raised for %s: %s",
            customer_id, exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("router unavailable: %s", exc)
        return None


def _get_tag_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_TAG_CUSTOMER
    except Exception as exc:  # noqa: BLE001
        logger.debug("capability resolve failed: %s", exc)
        return None
