"""Tag Management Engine — Shopify product-tag applier.

Bridges the engine's auto-generated tag assignments into actual
Shopify product updates. Each assignment carries
``{product_id, tags: [new tags to apply]}``. The applier builds
a MERGED tag list (existing tags from the input products + new
tags, dedup case-insensitive) and calls ``SHOPIFY_UPDATE_PRODUCT``
with the full set.

Why merge: the productUpdate mutation REPLACES the tags field. If
we passed only the new tags, every existing tag would be wiped.
The hydrator-fetched products carry their current ``tags`` list,
which the applier reads as the merge base.

Returns a list of per-product application results — one entry
per assignment with ``applied: bool`` and ``error: str | None``
so the engine output can show what was written and what was
skipped.

Skipped (no API call) when:
  * The product_id can't be matched in the products list (the
    applier needs the existing tags to merge against).
  * The new tags list is empty after dedup (all already exist).
  * The router is unavailable / the adapter call fails.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._agi_context import (
    explain_thrash_block,
    log_thrash_block,
    should_block_thrashing_store,
)
from engines._writeback_recorder import record_writeback

logger = get_logger("engines.tag_management.applier")


def apply_tags(
    assignments: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply tag assignments via SHOPIFY_UPDATE_PRODUCT.

    Args:
        assignments: List of ``{product_id, tags}`` from the
            auto-tagger.
        products: The hydrated product list — used as the source
            of existing tags to merge against.

    Returns:
        Per-assignment list with ``{product_id, applied, tags_added,
        merged_tags, error}``. ``applied`` is True when the
        adapter call succeeded; ``tags_added`` is the count of
        genuinely-new tags written; ``error`` is set on skip /
        failure (router unavailable, adapter rejection, etc).
    """
    if not isinstance(assignments, list) or not assignments:
        return []

    # product_id → existing-tags lookup.
    existing_by_id = _build_existing_tags_map(products)

    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        # Don't even try — return all-skipped results so the
        # caller has a uniform shape.
        return [
            {
                "product_id": str(a.get("product_id", "")),
                "applied": False,
                "tags_added": 0,
                "merged_tags": [],
                "error": "router_unavailable",
            }
            for a in assignments
        ]

    # Wave 921: thrash guardrail (system-level kill switch).
    # Tag writes are low blast-radius BUT still touch product
    # mutations -- pile-on during thrash is undesirable.
    try:
        from core.context import get_active_store_id
        active_store_id = get_active_store_id()
    except Exception:  # noqa: BLE001
        active_store_id = None
    if should_block_thrashing_store(active_store_id):
        reason = explain_thrash_block(active_store_id)
        record_writeback(
            engine="tag_management",
            action_type="apply_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={"assignment_count": len(assignments)},
            success=False,
            error=reason,
        )
        log_thrash_block(
            engine="tag_management",
            action_type="apply_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            store_id=active_store_id,
        )
        return [
            {
                "product_id": str(a.get("product_id", "")),
                "applied": False,
                "tags_added": 0,
                "merged_tags": [],
                "error": reason,
            }
            for a in assignments
        ]

    results: list[dict[str, Any]] = []
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        pid = str(assignment.get("product_id", "")).strip()
        new_tags_raw = assignment.get("tags") or []
        if not pid or not isinstance(new_tags_raw, list):
            continue

        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, new_tags_raw)

        if added_count == 0:
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "tags_added": added_count,
            "total_tags": len(merged),
        }

        try:
            result = router.execute(
                capability,
                {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("apply_tags raised for %s: %s", pid, exc)
            record_writeback(
                engine="tag_management",
                action_type="apply_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug("apply_tags failed for %s: %s", pid, err)
            record_writeback(
                engine="tag_management",
                action_type="apply_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="tag_management",
            action_type="apply_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid,
            "applied": True,
            "tags_added": added_count,
            "merged_tags": merged,
            "error": None,
        })

    return results


def enqueue_tags_for_approval(
    assignments: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Park tag assignments in the approval queue.

    Per-engine alternative to :func:`apply_tags` — selected by
    the flow when ``data.require_approval=True``. Same upfront
    filters (must have a product_id, a non-empty tags list, and
    at least one genuinely-new tag after the merge); each
    surviving assignment enqueues one pending action.

    Returns the same shape as :func:`apply_tags` plus a
    ``pending_action_id`` field on successfully-queued entries.
    Skip semantics (``no_new_tags`` / queue-unavailable) match
    the direct path so the engine output's ``apply_results``
    field stays uniform across approval / direct branches.
    """
    if not isinstance(assignments, list) or not assignments:
        return []

    existing_by_id = _build_existing_tags_map(products)

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "product_id": str(a.get("product_id", "")),
                "applied": False,
                "tags_added": 0,
                "merged_tags": [],
                "error": "approval_queue_unavailable",
                "pending_action_id": None,
            }
            for a in assignments
        ]

    results: list[dict[str, Any]] = []
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        pid = str(assignment.get("product_id", "")).strip()
        new_tags_raw = assignment.get("tags") or []
        if not pid or not isinstance(new_tags_raw, list):
            continue

        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, new_tags_raw)

        if added_count == 0:
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "error": "no_new_tags",
                "pending_action_id": None,
            })
            continue

        new_only = [t for t in merged if t not in existing]
        narrative = (
            f"Add {added_count} tag(s) to {pid}: "
            f"{', '.join(new_only[:5])}"
            + (f" + {len(new_only) - 5} more" if len(new_only) > 5 else "")
        )
        params = {
            "product_id": pid,
            "merged_tags": merged,
            "tags_added": added_count,
            "new_tags": new_only,
        }

        try:
            action = queue.enqueue(
                engine="tag_management",
                action_type="apply_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "enqueue raised for %s: %s", pid, exc,
            )
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "error": f"enqueue_raised: {exc}",
                "pending_action_id": None,
            })
            continue

        results.append({
            "product_id": pid,
            "applied": False,
            "tags_added": 0,
            "merged_tags": merged,
            "error": "queued",
            "pending_action_id": action.id,
        })

    return results


# ── Helpers ────────────────────────────────────────────────────


def _build_existing_tags_map(
    products: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Map product_id → existing tags list, normalising ids."""
    out: dict[str, list[str]] = {}
    if not isinstance(products, list):
        return out
    for p in products:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id", "")).strip()
        if not pid:
            continue
        raw_tags = p.get("tags") or []
        if isinstance(raw_tags, str):
            # Comma-separated fallback shape.
            raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        out[pid] = [
            str(t).strip() for t in raw_tags
            if isinstance(t, (str, int, float)) and str(t).strip()
        ]
    return out


def _merge_tags(
    existing: list[str], new: list[str],
) -> tuple[list[str], int]:
    """Merge new tags into existing, dedup case-insensitive.

    Returns the merged list (existing order preserved, new tags
    appended) and the count of genuinely-new tags added.
    """
    seen_lower = set()
    merged: list[str] = []
    for tag in existing:
        if not isinstance(tag, str):
            continue
        clean = tag.strip()
        key = clean.lower()
        if not clean or key in seen_lower:
            continue
        seen_lower.add(key)
        merged.append(clean)

    added = 0
    for tag in new:
        if not isinstance(tag, str):
            continue
        clean = tag.strip()
        key = clean.lower()
        if not clean or key in seen_lower:
            continue
        seen_lower.add(key)
        merged.append(clean)
        added += 1

    return merged, added


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


def _get_capability_update_product() -> Any | None:
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return Capability.SHOPIFY_UPDATE_PRODUCT
