"""Customer Effort Score Engine -- high-effort tag applier.

Bridges the engine's per-interaction effort scores into Shopify
CUSTOMER tag updates. Customers whose average effort_score across
their interactions exceeds the high-effort threshold get tagged
so customer-service surfaces can prioritize them.

CES is on a 1-7 scale where HIGHER means MORE effort (worse UX):
  * 1-2: very low effort (easy interaction)
  * 3-4: medium effort
  * 5-7: high effort (customer struggling)

Tag:
  * ``ces:high_effort`` -- avg score per customer >= 5

Customers with low/medium effort silently skipped (no UX issue).

Sixth customer-tag wireup. Uses SHOPIFY_TAG_CUSTOMER (additive).
Records via Pattern Z.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.customer_effort_score.tag_applier")


_HIGH_EFFORT_THRESHOLD = 5.0


def apply_high_effort_tags(
    interaction_scores: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag customers whose AVG effort_score exceeds threshold.

    Args:
        interaction_scores: From effort_calculator. Each carries
            ``customer_id`` + ``effort_score``.

    Returns:
        Per-(struggling-customer) results list.
    """
    if not isinstance(interaction_scores, list) or not interaction_scores:
        return []

    # Aggregate to per-customer avg effort.
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for s in interaction_scores:
        if not isinstance(s, dict):
            continue
        cid = str(s.get("customer_id", "")).strip()
        if not cid:
            continue
        try:
            score = float(s.get("effort_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        sums[cid] = sums.get(cid, 0.0) + score
        counts[cid] = counts.get(cid, 0) + 1

    high_effort: dict[str, float] = {}
    for cid, total in sums.items():
        avg = total / counts[cid]
        if avg >= _HIGH_EFFORT_THRESHOLD:
            high_effort[cid] = round(avg, 2)

    if not high_effort:
        return []

    router = _get_router()
    capability = _get_capability_tag_customer()
    if router is None or capability is None:
        return [
            {
                "customer_id": cid,
                "avg_effort_score": avg,
                "applied": False,
                "error": "router_unavailable",
            }
            for cid, avg in high_effort.items()
        ]

    results: list[dict[str, Any]] = []
    for cid, avg in high_effort.items():
        recorder_params = {
            "customer_id": cid,
            "avg_effort_score": avg,
            "interaction_count": counts[cid],
            "tag": "ces:high_effort",
        }

        try:
            result = router.execute(
                capability,
                {"id": cid, "tags": ["ces:high_effort"]},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_high_effort_tags raised for %s: %s", cid, exc,
            )
            record_writeback(
                engine="customer_effort_score",
                action_type="apply_high_effort_tags",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "customer_id": cid, "avg_effort_score": avg,
                "applied": False,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_high_effort_tags failed for %s: %s", cid, err,
            )
            record_writeback(
                engine="customer_effort_score",
                action_type="apply_high_effort_tags",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "customer_id": cid, "avg_effort_score": avg,
                "applied": False,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="customer_effort_score",
            action_type="apply_high_effort_tags",
            capability="SHOPIFY_TAG_CUSTOMER",
            params=recorder_params,
            success=True,
        )
        results.append({
            "customer_id": cid, "avg_effort_score": avg,
            "applied": True, "error": None,
        })

    return results


# -- Helpers ---------------------------------------------------


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "customer_effort_score tag_applier router lookup raised: %s",
            exc,
        )
        return None


def _get_capability_tag_customer() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_TAG_CUSTOMER
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "customer_effort_score tag_applier capability lookup raised: %s",
            exc,
        )
        return None
