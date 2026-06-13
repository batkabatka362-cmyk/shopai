"""NPS Engine -- NPS-tier tag applier.

Bridges the engine's validated NPS responses into Shopify
CUSTOMER tag updates. Each respondent gets tagged with their
NPS tier so retention + referral campaigns can target them
without re-running the engine.

NPS tier definition (Bain & Company standard):
  * ``nps:promoter``  -- score 9-10 (loyal advocates)
  * ``nps:passive``   -- score 7-8  (satisfied but unenthusiastic)
  * ``nps:detractor`` -- score 0-6  (unhappy; churn + bad-WOM risk)

Fifth customer-tag wireup. Uses SHOPIFY_TAG_CUSTOMER (additive).
Records via Pattern Z.

The applier dedups by customer_id within a single run -- if a
customer submits multiple NPS responses, the MOST RECENT score
(latest in the input list) determines the tag. This matches how
operators typically interpret NPS data (most recent feedback wins).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.nps_engine.tag_applier")


def apply_nps_tags(
    validated_responses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag every respondent with their NPS tier.

    Args:
        validated_responses: From survey_manager. Each carries
            ``customer_id`` + ``score`` (0-10).

    Returns:
        Per-customer results list. Note: customers with multiple
        responses get ONE result (most recent score wins).
    """
    if not isinstance(validated_responses, list) or not validated_responses:
        return []

    # Dedup: most-recent score per customer (last in input list).
    latest_by_cid: dict[str, dict[str, Any]] = {}
    for resp in validated_responses:
        if not isinstance(resp, dict):
            continue
        cid = str(resp.get("customer_id", "")).strip()
        if not cid:
            continue
        latest_by_cid[cid] = resp

    if not latest_by_cid:
        return []

    router = _get_router()
    capability = _get_capability_tag_customer()
    if router is None or capability is None:
        return [
            {
                "customer_id": cid,
                "tier": _score_to_tier(_safe_score(r.get("score"))),
                "applied": False,
                "error": "router_unavailable",
            }
            for cid, r in latest_by_cid.items()
        ]

    results: list[dict[str, Any]] = []
    for cid, resp in latest_by_cid.items():
        score_raw = resp.get("score")
        if score_raw is None:
            continue
        try:
            score = int(score_raw)
        except (TypeError, ValueError):
            continue
        tier = _score_to_tier(score)
        if not tier:
            continue
        nps_tag = f"nps:{tier}"

        recorder_params = {
            "customer_id": cid,
            "tier": tier,
            "score": score,
            "tag": nps_tag,
        }

        try:
            result = router.execute(
                capability,
                {"id": cid, "tags": [nps_tag]},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_nps_tags raised for %s: %s", cid, exc,
            )
            record_writeback(
                engine="nps_engine",
                action_type="apply_nps_tags",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "customer_id": cid, "tier": tier, "score": score,
                "applied": False,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_nps_tags failed for %s: %s", cid, err,
            )
            record_writeback(
                engine="nps_engine",
                action_type="apply_nps_tags",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "customer_id": cid, "tier": tier, "score": score,
                "applied": False,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="nps_engine",
            action_type="apply_nps_tags",
            capability="SHOPIFY_TAG_CUSTOMER",
            params=recorder_params,
            success=True,
        )
        results.append({
            "customer_id": cid, "tier": tier, "score": score,
            "applied": True, "error": None,
        })

    return results


def _score_to_tier(score: int) -> str:
    if score >= 9:
        return "promoter"
    if score >= 7:
        return "passive"
    if score >= 0:
        return "detractor"
    return ""


def _safe_score(raw: Any) -> int:
    if raw is None:
        return -1
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


# -- Helpers ---------------------------------------------------


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "nps_engine tag_applier router lookup raised: %s", exc,
        )
        return None


def _get_capability_tag_customer() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_TAG_CUSTOMER
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "nps_engine tag_applier capability lookup raised: %s",
            exc,
        )
        return None
