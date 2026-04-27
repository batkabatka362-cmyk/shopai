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
