"""NPS Engine -- per-customer NPS-bucket tag applier.

The engine classifies every responder by their score:
``promoter`` (9-10) / ``passive`` (7-8) / ``detractor`` (0-6).
Pre-fix the classifications landed in the engine output only
as aggregate percentages -- the merchant couldn't pull a
"show me my promoters" segment without manually crunching
the raw responses.

This applier closes the loop. For each survey respondent, push
a tag ``shopai-nps-{bucket}`` via ``SHOPIFY_TAG_CUSTOMER`` (the
``tagsAdd`` GraphQL mutation -- additive). Merchants then save
a Shopify admin search for the tag (drive referrals from
promoters, run win-back campaigns on detractors), or downstream
engines (loyalty / customer_service) filter on it to fire
bucket-aware retention plays.

Passives (7-8) are intentionally NOT tagged by default --
they're the "would survive but might not return" middle, and
the operator typically wants to focus attention on the
promoters and detractors only. Set ``include_passives=True``
to also push ``shopai-nps-passive``.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_nps_tags=True + data.require_approval=False
    -> SHOPIFY_TAG_CUSTOMER immediately per response.
  data.apply_nps_tags=True + data.require_approval=True
    (default) -> enqueue each tag-update proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The response has no customer_id
  * The score is out of range (0-10) or non-integer
  * The bucket is "passive" and include_passives=False
  * Duplicate customer_ids deduped (last response wins -- some
    survey deployments re-survey the same customer)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-customer; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.nps_engine.tag_applier")


_TAG_PREFIX = "shopai-nps-"


def apply_nps_tags(
    validated_responses: list[dict[str, Any]],
    *,
    include_passives: bool = False,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-nps-{bucket}`` on each responder.

    Returns per-customer list with
    ``{customer_id, score, bucket, tag, applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries -- the actual tag lands when
    the dispatcher executes the approved action.
    ``pending_action_id`` is populated for those entries.
    """
    proposals = _build_proposals(
        validated_responses, include_passives=include_passives,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    validated_responses: list[dict[str, Any]],
    *,
    include_passives: bool,
) -> list[dict[str, Any]]:
    """Filter responses to actionable per-customer tag rows."""
    proposals: list[dict[str, Any]] = []
    if not isinstance(validated_responses, list):
        return proposals
    # Last-wins dedup: re-survey scenarios produce multiple
    # responses for the same customer; the latest score is the
    # current signal.
    seen: dict[str, dict[str, Any]] = {}
    for r in validated_responses:
        if not isinstance(r, dict):
            continue
        customer_id = str(r.get("customer_id") or "").strip()
        if not customer_id:
            continue
        score_raw = r.get("score")
        if score_raw is None:
            continue
        try:
            score = int(score_raw)
        except (TypeError, ValueError):
            continue
        if score < 0 or score > 10:
            continue
        bucket = _bucket_for(score)
        if bucket == "passive" and not include_passives:
            continue
        seen[customer_id] = {
            "customer_id": customer_id,
            "score": score,
            "bucket": bucket,
            "tag": f"{_TAG_PREFIX}{bucket}",
        }
    proposals.extend(seen.values())
    return proposals


def _bucket_for(score: int) -> str:
    if score >= 9:
        return "promoter"
    if score >= 7:
        return "passive"
    return "detractor"


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
                "score": p["score"],
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
                "nps tag_customer raised for %s: %s",
                p["customer_id"], exc,
            )
            _record_writeback_safely(
                customer_id=p["customer_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "customer_id": p["customer_id"],
                "score": p["score"],
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
                "score": p["score"],
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
                "score": p["score"],
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
                "score": p["score"],
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
        # (``tag_nps_customer``) translates to
        # ``{id, tags: [tag]}`` for SHOPIFY_TAG_CUSTOMER.
        params = {
            "customer_id": p["customer_id"],
            "tag": p["tag"],
            "score": p["score"],
            "bucket": p["bucket"],
        }
        narrative = (
            f"nps_engine: tag customer {p['customer_id']} "
            f"as {p['bucket']} (score {p['score']}) "
            f"-> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="nps_engine",
                action_type="tag_nps_customer",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "nps enqueue raised for %s: %s",
                p["customer_id"], exc,
            )
            results.append({
                "customer_id": p["customer_id"],
                "score": p["score"],
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
            "score": p["score"],
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
            engine="nps_engine",
            action_type="tag_nps_customer",
            capability="SHOPIFY_TAG_CUSTOMER",
            params={"customer_id": customer_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "nps record_writeback raised for %s: %s",
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
