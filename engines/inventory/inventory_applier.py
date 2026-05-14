"""Inventory Engine — Shopify state-tag applier.

The inventory engine's alerts + stockout_risks already flag the
SKUs the merchant should pay attention to. Pre-fix that flagging
was advisory only — the merchant had to manually re-create a
saved-search view on the Shopify admin to find these SKUs.

This applier closes the loop by pushing **inventory-state tags**
back onto each flagged product:

  * ``shopai-stockout-imminent``  — stockout_risks with risk_level
                                    "imminent" (next 7 days)
  * ``shopai-needs-reorder``      — reorder_calculations with
                                    ``needs_reorder=True``
  * ``shopai-dead-stock``         — stock_analysis flagged as
                                    "dead" (no sales in 90 days)
  * ``shopai-overstocked``        — stock_analysis flagged as
                                    "overstocked"

Tags merge with the product's existing tags — same case-
insensitive dedup pattern tag_management uses — so a manual
"premium" tag the operator added by hand isn't clobbered.

Two opt-in modes, matching the established Phase 6/7 pattern:

  data.apply_inventory_tags=True + data.require_approval=False
    → SHOPIFY_UPDATE_PRODUCT immediately per flagged SKU
  data.apply_inventory_tags=True + data.require_approval=True
    → enqueue each tag-update proposal to core.approval; merchant
      approves via /api/pending-actions before the mutation lands

Default OFF. Same risk gradient as the other Phase 6/7 appliers
— flagged SKUs go through the queue when ``require_approval``
is set, so a misclassified "dead stock" tag doesn't auto-apply
without human review.

Skipped (no API call) when:
  * Router unavailable / capability missing.
  * SKU has no Shopify id (engine output sometimes carries
    internal-only ids for forecasted but unmapped SKUs).
  * No state tags would be added (every relevant tag already on
    the product after the merge — same short-circuit as
    tag_management's ``no_new_tags``).
  * The adapter raises or rejects.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.inventory.applier")


# State tags this applier knows how to stamp. Each maps to a
# signal in the engine output.
_TAG_STOCKOUT_IMMINENT = "shopai-stockout-imminent"
_TAG_NEEDS_REORDER = "shopai-needs-reorder"
_TAG_DEAD_STOCK = "shopai-dead-stock"
_TAG_OVERSTOCKED = "shopai-overstocked"


def apply_inventory_tags(
    products: list[dict[str, Any]],
    stockout_risks: list[dict[str, Any]],
    reorder_calculations: list[dict[str, Any]],
    stock_analyses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Stamp inventory-state tags onto flagged products.

    Returns per-product list with ``{product_id, applied,
    tags_added, merged_tags, error}``. Skip semantics match the
    tag_management applier (same merge dedup, same
    ``no_new_tags`` short-circuit).
    """
    tag_assignments = _build_tag_assignments(
        stockout_risks=stockout_risks,
        reorder_calculations=reorder_calculations,
        stock_analyses=stock_analyses,
    )
    if not tag_assignments:
        return []

    existing_by_id = _build_existing_tags_map(products)

    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            {
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": [],
                "error": "router_unavailable",
            }
            for pid in tag_assignments.keys()
        ]

    results: list[dict[str, Any]] = []
    for pid, state_tags in tag_assignments.items():
        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, state_tags)
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
            "state_tags": state_tags,
            "tags_added": added_count,
        }
        try:
            result = router.execute(
                capability, {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_inventory_tags raised for %s: %s", pid, exc,
            )
            record_writeback(
                engine="inventory",
                action_type="apply_inventory_tags",
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
            record_writeback(
                engine="inventory",
                action_type="apply_inventory_tags",
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
            engine="inventory",
            action_type="apply_inventory_tags",
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


def enqueue_inventory_tags_for_approval(
    products: list[dict[str, Any]],
    stockout_risks: list[dict[str, Any]],
    reorder_calculations: list[dict[str, Any]],
    stock_analyses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-engine alternative to :func:`apply_inventory_tags`.

    Same triple-source flag aggregation (stockout_risks /
    reorder_calculations / stock_analyses), same merge-with-existing
    contract; on success each entry carries ``pending_action_id``
    and ``error="queued"`` instead of ``applied=True``.
    """
    tag_assignments = _build_tag_assignments(
        stockout_risks=stockout_risks,
        reorder_calculations=reorder_calculations,
        stock_analyses=stock_analyses,
    )
    if not tag_assignments:
        return []

    existing_by_id = _build_existing_tags_map(products)

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": [],
                "error": "approval_queue_unavailable",
                "pending_action_id": None,
            }
            for pid in tag_assignments.keys()
        ]

    results: list[dict[str, Any]] = []
    for pid, state_tags in tag_assignments.items():
        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, state_tags)
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

        narrative = (
            f"Apply {added_count} inventory state-tag(s) to {pid}: "
            f"{', '.join(state_tags)}"
        )
        params = {
            "product_id": pid,
            "merged_tags": merged,
            "state_tags": state_tags,
            "tags_added": added_count,
        }
        try:
            action = queue.enqueue(
                engine="inventory",
                action_type="apply_inventory_tags",
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


# ── Tag-aggregation logic ──────────────────────────────────────


def _build_tag_assignments(
    *,
    stockout_risks: list[dict[str, Any]],
    reorder_calculations: list[dict[str, Any]],
    stock_analyses: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Walk the three engine output streams and produce a
    ``{product_id → [state_tags]}`` map.

    A single SKU can earn multiple state tags (e.g. a SKU that's
    both flagged as needs-reorder AND has an imminent stockout
    forecast gets both tags on the same product). The applier
    later dedups + merges with existing tags.
    """
    out: dict[str, list[str]] = {}

    def _add(pid: str, tag: str) -> None:
        if not pid:
            return
        bucket = out.setdefault(pid, [])
        if tag not in bucket:
            bucket.append(tag)

    if isinstance(stockout_risks, list):
        for entry in stockout_risks:
            if not isinstance(entry, dict):
                continue
            risk_level = str(entry.get("risk_level", "")).lower()
            if risk_level not in {"imminent", "high"}:
                continue
            pid = str(entry.get("id", "")).strip()
            _add(pid, _TAG_STOCKOUT_IMMINENT)

    if isinstance(reorder_calculations, list):
        for entry in reorder_calculations:
            if not isinstance(entry, dict):
                continue
            if not entry.get("needs_reorder"):
                continue
            pid = str(entry.get("id", "")).strip()
            _add(pid, _TAG_NEEDS_REORDER)

    if isinstance(stock_analyses, list):
        for entry in stock_analyses:
            if not isinstance(entry, dict):
                continue
            classification = str(entry.get("classification", "")).lower()
            pid = str(entry.get("id", "")).strip()
            if classification == "dead":
                _add(pid, _TAG_DEAD_STOCK)
            elif classification == "overstocked":
                _add(pid, _TAG_OVERSTOCKED)

    return out


# ── Tag-merge logic (same dedup pattern as tag_management) ─────


def _build_existing_tags_map(
    products: list[dict[str, Any]],
) -> dict[str, list[str]]:
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
            raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        out[pid] = [
            str(t).strip() for t in raw_tags
            if isinstance(t, (str, int, float)) and str(t).strip()
        ]
    return out


def _merge_tags(
    existing: list[str], new: list[str],
) -> tuple[list[str], int]:
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


def _get_capability_update_product() -> Any | None:
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return Capability.SHOPIFY_UPDATE_PRODUCT
