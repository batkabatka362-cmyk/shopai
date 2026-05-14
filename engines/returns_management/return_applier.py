"""Returns Management Engine — order-tag writeback for return decisions.

The returns_management engine's ``processed`` output carries
per-return decisions (``status`` = approved / rejected,
``refund_amount``, ``rejection_reason``). Pre-fix that data was
advisory only — the merchant had to manually filter their order
admin to find returns the engine had recommended approving or
rejecting.

This applier tags the order so the merchant can filter natively
in Shopify admin:

  * ``shopai-return-approved``     — engine recommends approving
  * ``shopai-return-rejected``     — engine recommends rejecting
  * ``shopai-return-fraud-flag``   — return matched a fraud signal

We deliberately do NOT issue actual refunds via this applier.
Refunds are real money out, and ``refundCreate`` needs a
transaction-parent-id lookup the engine doesn't carry — that's
a future executor enhancement once the queue's executor learns
the transaction-lookup dance. Tagging the order is a safer
first cut: merchant filters by tag, eyeballs the suggestion,
and issues the refund manually (or future automation).

Two opt-in modes (same Phase 6/7 pattern):

  data.apply_return_tags=True + data.require_approval=False
    → SHOPIFY_TAG_ORDER immediately per processed return
  data.apply_return_tags=True + data.require_approval=True
    → enqueue each per-return tag proposal to core.approval

Skipped:
  * Return has no order_id (engine sometimes carries internal-
    only ids for unmapped returns).
  * No actionable tag to add (e.g. status is something other
    than "approved" / "rejected" / fraud-flagged).
  * Adapter fails or router unavailable.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.returns_management.applier")


_TAG_APPROVED = "shopai-return-approved"
_TAG_REJECTED = "shopai-return-rejected"
_TAG_FRAUD = "shopai-return-fraud-flag"


def apply_return_tags(
    processed: list[dict[str, Any]],
    fraud_flags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag the order for each processed return.

    Returns per-return list with ``{return_id, order_id, applied,
    tags, error}``. Errors surface on every skip / failure mode.
    """
    if not isinstance(processed, list) or not processed:
        return []

    fraud_return_ids = _fraud_return_ids(fraud_flags)

    router = _get_router()
    capability = _get_capability_tag_order()
    if router is None or capability is None:
        return [
            {
                "return_id": str(p.get("return_id", "")),
                "order_id": str(p.get("order_id", "")),
                "applied": False,
                "tags": [],
                "error": "router_unavailable",
            }
            for p in processed
        ]

    results: list[dict[str, Any]] = []
    for entry in processed:
        if not isinstance(entry, dict):
            continue
        return_id = str(entry.get("return_id", "")).strip()
        order_id = str(entry.get("order_id", "")).strip()
        tags = _tags_for_decision(entry, fraud_return_ids)

        base = {
            "return_id": return_id,
            "order_id": order_id,
        }
        if not order_id:
            results.append({
                **base, "applied": False, "tags": tags,
                "error": "order_id_missing",
            })
            continue
        if not tags:
            results.append({
                **base, "applied": False, "tags": [],
                "error": "no_actionable_tag",
            })
            continue

        recorder_params = {
            "return_id": return_id,
            "order_id": order_id,
            "tags": tags,
        }
        try:
            result = router.execute(
                capability, {"id": order_id, "tags": tags},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_return_tags raised for %s: %s",
                order_id, exc,
            )
            record_writeback(
                engine="returns_management",
                action_type="tag_return_decision",
                capability="SHOPIFY_TAG_ORDER",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                **base, "applied": False, "tags": tags,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            record_writeback(
                engine="returns_management",
                action_type="tag_return_decision",
                capability="SHOPIFY_TAG_ORDER",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                **base, "applied": False, "tags": tags,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="returns_management",
            action_type="tag_return_decision",
            capability="SHOPIFY_TAG_ORDER",
            params=recorder_params,
            success=True,
        )
        results.append({
            **base, "applied": True, "tags": tags, "error": None,
        })

    return results


def enqueue_return_tags_for_approval(
    processed: list[dict[str, Any]],
    fraud_flags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Park per-return tag proposals in the approval queue.

    Same decision logic as :func:`apply_return_tags`; on success
    each entry carries ``pending_action_id`` and
    ``error="queued"`` instead of ``applied=True``.
    """
    if not isinstance(processed, list) or not processed:
        return []

    fraud_return_ids = _fraud_return_ids(fraud_flags)

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "return_id": str(p.get("return_id", "")),
                "order_id": str(p.get("order_id", "")),
                "applied": False,
                "tags": [],
                "error": "approval_queue_unavailable",
                "pending_action_id": None,
            }
            for p in processed
        ]

    results: list[dict[str, Any]] = []
    for entry in processed:
        if not isinstance(entry, dict):
            continue
        return_id = str(entry.get("return_id", "")).strip()
        order_id = str(entry.get("order_id", "")).strip()
        tags = _tags_for_decision(entry, fraud_return_ids)

        base = {
            "return_id": return_id,
            "order_id": order_id,
        }
        if not order_id:
            results.append({
                **base, "applied": False, "tags": tags,
                "error": "order_id_missing",
                "pending_action_id": None,
            })
            continue
        if not tags:
            results.append({
                **base, "applied": False, "tags": [],
                "error": "no_actionable_tag",
                "pending_action_id": None,
            })
            continue

        narrative_bits = [
            f"return {return_id} on order {order_id}:",
            f"tag {', '.join(tags)}",
        ]
        refund_amount = entry.get("refund_amount")
        if refund_amount:
            narrative_bits.append(f"(refund ${refund_amount:g} pending)")
        narrative = " ".join(narrative_bits)

        params = {
            "return_id": return_id,
            "order_id": order_id,
            "tags": tags,
            "refund_amount": refund_amount,
            "decision_status": entry.get("status"),
            "rejection_reason": entry.get("rejection_reason"),
        }
        try:
            action = queue.enqueue(
                engine="returns_management",
                action_type="tag_return_decision",
                capability="SHOPIFY_TAG_ORDER",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "enqueue raised for %s: %s", order_id, exc,
            )
            results.append({
                **base, "applied": False, "tags": tags,
                "error": f"enqueue_raised: {exc}",
                "pending_action_id": None,
            })
            continue

        results.append({
            **base, "applied": False, "tags": tags,
            "error": "queued",
            "pending_action_id": action.id,
        })

    return results


# ── Helpers ───────────────────────────────────────────────────


def _fraud_return_ids(
    fraud_flags: list[dict[str, Any]] | None,
) -> set[str]:
    """Return ids that triggered fraud signals."""
    out: set[str] = set()
    if not isinstance(fraud_flags, list):
        return out
    for flag in fraud_flags:
        if not isinstance(flag, dict):
            continue
        rid = str(flag.get("return_id", "")).strip()
        if rid:
            out.add(rid)
    return out


def _tags_for_decision(
    entry: dict[str, Any], fraud_return_ids: set[str],
) -> list[str]:
    """Map a processed-return entry to a list of state tags.

    Empty list when nothing actionable (status is neither
    "approved" nor "rejected" AND the return isn't fraud-flagged).
    """
    tags: list[str] = []
    status = str(entry.get("status", "")).lower()
    if status == "approved":
        tags.append(_TAG_APPROVED)
    elif status == "rejected":
        tags.append(_TAG_REJECTED)
    return_id = str(entry.get("return_id", "")).strip()
    if return_id and return_id in fraud_return_ids:
        tags.append(_TAG_FRAUD)
    return tags


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router
    except Exception as exc:  # noqa: BLE001
        logger.debug("router import failed: %s", exc)
        return None
    try:
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("router init failed: %s", exc)
        return None


def _get_capability_tag_order() -> Any | None:
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return Capability.SHOPIFY_TAG_ORDER
