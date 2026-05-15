"""Fraud Detection Engine -- Shopify order-tagging applier.

Phase 7 writeback for fraud_detection. The engine produces a
verdict (``approve`` / ``review`` / ``block``) + risk score +
confidence per order. The applier turns ``review`` / ``block``
verdicts into ``SHOPIFY_TAG_ORDER`` calls so the operator's
order view in Shopify Admin shows the risk classification
inline -- no separate dashboard to consult.

Tagging is the SAFEST possible action for a fraud verdict:

  * Reversible (operator can untag any order at any time).
  * Non-destructive (doesn't refund, cancel, or notify).
  * Visible (the tag shows up in every order listing and Admin
    search).
  * Standard Shopify pattern (third-party fraud tools all tag).

The applier defaults to OFF; the engine opts in via either
``data.apply_fraud_tag = True`` (direct execute) or
``data.require_approval = True`` (queue path, recommended).
Approval-queue path is the documented default for the engine
because tagging an order is a customer-visible flag.

Skip semantics (no API call):

  * ``missing_order_id``
  * ``verdict_not_actionable``: engine returned ``approve`` --
    no tag warranted
  * ``below_confidence_threshold``: signal too weak; default
    threshold ``0.6`` (configurable via ``confidence_floor``)
  * ``router_unavailable`` / ``adapter_failed`` /
    ``adapter_raised``: vendor-side failure modes

Mirrors the established Phase 7 applier pattern (tag_management,
discount_strategy, product_lifecycle). Reuses
``record_writeback`` for Phase 8 feedback fan-out.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.fraud_detection.applier")


DEFAULT_CONFIDENCE_FLOOR = 0.6


def _tags_for_verdict(verdict: str, risk_level: str) -> list[str]:
    """Compose the tag list based on engine verdict + risk_level.

    The convention:
      - ``review`` -> ``fraud-review``
      - ``block`` -> ``fraud-block``
      - any verdict at high risk -> add ``fraud-high-risk``

    Standard hyphenated single-word tags so Shopify's tag-based
    filters / searches work cleanly. Operators can rename via
    rule-based Shopify Flow if they want different labels.
    """
    tags: list[str] = []
    if verdict == "review":
        tags.append("fraud-review")
    elif verdict == "block":
        tags.append("fraud-block")
    if risk_level == "high":
        tags.append("fraud-high-risk")
    return tags


def apply_fraud_tag(
    fraud_output: dict[str, Any],
    *,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> list[dict[str, Any]]:
    """Tag a risky order via SHOPIFY_TAG_ORDER.

    Args:
        fraud_output: The engine's output data block --
            ``{order_id, verdict, risk_score, risk_level,
            confidence, ...}``.
        confidence_floor: Minimum confidence to apply a tag.
            Below this the applier skips with
            ``below_confidence_threshold``.

    Returns:
        Per-result list (always exactly one entry today, since
        the engine processes one order at a time -- list shape
        kept for parity with the batch appliers). Each entry has
        ``{order_id, applied, tags, error}``.
    """
    if not isinstance(fraud_output, dict) or not fraud_output:
        return []

    order_id = str(fraud_output.get("order_id", "")).strip()
    verdict = str(fraud_output.get("verdict", "")).strip()
    risk_level = str(fraud_output.get("risk_level", "")).strip()
    confidence = float(fraud_output.get("confidence", 0.0) or 0.0)

    if not order_id:
        return [{
            "order_id": "",
            "applied": False,
            "tags": [],
            "error": "missing_order_id",
        }]

    if verdict not in {"review", "block"}:
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": [],
            "error": "verdict_not_actionable",
        }]

    if confidence < confidence_floor:
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": [],
            "error": "below_confidence_threshold",
        }]

    tags = _tags_for_verdict(verdict, risk_level)
    if not tags:
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": [],
            "error": "no_tag_for_verdict",
        }]

    # ── Adapter resolution ───────────────────────────────────
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
        router = get_router()
        capability = Capability.SHOPIFY_TAG_ORDER
    except Exception as exc:  # noqa: BLE001
        logger.debug("router init failed: %s", exc)
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": tags,
            "error": "router_unavailable",
        }]
    if router is None:
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": tags,
            "error": "router_unavailable",
        }]

    recorder_params = {
        "order_id": order_id,
        "tags": tags,
        "verdict": verdict,
        "risk_score": fraud_output.get("risk_score"),
        "confidence": confidence,
    }

    try:
        result = router.execute(
            capability, {"id": order_id, "tags": tags},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "apply_fraud_tag raised for %s: %s", order_id, exc,
        )
        record_writeback(
            engine="fraud_detection",
            action_type="apply_fraud_tag",
            capability="SHOPIFY_TAG_ORDER",
            params=recorder_params,
            success=False,
            error=f"adapter_raised: {exc}",
        )
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": tags,
            "error": f"adapter_raised: {exc}",
        }]

    if not getattr(result, "ok", False):
        err = getattr(result, "error", "unknown")
        logger.debug(
            "apply_fraud_tag failed for %s: %s", order_id, err,
        )
        record_writeback(
            engine="fraud_detection",
            action_type="apply_fraud_tag",
            capability="SHOPIFY_TAG_ORDER",
            params=recorder_params,
            success=False,
            error=f"adapter_failed: {err}",
        )
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": tags,
            "error": f"adapter_failed: {err}",
        }]

    record_writeback(
        engine="fraud_detection",
        action_type="apply_fraud_tag",
        capability="SHOPIFY_TAG_ORDER",
        params=recorder_params,
        success=True,
    )
    return [{
        "order_id": order_id,
        "applied": True,
        "tags": tags,
        "error": None,
    }]


def enqueue_fraud_tag_for_approval(
    fraud_output: dict[str, Any],
    *,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> list[dict[str, Any]]:
    """Park a fraud-tag action in the approval queue.

    Recommended path for fraud_detection -- tagging is operator-
    visible, so review-before-apply is the safer default. The
    engine's opt-in flag selects this over the direct
    :func:`apply_fraud_tag`.

    Same up-front filters (order_id, actionable verdict,
    confidence floor) so the result-shape stays uniform; on
    success the entry carries ``pending_action_id`` for later
    inspection via ``shopai approvals trace``.
    """
    if not isinstance(fraud_output, dict) or not fraud_output:
        return []

    order_id = str(fraud_output.get("order_id", "")).strip()
    verdict = str(fraud_output.get("verdict", "")).strip()
    risk_level = str(fraud_output.get("risk_level", "")).strip()
    confidence = float(fraud_output.get("confidence", 0.0) or 0.0)
    risk_score = fraud_output.get("risk_score")

    if not order_id:
        return [{
            "order_id": "",
            "applied": False,
            "tags": [],
            "error": "missing_order_id",
            "pending_action_id": None,
        }]
    if verdict not in {"review", "block"}:
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": [],
            "error": "verdict_not_actionable",
            "pending_action_id": None,
        }]
    if confidence < confidence_floor:
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": [],
            "error": "below_confidence_threshold",
            "pending_action_id": None,
        }]

    tags = _tags_for_verdict(verdict, risk_level)
    if not tags:
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": [],
            "error": "no_tag_for_verdict",
            "pending_action_id": None,
        }]

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": tags,
            "error": "approval_queue_unavailable",
            "pending_action_id": None,
        }]

    narrative = (
        f"Tag order {order_id} as {', '.join(tags)} "
        f"(verdict={verdict}, "
        f"risk_score={risk_score}, "
        f"confidence={confidence:.2f})"
    )
    try:
        action = queue.enqueue(
            engine="fraud_detection",
            action_type="apply_fraud_tag",
            capability="SHOPIFY_TAG_ORDER",
            params={
                "order_id": order_id,
                "tags": tags,
                "verdict": verdict,
                "risk_score": risk_score,
                "confidence": confidence,
            },
            narrative=narrative,
            confidence=confidence,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("enqueue raised for %s: %s", order_id, exc)
        return [{
            "order_id": order_id,
            "applied": False,
            "tags": tags,
            "error": f"enqueue_raised: {exc}",
            "pending_action_id": None,
        }]

    return [{
        "order_id": order_id,
        "applied": False,  # queued, not yet executed
        "tags": tags,
        "error": None,
        "pending_action_id": action.id,
    }]
