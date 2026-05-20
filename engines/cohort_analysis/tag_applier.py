"""Cohort Analysis Engine -- per-customer cohort tag applier.

The engine groups customers by their signup / first-purchase period
(``2025-01`` monthly or ``2025-01-15`` weekly) into LTV cohorts.
Pre-fix the cohort assignments landed in the engine output only --
the merchant had to manually translate "this customer is in the
2025-01 cohort" into a Shopify segment / campaign filter.

This applier closes the loop. For each cohort, push a tag
``shopai-cohort-{period}`` on every customer in it via
``SHOPIFY_TAG_CUSTOMER`` (the ``tagsAdd`` GraphQL mutation --
additive). Merchants then save a Shopify admin search for
``shopai-cohort-2025-01`` to retarget that cohort, AND downstream
engines (email_marketing / loyalty / retention) filter on the
cohort tag to fire cohort-aware retention plays.

Two opt-in modes match the established 2-opt-in Phase 6/7 pattern:

  data.apply_cohort_tags=True + data.require_approval=False
    -> SHOPIFY_TAG_CUSTOMER immediately per customer.
  data.apply_cohort_tags=True + data.require_approval=True
    (default) -> enqueue each tag-update proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The cohort has no period or no customer_ids
  * The customer_id is blank
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-customer; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.cohort_analysis.tag_applier")


_TAG_PREFIX = "shopai-cohort-"


def apply_cohort_tags(
    cohorts: list[dict[str, Any]],
    *,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-cohort-{period}`` on each cohort's customers.

    Returns per-customer list with
    ``{customer_id, cohort_period, tag, applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries -- the actual tag lands when
    the dispatcher executes the approved action.
    ``pending_action_id`` is populated for those entries.
    """
    proposals = _build_proposals(cohorts)
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    cohorts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter the engine's cohorts to actionable per-customer rows."""
    proposals: list[dict[str, Any]] = []
    if not isinstance(cohorts, list):
        return proposals
    for cohort in cohorts:
        if not isinstance(cohort, dict):
            continue
        period = str(cohort.get("period") or "").strip()
        if not period:
            continue
        tag = _build_tag(period)
        if not tag:
            continue
        customer_ids = cohort.get("customer_ids") or []
        if not isinstance(customer_ids, list):
            continue
        for cid_raw in customer_ids:
            cid = str(cid_raw or "").strip()
            if not cid:
                continue
            proposals.append({
                "customer_id": cid,
                "cohort_period": period,
                "tag": tag,
            })
    return proposals


def _build_tag(period: str) -> str:
    """Slugify a cohort period into a Shopify-safe tag.

    "2025-01" -> "shopai-cohort-2025-01"
    "2025-01-15" -> "shopai-cohort-2025-01-15"
    Garbage chars are dropped; consecutive dashes collapsed.
    """
    slug_chars: list[str] = []
    for ch in period.lower():
        if ch.isalnum():
            slug_chars.append(ch)
        elif slug_chars and slug_chars[-1] != "-":
            slug_chars.append("-")
    slug = "".join(slug_chars).strip("-")
    if not slug:
        return ""
    return f"{_TAG_PREFIX}{slug}"


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
                "cohort_period": p["cohort_period"],
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
                "cohort_analysis tag_customer raised for %s: %s",
                p["customer_id"], exc,
            )
            _record_writeback_safely(
                customer_id=p["customer_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "customer_id": p["customer_id"],
                "cohort_period": p["cohort_period"],
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
                "cohort_period": p["cohort_period"],
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
                "cohort_period": p["cohort_period"],
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
                "cohort_period": p["cohort_period"],
                "tag": p["tag"],
                "applied": False,
                "error": "approval_queue_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        # Enqueue uses ``customer_id`` + ``tag``. Dispatcher
        # (``tag_cohort_customer``) translates to
        # ``{id, tags: [tag]}`` -- the adapter's accepted shape.
        params = {
            "customer_id": p["customer_id"],
            "tag": p["tag"],
            "cohort_period": p["cohort_period"],
        }
        narrative = (
            f"cohort_analysis: tag customer {p['customer_id']} "
            f"with their cohort ({p['cohort_period']}) "
            f"-> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="cohort_analysis",
                action_type="tag_cohort_customer",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "cohort_analysis enqueue raised for %s: %s",
                p["customer_id"], exc,
            )
            results.append({
                "customer_id": p["customer_id"],
                "cohort_period": p["cohort_period"],
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
            "cohort_period": p["cohort_period"],
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
            engine="cohort_analysis",
            action_type="tag_cohort_customer",
            capability="SHOPIFY_TAG_CUSTOMER",
            params={"customer_id": customer_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cohort_analysis record_writeback raised for %s: %s",
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
