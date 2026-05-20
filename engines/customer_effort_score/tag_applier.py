"""Customer Effort Score Engine -- per-customer effort-bucket tag applier.

The engine scores every interaction on a 1-7 effort scale
(lower = easier customer journey) and rolls those up into a
``ces_score`` aggregate plus a per-interaction list. Pre-fix
the per-interaction signal landed only in
``interaction_scores`` -- the merchant couldn't pull a
"customers having a hard time right now" segment without
manually filtering the raw output.

This applier closes the loop. For each customer, take their
WORST (highest) effort_score across all interactions (we want
to flag anyone who hit a friction wall, not the average) and
push ``shopai-ces-{bucket}`` via ``SHOPIFY_TAG_CUSTOMER``
(the ``tagsAdd`` mutation -- additive). Merchants then save
admin searches to focus support attention or run reach-out
campaigns; downstream engines (customer_service / loyalty)
filter on the bucket for friction-aware retention plays.

Bucket math (1-7 effort scale, lower is better):
  * score <= 2.5 -> "low" (smooth journey)
  * 2.5 < score <= 5.0 -> "medium"
  * score > 5.0 -> "high" (friction-heavy, needs attention)

The "high" bucket is the operator's hot list. The "low" bucket
is OFF by default (tagging happy customers as "low effort" is
noise -- merchants want signal). The "medium" bucket is OFF by
default for the same reason. Set ``include_low=True`` /
``include_medium=True`` to override.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_ces_tags=True + data.require_approval=False
    -> SHOPIFY_TAG_CUSTOMER immediately per customer.
  data.apply_ces_tags=True + data.require_approval=True
    (default) -> enqueue each tag-update proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The interaction has no customer_id
  * The effort_score is non-numeric or out of range (1-7)
  * The bucket is excluded by the include_* flags
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-customer; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.customer_effort_score.tag_applier")


_TAG_PREFIX = "shopai-ces-"


def apply_ces_tags(
    interaction_scores: list[dict[str, Any]],
    *,
    include_low: bool = False,
    include_medium: bool = False,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-ces-{bucket}`` on each scored customer.

    Returns per-customer list with
    ``{customer_id, effort_score, bucket, tag, applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries -- the actual tag lands when
    the dispatcher executes the approved action.
    ``pending_action_id`` is populated for those entries.
    """
    proposals = _build_proposals(
        interaction_scores,
        include_low=include_low,
        include_medium=include_medium,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    interaction_scores: list[dict[str, Any]],
    *,
    include_low: bool,
    include_medium: bool,
) -> list[dict[str, Any]]:
    """Filter interactions to actionable per-customer rows.

    Worst-score-wins per customer: a customer with one smooth
    and one frustrating interaction is still a customer who
    hit friction -- that's the signal we want.
    """
    if not isinstance(interaction_scores, list):
        return []
    worst: dict[str, dict[str, Any]] = {}
    for r in interaction_scores:
        if not isinstance(r, dict):
            continue
        customer_id = str(r.get("customer_id") or "").strip()
        if not customer_id or customer_id == "unknown":
            continue
        try:
            score = float(r.get("effort_score", 0))
        except (TypeError, ValueError):
            continue
        # The scorer clamps to 1.0-7.0 but be defensive in
        # case the applier ever sees a hand-built list.
        if score < 1.0 or score > 7.0:
            continue
        existing = worst.get(customer_id)
        if existing is None or score > existing["effort_score"]:
            worst[customer_id] = {
                "customer_id": customer_id,
                "effort_score": score,
            }

    proposals: list[dict[str, Any]] = []
    for entry in worst.values():
        score = entry["effort_score"]
        bucket = _bucket_for(score)
        if bucket == "low" and not include_low:
            continue
        if bucket == "medium" and not include_medium:
            continue
        proposals.append({
            "customer_id": entry["customer_id"],
            "effort_score": round(score, 2),
            "bucket": bucket,
            "tag": f"{_TAG_PREFIX}{bucket}",
        })
    return proposals


def _bucket_for(score: float) -> str:
    if score <= 2.5:
        return "low"
    if score <= 5.0:
        return "medium"
    return "high"


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
                "effort_score": p["effort_score"],
                "bucket": p["bucket"],
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
                "ces tag_customer raised for %s: %s",
                p["customer_id"], exc,
            )
            _record_writeback_safely(
                customer_id=p["customer_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "customer_id": p["customer_id"],
                "effort_score": p["effort_score"],
                "bucket": p["bucket"],
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
                "effort_score": p["effort_score"],
                "bucket": p["bucket"],
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
                "effort_score": p["effort_score"],
                "bucket": p["bucket"],
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
                "effort_score": p["effort_score"],
                "bucket": p["bucket"],
                "tag": p["tag"],
                "applied": False,
                "error": "approval_queue_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        # Enqueue uses ``customer_id`` + ``tag``. Dispatcher
        # (``tag_ces_customer``) translates to
        # ``{id, tags: [tag]}`` for SHOPIFY_TAG_CUSTOMER.
        params = {
            "customer_id": p["customer_id"],
            "tag": p["tag"],
            "effort_score": p["effort_score"],
            "bucket": p["bucket"],
        }
        narrative = (
            f"customer_effort_score: tag customer "
            f"{p['customer_id']} as {p['bucket']} effort "
            f"(score {p['effort_score']}) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="customer_effort_score",
                action_type="tag_ces_customer",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "ces enqueue raised for %s: %s",
                p["customer_id"], exc,
            )
            results.append({
                "customer_id": p["customer_id"],
                "effort_score": p["effort_score"],
                "bucket": p["bucket"],
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
            "effort_score": p["effort_score"],
            "bucket": p["bucket"],
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
            engine="customer_effort_score",
            action_type="tag_ces_customer",
            capability="SHOPIFY_TAG_CUSTOMER",
            params={"customer_id": customer_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "ces record_writeback raised for %s: %s",
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
