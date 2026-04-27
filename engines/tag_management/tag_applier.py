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

        try:
            result = router.execute(
                capability,
                {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("apply_tags raised for %s: %s", pid, exc)
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
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "error": f"adapter_failed: {err}",
            })
            continue

        results.append({
            "product_id": pid,
            "applied": True,
            "tags_added": added_count,
            "merged_tags": merged,
            "error": None,
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
