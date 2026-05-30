"""Product Lifecycle Engine — Shopify status applier.

Phase 7's first wireup. The engine classifies each product's
lifecycle stage (``introduction`` / ``growth`` / ``maturity`` /
``decline``). Products in the ``decline`` stage with low velocity
are candidates for archival — moving them to ``status=ARCHIVED``
in Shopify so they stop appearing in the storefront / marketing
without being deleted (their order history stays intact).

This is the FIRST destructive Phase 6/7 writeback (loyalty,
discount_strategy, tag_management, dynamic_pricing, affiliate
all created NEW data; this one CHANGES existing product
visibility). So the safety guardrails are stricter:

  * Only acts on ``stage == "decline"``.
  * Velocity floor — won't archive a product that's still moving
    (default: velocity < 0.5 units/day across the trailing window).
  * Optional ``min_confidence`` floor (the engine's stage_classifier
    emits per-stage confidence; the writer can require ≥ 0.7).
  * Always opt-in via ``data.apply_archives = True``.

Returns per-product results so the engine output shows what was
archived, what was kept active, and what was skipped (with reason).
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

logger = get_logger("engines.product_lifecycle.applier")


# Default velocity threshold below which a declining product is
# eligible for archival. Velocity is units-per-day from the engine's
# velocity_tracker stage. Tunable per call via ``min_velocity``.
_DEFAULT_VELOCITY_FLOOR = 0.5

# The engine emits multiple lifecycle stages. Only this one is
# actionable as an archival decision.
_ARCHIVABLE_STAGE = "decline"


def archive_declining_products(
    lifecycle: list[dict[str, Any]],
    *,
    min_confidence: float = 0.0,
    velocity_floor: float = _DEFAULT_VELOCITY_FLOOR,
) -> list[dict[str, Any]]:
    """Archive products in the decline stage with low velocity.

    Args:
        lifecycle: Per-product lifecycle entries from the engine.
            Each carries ``product_id``, ``stage``, ``velocity``,
            ``projected_transition``, and (optionally)
            ``confidence``.
        min_confidence: Floor on per-product confidence. Engine's
            stage_classifier emits this between 0 and 1; default 0
            accepts any. Pass 0.7+ for stricter gating.
        velocity_floor: Velocity below which the product is
            considered truly declining. Default 0.5 units/day.

    Returns:
        Per-entry list with ``{product_id, archived, stage,
        velocity, error}``. ``archived`` is True when the adapter
        call succeeded; ``error`` is set on every skip / failure.
    """
    if not isinstance(lifecycle, list) or not lifecycle:
        return []

    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            {
                "product_id": str(e.get("product_id", "")),
                "archived": False,
                "stage": str(e.get("stage", "")),
                "velocity": _safe_float(e.get("velocity")),
                "error": "router_unavailable",
            }
            for e in lifecycle
        ]

    # Wave 923: thrash guardrail (system-level kill switch).
    # Product archiving is a MODIFICATION-class writer (per
    # CLAUDE.md risk taxonomy) -- refuse during thrash so an
    # upstream race doesn't compound into mass-archiving.
    try:
        from core.context import get_active_store_id
        active_store_id = get_active_store_id()
    except Exception:  # noqa: BLE001
        active_store_id = None
    if should_block_thrashing_store(active_store_id):
        reason = explain_thrash_block(active_store_id)
        record_writeback(
            engine="product_lifecycle",
            action_type="archive_product",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={"lifecycle_count": len(lifecycle)},
            success=False,
            error=reason,
        )
        log_thrash_block(
            engine="product_lifecycle",
            action_type="archive_product",
            capability="SHOPIFY_UPDATE_PRODUCT",
            store_id=active_store_id,
        )
        return [
            {
                "product_id": str(e.get("product_id", "")),
                "archived": False,
                "stage": str(e.get("stage", "")),
                "velocity": _safe_float(e.get("velocity")),
                "error": reason,
            }
            for e in lifecycle
        ]

    results: list[dict[str, Any]] = []
    for entry in lifecycle:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("product_id", "")).strip()
        if not pid:
            continue
        stage = str(entry.get("stage", "")).lower()
        velocity = _safe_float(entry.get("velocity")) or 0.0

        # Stage gate.
        if stage != _ARCHIVABLE_STAGE:
            results.append({
                "product_id": pid,
                "archived": False,
                "stage": stage,
                "velocity": velocity,
                "error": "stage_not_archivable",
            })
            continue

        # Velocity gate — won't archive products still moving.
        if velocity >= velocity_floor:
            results.append({
                "product_id": pid,
                "archived": False,
                "stage": stage,
                "velocity": velocity,
                "error": "velocity_above_floor",
            })
            continue

        # Confidence gate (optional).
        confidence = _safe_float(entry.get("confidence"))
        if confidence is not None and confidence < min_confidence:
            results.append({
                "product_id": pid,
                "archived": False,
                "stage": stage,
                "velocity": velocity,
                "error": "below_min_confidence",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "stage": stage,
            "velocity": velocity,
        }

        try:
            result = router.execute(
                capability,
                {"id": pid, "status": "ARCHIVED"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "archive_declining_products raised for %s: %s", pid, exc,
            )
            record_writeback(
                engine="product_lifecycle",
                action_type="archive_declining_product",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid,
                "archived": False,
                "stage": stage,
                "velocity": velocity,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "archive_declining_products failed for %s: %s", pid, err,
            )
            record_writeback(
                engine="product_lifecycle",
                action_type="archive_declining_product",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid,
                "archived": False,
                "stage": stage,
                "velocity": velocity,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="product_lifecycle",
            action_type="archive_declining_product",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid,
            "archived": True,
            "stage": stage,
            "velocity": velocity,
            "error": None,
        })

    return results


def enqueue_archives_for_approval(
    lifecycle: list[dict[str, Any]],
    *,
    min_confidence: float = 0.0,
    velocity_floor: float = _DEFAULT_VELOCITY_FLOOR,
) -> list[dict[str, Any]]:
    """Park archive proposals in the approval queue.

    Per-engine alternative to :func:`archive_declining_products`
    — selected by the flow when ``data.require_approval=True``.
    Same triple-gate (stage / velocity / confidence) as the
    direct path; surviving entries each enqueue one pending
    action.

    Archives are the first DESTRUCTIVE writeback wired through
    the queue (loyalty / discount / dynamic_pricing /
    tag_management / affiliate all created NEW state). The
    approval gate is therefore especially valuable here — a
    wrongly-archived product disappears from the storefront
    until manually un-archived.

    Returns the same shape as
    :func:`archive_declining_products` plus a
    ``pending_action_id`` field on successfully-queued entries.
    """
    if not isinstance(lifecycle, list) or not lifecycle:
        return []

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "product_id": str(e.get("product_id", "")),
                "archived": False,
                "stage": str(e.get("stage", "")),
                "velocity": _safe_float(e.get("velocity")),
                "error": "approval_queue_unavailable",
                "pending_action_id": None,
            }
            for e in lifecycle
        ]

    results: list[dict[str, Any]] = []
    for entry in lifecycle:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("product_id", "")).strip()
        if not pid:
            continue
        stage = str(entry.get("stage", "")).lower()
        velocity = _safe_float(entry.get("velocity")) or 0.0

        if stage != _ARCHIVABLE_STAGE:
            results.append({
                "product_id": pid,
                "archived": False,
                "stage": stage,
                "velocity": velocity,
                "error": "stage_not_archivable",
                "pending_action_id": None,
            })
            continue

        if velocity >= velocity_floor:
            results.append({
                "product_id": pid,
                "archived": False,
                "stage": stage,
                "velocity": velocity,
                "error": "velocity_above_floor",
                "pending_action_id": None,
            })
            continue

        confidence = _safe_float(entry.get("confidence"))
        if confidence is not None and confidence < min_confidence:
            results.append({
                "product_id": pid,
                "archived": False,
                "stage": stage,
                "velocity": velocity,
                "error": "below_min_confidence",
                "pending_action_id": None,
            })
            continue

        narrative = (
            f"Archive declining product {pid} "
            f"(stage={stage}, velocity={velocity:.2f}/day"
            + (f", confidence={confidence:.2f}" if confidence is not None else "")
            + ") — DESTRUCTIVE, hides from storefront"
        )
        params = {
            "product_id": pid,
            "stage": stage,
            "velocity": velocity,
            "confidence": confidence,
            "status": "ARCHIVED",
        }

        try:
            action = queue.enqueue(
                engine="product_lifecycle",
                action_type="archive_declining_product",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=params,
                narrative=narrative,
                confidence=confidence,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "enqueue raised for %s: %s", pid, exc,
            )
            results.append({
                "product_id": pid,
                "archived": False,
                "stage": stage,
                "velocity": velocity,
                "error": f"enqueue_raised: {exc}",
                "pending_action_id": None,
            })
            continue

        results.append({
            "product_id": pid,
            "archived": False,
            "stage": stage,
            "velocity": velocity,
            "error": "queued",
            "pending_action_id": action.id,
        })

    return results


# ── Helpers ────────────────────────────────────────────────────


def _safe_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


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
