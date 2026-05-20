"""Churn Prediction Engine -- at-risk customer tag applier.

The engine classifies every customer into a churn-risk
bucket (``critical`` / ``high`` / ``medium`` / ``low``).
Pre-fix the classifications landed in the engine output only --
the operator had to manually translate "this customer is
high-risk" into a Shopify action (segment them, target them
with a win-back campaign, raise CS priority).

This applier closes the loop. For each prediction with
``risk_level`` in ``{critical, high}``, push a tag
``shopai-churn-{level}`` via ``SHOPIFY_TAG_CUSTOMER`` (the
``tagsAdd`` GraphQL mutation -- additive). Merchants can
then save a Shopify admin search for the tag, or downstream
engines (email_marketing / loyalty / browse_recovery) can
filter on it to trigger retention plays automatically.

Two opt-in modes match the established Phase 6/7 pattern
(reference: ``customer_segmentation/customer_applier.py``):

  data.apply_at_risk_tags=True + data.require_approval=False
    -> SHOPIFY_TAG_CUSTOMER immediately per customer
  data.apply_at_risk_tags=True + data.require_approval=True
    (default) -> enqueue each tag-update proposal via the
    approval queue; merchant approves via /api/pending-actions
    before the mutation lands.

Default OFF -- existing callers keep their pure-recommendation
contract.

Skipped (no API call / no queue entry) when:
  * ``risk_level`` is medium / low (we only tag the elevated
    buckets; tagging "low risk" is noise)
  * The prediction has no Shopify customer id
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-customer, doesn't
    halt the batch)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.churn_prediction.tag_applier")


_TAG_PREFIX = "shopai-churn-"
_ELEVATED_RISK = frozenset({"critical", "high"})


def apply_at_risk_tags(
    predictions: list[dict[str, Any]],
    *,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-churn-{level}`` on each elevated-risk
    customer.

    Returns per-customer list with
    ``{customer_id, risk_level, tag, applied, error}``. When
    ``require_approval=True`` (default), ``applied`` is False
    for queue-only entries -- the actual tag lands when the
    dispatcher executes the approved action. ``pending_action_id``
    is populated for those entries.
    """
    proposals = _build_proposals(predictions)
    if not proposals:
        return []

    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    predictions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter the engine's predictions to actionable rows."""
    proposals: list[dict[str, Any]] = []
    if not isinstance(predictions, list):
        return proposals
    for p in predictions:
        if not isinstance(p, dict):
            continue
        customer_id = str(p.get("customer_id") or "").strip()
        risk_level = str(p.get("risk_level") or "").strip().lower()
        if not customer_id:
            continue
        if risk_level not in _ELEVATED_RISK:
            continue
        # Tag prefix is the engine's "ownership marker" -- any
        # tag starting with shopai-churn- means this engine
        # added it and the engine is the authority for that
        # tag's lifecycle.
        proposals.append({
            "customer_id": customer_id,
            "risk_level": risk_level,
            "tag": f"{_TAG_PREFIX}{risk_level}",
            "churn_probability": float(
                p.get("churn_probability") or 0.0,
            ),
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
                "risk_level": p["risk_level"],
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
                "churn_prediction tag_customer raised for %s: %s",
                p["customer_id"], exc,
            )
            _record_writeback_safely(
                customer_id=p["customer_id"],
                tag=p["tag"],
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "customer_id": p["customer_id"],
                "risk_level": p["risk_level"],
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
                "risk_level": p["risk_level"],
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
                "risk_level": p["risk_level"],
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
                "risk_level": p["risk_level"],
                "tag": p["tag"],
                "applied": False,
                "error": "approval_queue_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        # Enqueue uses ``customer_id`` + ``tag`` (singular).
        # Dispatcher (``tag_at_risk_customer``) translates to
        # ``{id, tags: [tag]}`` -- the adapter's accepted shape.
        # Same dispatcher-side translation
        # ``apply_segment_tag`` does for customer_segmentation.
        params = {
            "customer_id": p["customer_id"],
            "tag": p["tag"],
            "risk_level": p["risk_level"],
            "churn_probability": p["churn_probability"],
        }
        narrative = (
            f"churn_prediction: tag customer {p['customer_id']} "
            f"as {p['risk_level']} risk ({p['churn_probability']:.0%} "
            f"probability) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="churn_prediction",
                action_type="tag_at_risk_customer",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "churn_prediction enqueue raised for %s: %s",
                p["customer_id"], exc,
            )
            results.append({
                "customer_id": p["customer_id"],
                "risk_level": p["risk_level"],
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
            "risk_level": p["risk_level"],
            "tag": p["tag"],
            "applied": False,  # not applied YET -- queued
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
    """Best-effort Phase 8 recording. Failures swallowed."""
    try:
        record_writeback(
            engine="churn_prediction",
            action_type="tag_at_risk_customer",
            capability="SHOPIFY_TAG_CUSTOMER",
            params={"customer_id": customer_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "churn_prediction record_writeback raised for %s: %s",
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
