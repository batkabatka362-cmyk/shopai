"""Search Optimization Engine — Shopify SEO field applier.

Phase 7.3 wireup. The engine produces ``meta_recommendations``
per product — optimised meta titles + descriptions for SEO. This
applier pushes those into ``SHOPIFY_UPDATE_PRODUCT.seo`` (the
nested ``{ title, description }`` field on every product).

Required a small adapter extension first: the products adapter
now accepts flat ``seo_title`` / ``seo_description`` params and
converts them to Shopify's nested ``seo: { title, description }``
input shape. See PR for the full mutation.

Same opt-in pattern as Phase 6/7:

  * ``data.apply_seo == True`` toggles the writer on. Default
    OFF — the engine's recommendations stay advisory unless
    explicitly applied.
  * Per-recommendation results so the engine output shows what
    was written, what was skipped, and why.
  * Phase 8 integration: every adapter call (success or
    failure) records via ``record_writeback`` so the autonomous
    loop can correlate SEO meta changes with search-traffic
    impact.

Skip modes (per recommendation):

  * ``product_id_missing`` — the recommendation has no GID.
  * ``no_changes`` — both title and description match the
    current meta. Don't waste an API call when there's nothing
    to write.
  * ``router_unavailable`` — the entire SmartRouter isn't
    configured.
  * ``adapter_failed`` / ``adapter_raised`` — the GraphQL call
    rejected or raised.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.search_optimization.applier")


def apply_meta(
    recommendations: list[dict[str, Any]],
    current_meta: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Apply SEO meta recommendations via SHOPIFY_UPDATE_PRODUCT.

    Args:
        recommendations: List of meta recommendations from the
            engine. Each carries ``product_id``, ``title``
            (proposed meta title), ``description`` (proposed meta
            description), ``keywords``, ``improvements``.
        current_meta: Optional list of ``{product_id, title,
            description}`` representing the current Shopify SEO
            state. Used to short-circuit when proposed == current
            (no API call needed).

    Returns:
        Per-recommendation list with ``{product_id, applied,
        title_updated, description_updated, error}``.
    """
    if not isinstance(recommendations, list) or not recommendations:
        return []

    current_by_id = _index_current_meta(current_meta)

    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            {
                "product_id": str(r.get("product_id", "")),
                "applied": False,
                "title_updated": False,
                "description_updated": False,
                "error": "router_unavailable",
            }
            for r in recommendations
        ]

    results: list[dict[str, Any]] = []
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        pid = str(rec.get("product_id", "")).strip()
        if not pid:
            continue

        proposed_title = str(rec.get("title", "")).strip()
        proposed_desc = str(rec.get("description", "")).strip()

        current = current_by_id.get(pid, {})
        title_updated = (
            bool(proposed_title)
            and proposed_title != str(current.get("title", "")).strip()
        )
        desc_updated = (
            bool(proposed_desc)
            and proposed_desc !=
            str(current.get("description", "")).strip()
        )

        if not title_updated and not desc_updated:
            results.append({
                "product_id": pid,
                "applied": False,
                "title_updated": False,
                "description_updated": False,
                "error": "no_changes",
            })
            continue

        params: dict[str, Any] = {"id": pid}
        if title_updated:
            params["seo_title"] = proposed_title
        if desc_updated:
            params["seo_description"] = proposed_desc

        recorder_params = {
            "product_id": pid,
            "title_updated": title_updated,
            "description_updated": desc_updated,
        }

        try:
            result = router.execute(capability, params)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_meta raised for %s: %s", pid, exc,
            )
            record_writeback(
                engine="search_optimization",
                action_type="apply_seo_meta",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid,
                "applied": False,
                "title_updated": False,
                "description_updated": False,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_meta failed for %s: %s", pid, err,
            )
            record_writeback(
                engine="search_optimization",
                action_type="apply_seo_meta",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid,
                "applied": False,
                "title_updated": False,
                "description_updated": False,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="search_optimization",
            action_type="apply_seo_meta",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid,
            "applied": True,
            "title_updated": title_updated,
            "description_updated": desc_updated,
            "error": None,
        })

    return results


def enqueue_meta_for_approval(
    recommendations: list[dict[str, Any]],
    current_meta: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Park SEO meta recommendations in the approval queue.

    Per-engine alternative to :func:`apply_meta` — selected by
    the flow when ``data.require_approval=True``. Same upfront
    filters (must have a product_id, at least one of
    title/description must differ from the current value);
    surviving recommendations each enqueue one pending action.

    Returns the same shape as :func:`apply_meta` plus a
    ``pending_action_id`` field on successfully-queued entries.
    Skip semantics match the direct path so the engine output's
    downstream consumers don't need to special-case the approval
    branch.
    """
    if not isinstance(recommendations, list) or not recommendations:
        return []

    current_by_id = _index_current_meta(current_meta)

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "product_id": str(r.get("product_id", "")),
                "applied": False,
                "title_updated": False,
                "description_updated": False,
                "error": "approval_queue_unavailable",
                "pending_action_id": None,
            }
            for r in recommendations
        ]

    results: list[dict[str, Any]] = []
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        pid = str(rec.get("product_id", "")).strip()
        if not pid:
            continue

        proposed_title = str(rec.get("title", "")).strip()
        proposed_desc = str(rec.get("description", "")).strip()

        current = current_by_id.get(pid, {})
        title_updated = (
            bool(proposed_title)
            and proposed_title != str(current.get("title", "")).strip()
        )
        desc_updated = (
            bool(proposed_desc)
            and proposed_desc !=
            str(current.get("description", "")).strip()
        )

        if not title_updated and not desc_updated:
            results.append({
                "product_id": pid,
                "applied": False,
                "title_updated": False,
                "description_updated": False,
                "error": "no_changes",
                "pending_action_id": None,
            })
            continue

        change_parts = []
        if title_updated:
            change_parts.append(f"title → \"{proposed_title[:60]}\"")
        if desc_updated:
            desc_preview = proposed_desc[:80]
            change_parts.append(f"description → \"{desc_preview}\"")
        narrative = (
            f"Update SEO meta for {pid}: " + "; ".join(change_parts)
        )
        params = {
            "product_id": pid,
            "title_updated": title_updated,
            "description_updated": desc_updated,
            "proposed_title": proposed_title if title_updated else None,
            "proposed_description": proposed_desc if desc_updated else None,
        }

        try:
            action = queue.enqueue(
                engine="search_optimization",
                action_type="apply_seo_meta",
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
                "title_updated": False,
                "description_updated": False,
                "error": f"enqueue_raised: {exc}",
                "pending_action_id": None,
            })
            continue

        results.append({
            "product_id": pid,
            "applied": False,
            "title_updated": title_updated,
            "description_updated": desc_updated,
            "error": "queued",
            "pending_action_id": action.id,
        })

    return results


# ── Helpers ────────────────────────────────────────────────────


def _index_current_meta(
    current_meta: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Index current meta entries by product_id for diff checks."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(current_meta, list):
        return out
    for entry in current_meta:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("product_id", "")).strip()
        if pid:
            out[pid] = entry
    return out


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
