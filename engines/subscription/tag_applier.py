"""Subscription Engine -- per-subscriber at-risk tag applier.

The engine evaluates each active subscriber for churn risk
based on payment failures, past-due status, tenure, LTV, and
downgrade patterns. It emits ``churn_risks`` per subscriber
with a ``risk_level`` (high / medium / low / minimal) and a
``recommended_action`` (immediate_retention_outreach /
proactive_engagement / monitor / none). Pre-fix the
classification landed in engine output only -- the merchant
had to manually translate "this subscriber hit our high-risk
threshold" into a Shopify segment / outreach worklist.

This applier closes the loop. For high-risk subscribers, push
``shopai-subscription-at-risk`` on the customer via
``SHOPIFY_TAG_CUSTOMER`` (the additive tagsAdd mutation --
existing tags preserved). Merchants then save admin searches
to drive a "subscriptions about to cancel" worklist;
downstream engines (loyalty / customer_service /
email_marketing) filter on the tag to fire win-back retention
plays before the cancel hits.

Only ``high`` risk is tagged by default -- tagging medium /
low as at-risk is noise. ``include_medium=True`` opts in
medium-risk subscribers (broader hot list at the cost of
weaker signal-to-noise).

Distinct from ``shopai-churn-*`` (churn_prediction engine
tags) because subscription-side churn is a separate failure
mode (recurring billing problems, plan-level retention)
from broader customer churn (purchase-recency, engagement
drop). A subscriber may be flagged by ONE but not the OTHER,
and merchants can act on each axis independently.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_subscription_tags=True + data.require_approval=False
    -> SHOPIFY_TAG_CUSTOMER immediately.
  data.apply_subscription_tags=True + data.require_approval=True
    (default) -> enqueue each tag-update proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The risk entry has no subscriber_id
  * risk_level is not ``high`` (and not ``medium`` when
    include_medium=True)
  * Duplicate subscriber_ids deduped (worst-risk wins -- the
    engine's churn predictor already sorts by risk desc, but
    be defensive)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-subscriber; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.subscription.tag_applier")


_TAG = "shopai-subscription-at-risk"
# Maps engine risk_level → bucket name we tag. Only "high"
# tagged by default; "medium" gated by include_medium.
_HIGH = "high"
_MEDIUM = "medium"
_TAGGABLE_LEVELS = frozenset({_HIGH, _MEDIUM})


def apply_subscription_tags(
    churn_risks: list[dict[str, Any]],
    *,
    include_medium: bool = False,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-subscription-at-risk`` on each at-risk subscriber.

    Returns per-subscriber list with
    ``{subscriber_id, risk, risk_level, tag, applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries.
    """
    proposals = _build_proposals(
        churn_risks, include_medium=include_medium,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    churn_risks: list[dict[str, Any]],
    *,
    include_medium: bool,
) -> list[dict[str, Any]]:
    """Filter churn risks to actionable per-subscriber rows."""
    if not isinstance(churn_risks, list):
        return []
    allowed = {_HIGH}
    if include_medium:
        allowed = {_HIGH, _MEDIUM}
    seen: set[str] = set()
    proposals: list[dict[str, Any]] = []
    for entry in churn_risks:
        if not isinstance(entry, dict):
            continue
        # The engine uses "unknown" as the default subscriber
        # id when sub.get("id") is missing — filter both.
        subscriber_id = str(entry.get("subscriber_id") or "").strip()
        if not subscriber_id or subscriber_id == "unknown":
            continue
        if subscriber_id in seen:
            continue
        risk_level = str(entry.get("risk_level") or "").strip().lower()
        if risk_level not in allowed:
            continue
        if risk_level not in _TAGGABLE_LEVELS:
            continue
        try:
            risk = float(entry.get("risk", 0.0))
        except (TypeError, ValueError):
            risk = 0.0
        recommended_action = str(
            entry.get("recommended_action") or "",
        ).strip()
        seen.add(subscriber_id)
        proposals.append({
            "subscriber_id": subscriber_id,
            "risk": round(risk, 2),
            "risk_level": risk_level,
            "recommended_action": recommended_action,
            "tag": _TAG,
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
                "subscriber_id": p["subscriber_id"],
                "risk": p["risk"],
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
                "id": p["subscriber_id"],
                "tags": [p["tag"]],
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "subscription tag_customer raised for %s: %s",
                p["subscriber_id"], exc,
            )
            _record_writeback_safely(
                subscriber_id=p["subscriber_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "subscriber_id": p["subscriber_id"],
                "risk": p["risk"],
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
                subscriber_id=p["subscriber_id"],
                tag=p["tag"], success=True,
            )
            results.append({
                "subscriber_id": p["subscriber_id"],
                "risk": p["risk"],
                "risk_level": p["risk_level"],
                "tag": p["tag"],
                "applied": True,
                "error": None,
            })
        else:
            err_str = str(error or "rejected")
            _record_writeback_safely(
                subscriber_id=p["subscriber_id"],
                tag=p["tag"], success=False, error=err_str,
            )
            results.append({
                "subscriber_id": p["subscriber_id"],
                "risk": p["risk"],
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
                "subscriber_id": p["subscriber_id"],
                "risk": p["risk"],
                "risk_level": p["risk_level"],
                "tag": p["tag"],
                "applied": False,
                "error": "approval_queue_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        # Enqueue uses ``subscriber_id`` -> the dispatcher
        # translates to ``{id, tags: [tag]}`` for
        # SHOPIFY_TAG_CUSTOMER. We use ``customer_id`` as the
        # key the dispatcher reads (consistent with the
        # other tag_customer dispatchers).
        params = {
            "customer_id": p["subscriber_id"],
            "tag": p["tag"],
            "risk": p["risk"],
            "risk_level": p["risk_level"],
            "recommended_action": p["recommended_action"],
        }
        narrative = (
            f"subscription: tag subscriber {p['subscriber_id']} "
            f"as at-risk ({p['risk_level']}, "
            f"risk={p['risk']}) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="subscription",
                action_type="tag_subscription_at_risk",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "subscription enqueue raised for %s: %s",
                p["subscriber_id"], exc,
            )
            results.append({
                "subscriber_id": p["subscriber_id"],
                "risk": p["risk"],
                "risk_level": p["risk_level"],
                "tag": p["tag"],
                "applied": False,
                "error": f"enqueue_raised: {exc}",
            })
            continue

        _record_writeback_safely(
            subscriber_id=p["subscriber_id"],
            tag=p["tag"], success=True,
        )
        results.append({
            "subscriber_id": p["subscriber_id"],
            "risk": p["risk"],
            "risk_level": p["risk_level"],
            "tag": p["tag"],
            "applied": False,  # queued, not applied yet
            "pending_action_id": action.id,
            "error": None,
        })
    return results


def _record_writeback_safely(
    *,
    subscriber_id: str,
    tag: str,
    success: bool,
    error: str | None = None,
) -> None:
    """Best-effort Phase 8 recording."""
    try:
        record_writeback(
            engine="subscription",
            action_type="tag_subscription_at_risk",
            capability="SHOPIFY_TAG_CUSTOMER",
            params={"subscriber_id": subscriber_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "subscription record_writeback raised for %s: %s",
            subscriber_id, exc,
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
