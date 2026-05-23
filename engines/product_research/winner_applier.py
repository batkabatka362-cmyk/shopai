"""Product Research Engine -- Shopify winner-tag applier.

Bridges the engine's ranked winners list into actual Shopify
product updates. Each winner with verdict ``strong_buy`` or
``buy`` gets tagged so operators can filter the admin catalog
by research-validated SKUs.

Tags written per winner:
  * ``research:winner`` (generic marker so a single filter
    pulls all validated SKUs)
  * ``research:<verdict>`` (one of strong_buy / buy, so
    operators can split the high-conviction set from the
    rest)

Same merge semantics as ``tag_management.tag_applier``: the
SHOPIFY_UPDATE_PRODUCT mutation REPLACES the tags field, so
we read existing tags from the input products list and merge
(dedup case-insensitive) before writing.

Skipped (no API call) per winner when:
  * verdict is not in {"strong_buy", "buy"} (hold / avoid
    don't earn a tag)
  * product_id can't be matched in the products list (we
    need existing tags to merge against)
  * all the new tags already exist on the product (no-op)
  * router unavailable / adapter rejection / adapter raise

Records via Pattern Z so every apply attempt feeds Phase 8's
learning loop -- the system can later correlate winner-tagged
products with downstream catalog signals (filtered views,
boost ranking, etc).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.product_research.winner_applier")


# Verdicts that earn a winner tag. Hold / avoid winners are
# below the conviction floor for catalog promotion.
_TAGGABLE_VERDICTS = {"strong_buy", "buy"}

# Generic marker tag so filtering admin by a single tag pulls
# every research-validated winner.
_GENERIC_WINNER_TAG = "research:winner"


def apply_winner_tags(
    winners: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag research winners with ``research:winner`` +
    ``research:<verdict>`` via SHOPIFY_UPDATE_PRODUCT.

    Args:
        winners: Ranked winners list from
            ``engines.product_research.run()``'s
            ``data.winners``. Each carries ``product_id`` (or
            ``id``) + ``verdict``.
        products: The input products list -- used as the
            source of existing tags to merge against.

    Returns:
        Per-winner list with ``{product_id, applied,
        tags_added, merged_tags, error}``. ``applied`` is
        True when the adapter call succeeded; ``tags_added``
        is the count of genuinely-new tags written; ``error``
        is set on skip / failure.
    """
    if not isinstance(winners, list) or not winners:
        return []

    existing_by_id = _build_existing_tags_map(products)

    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        # Don't try -- return all-skipped so the caller has
        # a uniform shape.
        return [
            _skip_result(
                _winner_id(w),
                "router_unavailable",
            )
            for w in winners
            if isinstance(w, dict)
            and _winner_id(w)
            and _verdict(w) in _TAGGABLE_VERDICTS
        ]

    results: list[dict[str, Any]] = []
    for winner in winners:
        if not isinstance(winner, dict):
            continue

        pid = _winner_id(winner)
        verdict = _verdict(winner)
        if not pid or verdict not in _TAGGABLE_VERDICTS:
            # Hold / avoid / unscored -- not promoted to the
            # winners filter. Skipped silently (no result
            # row) so the output stays focused on actually-
            # tagged products.
            continue

        new_tags = [_GENERIC_WINNER_TAG, f"research:{verdict}"]
        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, new_tags)

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
            "verdict": verdict,
            "tags_added": added_count,
            "total_tags": len(merged),
        }

        try:
            result = router.execute(
                capability,
                {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_winner_tags raised for %s: %s", pid, exc,
            )
            record_writeback(
                engine="product_research",
                action_type="apply_winner_tags",
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
            logger.debug(
                "apply_winner_tags failed for %s: %s", pid, err,
            )
            record_writeback(
                engine="product_research",
                action_type="apply_winner_tags",
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
            engine="product_research",
            action_type="apply_winner_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid,
            "applied": True,
            "tags_added": added_count,
            "merged_tags": merged,
            "verdict": verdict,
            "error": None,
        })

    return results


# ── Helpers ───────────────────────────────────────────────────


def _winner_id(winner: dict[str, Any]) -> str:
    """Pull product_id from a winner entry. Tolerates ``id``
    or ``product_id`` since the scorer's output field name
    drifts across niches."""
    pid = winner.get("product_id") or winner.get("id") or ""
    return str(pid).strip()


def _verdict(winner: dict[str, Any]) -> str:
    return str(winner.get("verdict", "")).strip().lower()


def _build_existing_tags_map(
    products: list[dict[str, Any]] | None,
) -> dict[str, list[str]]:
    """Map ``product_id -> existing tags`` for merge base."""
    out: dict[str, list[str]] = {}
    if not isinstance(products, list):
        return out
    for product in products:
        if not isinstance(product, dict):
            continue
        pid = str(
            product.get("product_id")
            or product.get("id")
            or "",
        ).strip()
        if not pid:
            continue
        tags = product.get("tags") or []
        if isinstance(tags, str):
            # Shopify sometimes returns tags as a comma-string
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if isinstance(tags, list):
            out[pid] = [str(t) for t in tags if t]
    return out


def _merge_tags(
    existing: list[str],
    new: list[str],
) -> tuple[list[str], int]:
    """Case-insensitive union. Returns (merged_list,
    new_count). Preserves the original casing of existing
    tags."""
    seen_lower = {t.lower() for t in existing if isinstance(t, str)}
    merged = list(existing)
    added = 0
    for tag in new:
        if not isinstance(tag, str):
            continue
        if tag.lower() in seen_lower:
            continue
        merged.append(tag)
        seen_lower.add(tag.lower())
        added += 1
    return merged, added


def _skip_result(pid: str, error: str) -> dict[str, Any]:
    return {
        "product_id": pid,
        "applied": False,
        "tags_added": 0,
        "merged_tags": [],
        "error": error,
    }


def _get_router() -> Any:
    """Lazy router lookup so import order doesn't matter +
    test stubs can substitute."""
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("winner_applier router lookup raised: %s", exc)
        return None


def _get_capability_update_product() -> Any:
    """Lazy capability lookup."""
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "winner_applier capability lookup raised: %s", exc,
        )
        return None
