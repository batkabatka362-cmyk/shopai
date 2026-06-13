"""Cohort Analysis Engine -- Shopify customer cohort tag applier.

Bridges the engine's cohort list into Shopify CUSTOMER tag
updates. Each customer gets tagged with their signup-cohort
period so marketing campaigns can target by cohort (e.g.,
``cohort:2026-05`` for May-2026 signups).

First customer-tag wireup in the Phase 7 stack -- previous
appliers wrote product tags via SHOPIFY_UPDATE_PRODUCT.
Customer tagging uses SHOPIFY_TAG_CUSTOMER (tagsAdd) which is
ADDITIVE (Shopify merges with existing tags), so we don't
need the read-merge-write dance.

Tag written per customer:
  * ``cohort:<period>`` (period = cohort_builder's
    "YYYY-MM" identifier)

Records via Pattern Z so cohort-tagging fans into the
learning loop the same way other writebacks do.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.cohort_analysis.tag_applier")


def apply_cohort_tags(
    cohorts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag every customer in every cohort with
    ``cohort:<period>`` via SHOPIFY_TAG_CUSTOMER.

    Args:
        cohorts: From ``CohortAnalysisEngine.run()``'s
            ``data.cohorts``. Each carries ``period`` +
            ``customer_ids`` list.

    Returns:
        Per-customer results list with ``{customer_id,
        cohort, applied, error}``.
    """
    if not isinstance(cohorts, list) or not cohorts:
        return []

    router = _get_router()
    capability = _get_capability_tag_customer()
    if router is None or capability is None:
        return [
            {
                "customer_id": str(cid),
                "cohort": str(cohort.get("period", "")),
                "applied": False,
                "error": "router_unavailable",
            }
            for cohort in cohorts
            if isinstance(cohort, dict)
            for cid in cohort.get("customer_ids", []) or []
            if cid
        ]

    results: list[dict[str, Any]] = []
    for cohort in cohorts:
        if not isinstance(cohort, dict):
            continue
        period = str(cohort.get("period", "")).strip()
        if not period:
            continue
        cohort_tag = f"cohort:{period}"
        customer_ids = cohort.get("customer_ids", []) or []

        for cid in customer_ids:
            cid_str = str(cid).strip()
            if not cid_str:
                continue
            recorder_params = {
                "customer_id": cid_str,
                "cohort": period,
                "tag": cohort_tag,
            }

            try:
                result = router.execute(
                    capability,
                    {"id": cid_str, "tags": [cohort_tag]},
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "apply_cohort_tags raised for %s: %s",
                    cid_str, exc,
                )
                record_writeback(
                    engine="cohort_analysis",
                    action_type="apply_cohort_tags",
                    capability="SHOPIFY_TAG_CUSTOMER",
                    params=recorder_params,
                    success=False,
                    error=f"adapter_raised: {exc}",
                )
                results.append({
                    "customer_id": cid_str,
                    "cohort": period,
                    "applied": False,
                    "error": f"adapter_raised: {exc}",
                })
                continue

            if not getattr(result, "ok", False):
                err = getattr(result, "error", "unknown")
                logger.debug(
                    "apply_cohort_tags failed for %s: %s",
                    cid_str, err,
                )
                record_writeback(
                    engine="cohort_analysis",
                    action_type="apply_cohort_tags",
                    capability="SHOPIFY_TAG_CUSTOMER",
                    params=recorder_params,
                    success=False,
                    error=f"adapter_failed: {err}",
                )
                results.append({
                    "customer_id": cid_str,
                    "cohort": period,
                    "applied": False,
                    "error": f"adapter_failed: {err}",
                })
                continue

            record_writeback(
                engine="cohort_analysis",
                action_type="apply_cohort_tags",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=True,
            )
            results.append({
                "customer_id": cid_str,
                "cohort": period,
                "applied": True,
                "error": None,
            })

    return results


# ── Helpers ───────────────────────────────────────────────────


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cohort tag_applier router lookup raised: %s", exc,
        )
        return None


def _get_capability_tag_customer() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_TAG_CUSTOMER
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cohort tag_applier capability lookup raised: %s",
            exc,
        )
        return None
