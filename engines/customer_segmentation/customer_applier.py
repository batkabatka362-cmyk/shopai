"""Customer Segmentation Engine — Shopify segment-tag applier.

The segmentation engine emits ``segments = [{name, size,
customers: [id...], avg_clv, strategy}, ...]`` — each customer
classified into exactly one named segment (e.g. ``VIP
Champions``, ``At-Risk Loyalists``, ``Dormant Cart-Abandoners``).
Pre-fix the segment names landed only in the engine output —
the merchant couldn't pull a "show me all VIPs" view in Shopify
admin without manually saving a search per segment.

This applier closes the loop. For each customer, push a tag
``shopai-segment-{slug}`` via ``SHOPIFY_TAG_CUSTOMER`` (the
``tagsAdd`` GraphQL mutation — additive, no need to merge with
existing tags the way ``productUpdate.tags`` does).

Two opt-in modes match the established Phase 6/7 pattern:

  data.apply_segment_tags=True + data.require_approval=False
    → SHOPIFY_TAG_CUSTOMER immediately per customer
  data.apply_segment_tags=True + data.require_approval=True
    → enqueue each tag-update proposal to core.approval;
      merchant approves via /api/pending-actions before the
      mutation lands

Default OFF — existing callers keep their pure-recommendation
contract. Skipped (no API call / no queue entry) when:

  * The customer has no Shopify id (engine accepts arbitrary
    ids, some pipelines feed internal customer numbers).
  * The segment is the fallback ``Unclassified`` bucket
    (tagging customers with ``shopai-segment-unclassified``
    is noise — merchants want signal, not "system couldn't
    decide").
  * The router is unavailable / capability missing (direct path).
  * The queue is unavailable (approval path).
  * The adapter raises or rejects (per-customer, doesn't halt
    the batch).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.customer_segmentation.applier")


_TAG_PREFIX = "shopai-segment-"
_FALLBACK_SEGMENT = "Unclassified"


def apply_segment_tags(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Stamp ``shopai-segment-{slug}`` on each customer.

    Returns per-customer list with ``{customer_id, segment, tag,
    applied, error}``. ``applied=True`` when the
    ``tagsAdd`` mutation succeeded; ``error`` is populated on
    every skip / failure mode (no_customer_id, fallback_segment,
    router_unavailable, adapter_raised, adapter_failed).
    """
    proposals = _build_proposals(segments)
    if not proposals:
        return []

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        return [
            {
                "customer_id": p["customer_id"],
                "segment": p["segment"],
                "tag": p["tag"],
                "applied": False,
                "error": "router_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        recorder_params = {
            "customer_id": p["customer_id"],
            "segment": p["segment"],
            "tag": p["tag"],
        }
        try:
            result = router.execute(
                capability,
                {"id": p["customer_id"], "tags": [p["tag"]]},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_segment_tags raised for %s: %s",
                p["customer_id"], exc,
            )
            record_writeback(
                engine="customer_segmentation",
                action_type="apply_segment_tag",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "customer_id": p["customer_id"],
                "segment": p["segment"],
                "tag": p["tag"],
                "applied": False,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            record_writeback(
                engine="customer_segmentation",
                action_type="apply_segment_tag",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "customer_id": p["customer_id"],
                "segment": p["segment"],
                "tag": p["tag"],
                "applied": False,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="customer_segmentation",
            action_type="apply_segment_tag",
            capability="SHOPIFY_TAG_CUSTOMER",
            params=recorder_params,
            success=True,
        )
        results.append({
            "customer_id": p["customer_id"],
            "segment": p["segment"],
            "tag": p["tag"],
            "applied": True,
            "error": None,
        })

    return results


def enqueue_segment_tags_for_approval(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-engine alternative to :func:`apply_segment_tags`.

    Same upfront filter (skip no-id / Unclassified) and same
    per-customer result shape; on success each entry carries
    ``pending_action_id`` and ``error="queued"`` instead of
    ``applied=True``.
    """
    proposals = _build_proposals(segments)
    if not proposals:
        return []

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "customer_id": p["customer_id"],
                "segment": p["segment"],
                "tag": p["tag"],
                "applied": False,
                "error": "approval_queue_unavailable",
                "pending_action_id": None,
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        narrative = (
            f"Tag customer {p['customer_id']} as "
            f"'{p['segment']}' ({p['tag']})"
        )
        params = {
            "customer_id": p["customer_id"],
            "tag": p["tag"],
            "segment": p["segment"],
        }
        try:
            action = queue.enqueue(
                engine="customer_segmentation",
                action_type="apply_segment_tag",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "enqueue raised for %s: %s", p["customer_id"], exc,
            )
            results.append({
                "customer_id": p["customer_id"],
                "segment": p["segment"],
                "tag": p["tag"],
                "applied": False,
                "error": f"enqueue_raised: {exc}",
                "pending_action_id": None,
            })
            continue

        results.append({
            "customer_id": p["customer_id"],
            "segment": p["segment"],
            "tag": p["tag"],
            "applied": False,
            "error": "queued",
            "pending_action_id": action.id,
        })

    return results


# ── Proposal builder ──────────────────────────────────────────


def _build_proposals(
    segments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Walk the segments and produce one
    ``{customer_id, segment, tag}`` per customer.

    Filters:
      * Skip the ``Unclassified`` fallback segment (tagging
        customers with ``shopai-segment-unclassified`` is noise).
      * Skip blank / non-string customer ids.
      * Skip segments missing a name.

    Each customer should appear in exactly ONE segment (the
    builder's design), so no dedup is needed across segments.
    """
    if not isinstance(segments, list):
        return []

    out: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        name = str(seg.get("name", "")).strip()
        if not name or name == _FALLBACK_SEGMENT:
            continue
        tag = _build_tag(name)
        customers = seg.get("customers") or []
        if not isinstance(customers, list):
            continue
        for cid_raw in customers:
            cid = str(cid_raw).strip()
            if not cid:
                continue
            out.append({
                "customer_id": cid,
                "segment": name,
                "tag": tag,
            })
    return out


def _build_tag(segment_name: str) -> str:
    """Slugify a segment name into a Shopify-safe tag.

    "VIP Champions" → "shopai-segment-vip-champions"
    "At-Risk Loyalists" → "shopai-segment-at-risk-loyalists"
    """
    slug_chars: list[str] = []
    for ch in segment_name.lower():
        if ch.isalnum():
            slug_chars.append(ch)
        elif slug_chars and slug_chars[-1] != "-":
            slug_chars.append("-")
    slug = "".join(slug_chars).strip("-")
    return f"{_TAG_PREFIX}{slug or 'unknown'}"


# ── Router boilerplate ────────────────────────────────────────


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


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return Capability.SHOPIFY_TAG_CUSTOMER
