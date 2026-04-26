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

        try:
            result = router.execute(capability, {
                "id": product_id,
                "tags": cleaned_tags,
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "tag apply raised for %s: %s", product_id, exc,
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
            _stamp_skipped(assignment, err)
            continue

        assignment["applied"] = True
        assignment["apply_error"] = ""

    return assignments


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
