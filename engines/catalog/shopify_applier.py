"""Catalog Engine — Shopify tag applier.

Companion to the hydrator (read side). The catalog engine's
tag_assigner produces an ``assignments`` list — one record per
product with a recommended tag list. Without this stage, those
recommendations are inert: the engine returns "Product X should be
tagged budget,seasonal,winter-2026" but doesn't actually push the
tags to Shopify, so the storefront filters / collections that
depend on tags don't update.

This module bridges the gap by calling ``Capability.SHOPIFY_ADD_TAGS``
(merges tags — preserves any tags already on the product that the
engine didn't recommend, so manual operator work isn't clobbered)
per assignment.

Default behavior is opt-OUT (``apply=True`` on the input data block
flips it on). The recommendation list still flows through the
engine's output regardless — this is purely about pushing the
recommendations to live Shopify.

Each assignment dict gets two new fields stamped on:
  * ``applied`` — ``True`` if SHOPIFY_ADD_TAGS succeeded.
  * ``apply_error`` — error message string (empty when applied).

Graceful behavior:
  * Router unavailable → all assignments stamped applied=False with
    apply_error="router unavailable". Pipeline continues.
  * Per-assignment adapter failure → that assignment alone is
    stamped failed; others continue.
  * Empty product_id / empty tags / non-list garbage → skipped
    with a meaningful apply_error.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("catalog.shopify_applier")


def apply_tag_assignments(
    assignments: list[dict[str, Any]],
    *,
    apply: bool = False,
) -> list[dict[str, Any]]:
    """Apply tag assignments to Shopify. Mutates each in place.

    Args:
        assignments: List of {product_id, tags, ...} dicts from
            the tag_assigner stage.
        apply: Master switch. False (default) → no network calls,
            every assignment stamped applied=False with
            apply_error="apply disabled by caller". This is the
            safe default — engines run dry until the operator
            explicitly opts in.

    Returns:
        The same assignments list (mutated). Returned for chain
        readability.
    """
    if not assignments:
        return assignments

    if not apply:
        for assignment in assignments:
            _stamp_skipped(assignment, "apply disabled by caller")
        return assignments

    router = _get_router()
    capability = _get_capability_add_tags()
    if router is None or capability is None:
        for assignment in assignments:
            _stamp_skipped(assignment, "router unavailable")
        return assignments

    for assignment in assignments:
        product_id = str(assignment.get("product_id", "")).strip()
        if not product_id:
            _stamp_skipped(assignment, "missing product_id")
            continue
        tags = assignment.get("tags")
        if not isinstance(tags, list) or not tags:
            _stamp_skipped(assignment, "no tags to apply")
            continue
        cleaned_tags = [
            str(t).strip() for t in tags
            if isinstance(t, str) and t.strip()
        ]
        if not cleaned_tags:
            _stamp_skipped(assignment, "no tags to apply")
            continue

        recorder_params = {
            "product_id": product_id,
            "tag_count": len(cleaned_tags),
        }

        try:
            result = router.execute(capability, {
                "id": product_id,
                "tags": cleaned_tags,
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "tag apply raised for %s: %s", product_id, exc,
            )
            _record_writeback(
                action_type="catalog_apply_tags",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            _stamp_skipped(
                assignment, f"adapter raised: {exc}",
            )
            continue

        if not getattr(result, "ok", False):
            err = str(getattr(result, "error", "unknown"))
            logger.debug(
                "tag apply failed for %s: %s", product_id, err,
            )
            _record_writeback(
                action_type="catalog_apply_tags",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            _stamp_skipped(assignment, err)
            continue

        _record_writeback(
            action_type="catalog_apply_tags",
            params=recorder_params,
            success=True,
        )
        assignment["applied"] = True
        assignment["apply_error"] = ""

    return assignments


def enqueue_tag_assignments_for_approval(
    assignments: list[dict[str, Any]],
    *,
    apply: bool = False,
) -> list[dict[str, Any]]:
    """Park catalog tag assignments in the approval queue.

    Per-engine alternative to :func:`apply_tag_assignments` —
    selected by the flow when ``data.require_approval=True``.
    The catalog applier mutates assignments in place (rather than
    returning a separate result list), so this enqueue function
    keeps that contract: each parked assignment is stamped with
    ``applied=False``, ``apply_error="queued"``, and a
    ``pending_action_id`` for the merchant approval flow.

    Skip semantics match the direct path so the engine output
    looks identical regardless of which branch ran:
      * ``apply=False`` (master switch off) → all stamped
        ``"apply disabled by caller"`` (no queue entry).
      * Missing product_id / no tags → stamped accordingly.
      * Approval queue unavailable → all stamped
        ``"approval queue unavailable"``.
    """
    if not assignments:
        return assignments

    if not apply:
        for assignment in assignments:
            _stamp_skipped(assignment, "apply disabled by caller")
        return assignments

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        for assignment in assignments:
            _stamp_skipped(assignment, "approval queue unavailable")
        return assignments

    for assignment in assignments:
        product_id = str(assignment.get("product_id", "")).strip()
        if not product_id:
            _stamp_skipped(assignment, "missing product_id")
            continue
        tags = assignment.get("tags")
        if not isinstance(tags, list) or not tags:
            _stamp_skipped(assignment, "no tags to apply")
            continue
        cleaned_tags = [
            str(t).strip() for t in tags
            if isinstance(t, str) and t.strip()
        ]
        if not cleaned_tags:
            _stamp_skipped(assignment, "no tags to apply")
            continue

        narrative = (
            f"Add {len(cleaned_tags)} tag(s) to {product_id}: "
            f"{', '.join(cleaned_tags[:5])}"
            + (f" + {len(cleaned_tags) - 5} more"
               if len(cleaned_tags) > 5 else "")
        )
        params = {
            "product_id": product_id,
            "tags": cleaned_tags,
            "tag_count": len(cleaned_tags),
        }

        try:
            action = queue.enqueue(
                engine="catalog",
                action_type="catalog_apply_tags",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "enqueue raised for %s: %s", product_id, exc,
            )
            _stamp_skipped(
                assignment, f"enqueue raised: {exc}",
            )
            continue

        assignment["applied"] = False
        assignment["apply_error"] = "queued"
        assignment["pending_action_id"] = action.id

    return assignments


def _record_writeback(
    *,
    action_type: str,
    params: dict[str, Any],
    success: bool,
    error: str | None = None,
) -> None:
    """Best-effort feed of catalog tag writes to the autonomous-loop
    recorder (Phase 8). Wrapped in its own helper so the import is
    lazy — keeps catalog usable in environments where the
    learning-loop infra isn't bootstrapped (the recorder itself is
    already graceful, but the import path may not be available in
    every test fixture).
    """
    try:
        from engines._writeback_recorder import record_writeback
    except Exception as exc:  # noqa: BLE001
        logger.debug("recorder import failed: %s", exc)
        return
    try:
        record_writeback(
            engine="catalog",
            action_type=action_type,
            capability="SHOPIFY_ADD_TAGS",
            params=params,
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("recorder call failed: %s", exc)


# ── Helpers ────────────────────────────────────────────────────


def _stamp_skipped(
    assignment: dict[str, Any], reason: str,
) -> None:
    assignment["applied"] = False
    assignment["apply_error"] = reason


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


def _get_capability_add_tags() -> Any | None:
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return Capability.SHOPIFY_ADD_TAGS
