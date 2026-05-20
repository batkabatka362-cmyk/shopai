"""Phase 7 writeback for product_optimization.

Bridges the engine's advisory pricing adjustments into actual
Shopify mutations via the approval queue. Mirrors the established
Phase 6 / 7 pattern (loyalty PR #43, discount_strategy PR #44,
dynamic_pricing PR #46, etc.):

  1. Default OFF — operator opts in by setting
     ``data.apply_pricing_adjustments = True`` in the engine
     input payload.
  2. Each qualifying adjustment is enqueued via
     ``ApprovalQueue.enqueue(action_type="apply_strategic_price",
     capability="SHOPIFY_UPDATE_VARIANTS", ...)`` — same wire
     format the dynamic_pricing engine uses (dispatcher landed
     in PR #159).
  3. Output gains a ``pricing_pending_actions`` list (empty when
     not opted in, populated when adjustments queue successfully)
     so callers see what was queued and what was skipped.
  4. Writeback recorded via :mod:`engines._writeback_recorder`
     so Phase 8 feedback systems (MemoryIntelligence,
     DataArchitecture, LearningLoop) learn from the action.

Three guardrails before enqueue:
  - ``adjustment_pct`` must be materially non-zero (> 0.1%) —
    no-op adjustments are advisory only.
  - The product must have at least one variant ID (Shopify's
    ``UPDATE_VARIANTS`` requires per-variant ids; hydrated
    product lists from ``SHOPIFY_LIST_PRODUCTS`` often miss
    variants, in which case the operator pre-fetches via
    ``SHOPIFY_GET_PRODUCT``).
  - ``suggested_price`` must be positive.

Failed enqueues are recorded in the per-adjustment skip reason
so the engine output explains every decision.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("engines.product_optimization.applier")

# Default threshold — match the engine's existing flow.py
# filter at line 144 (``if abs(adj.get("adjustment_pct")) > 0.1``)
# so opt-in writeback and advisory output stay aligned.
_MIN_ADJUSTMENT_PCT = 0.1


def apply_pricing_optimizations(
    adjustments: list[dict[str, Any]],
    products: list[dict[str, Any]],
    store: dict[str, Any] | None = None,
    *,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Apply Shopify variant-price updates for each qualifying
    adjustment.

    Two paths, selected by ``require_approval``:

      * ``require_approval=True`` (default) -- enqueue each
        adjustment via the approval queue. The operator (or
        the auto-approve allowlist) approves, then the queue
        dispatcher executes. Safer; preserves the
        human-in-the-loop default the engine has shipped with.
      * ``require_approval=False`` -- call
        ``Capability.SHOPIFY_UPDATE_VARIANTS`` directly through
        the adapter router, bypassing the queue. Used by
        cycles that already have an auto-approve allowlist
        gating this engine, or for ad-hoc operator-triggered
        bulk applies.

    Args:
        adjustments: engine's per-product price recommendations
            (output of ``price_adjuster.adjust_prices``).
        products: the same products list the adjuster ran against
            -- used to look up variant IDs that aren't on the
            adjustment row itself.
        store: optional store context passed through to the
            recorder; not used in the enqueue wire format.
        require_approval: When True, enqueue via approval queue
            (default). When False, call SHOPIFY_UPDATE_VARIANTS
            directly through the router.

    Returns:
        A list of result dicts (one per adjustment), each
        carrying ``status`` (``queued`` | ``applied`` |
        ``skipped``), the ``pending_action_id`` (queue path),
        and the ``reason`` (when skipped). The order matches
        the input.
    """
    results: list[dict[str, Any]] = []
    if not isinstance(adjustments, list) or not adjustments:
        return results

    # Build variant-id lookup from the products list. Each
    # product is expected to carry a ``variants`` list with
    # ``id`` fields; if missing or empty, the adjustment skips.
    variant_lookup: dict[str, list[str]] = {}
    if isinstance(products, list):
        for p in products:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id") or p.get("product_id") or "")
            if not pid:
                continue
            variants = p.get("variants") or []
            if not isinstance(variants, list):
                continue
            variant_ids = [
                str(v.get("id") or "")
                for v in variants
                if isinstance(v, dict) and v.get("id")
            ]
            if variant_ids:
                variant_lookup[pid] = variant_ids

    for adj in adjustments:
        if not isinstance(adj, dict):
            results.append({
                "status": "skipped",
                "reason": "adjustment_not_a_dict",
            })
            continue

        product_id = str(adj.get("product_id", "")).strip()
        suggested_price = adj.get("suggested_price")
        adjustment_pct = adj.get("adjustment_pct", 0.0)

        # ── Guard: product id required ───────────────────────
        if not product_id:
            results.append({
                "status": "skipped",
                "reason": "missing_product_id",
            })
            continue

        # ── Guard: material price change ─────────────────────
        try:
            pct_abs = abs(float(adjustment_pct))
        except (TypeError, ValueError):
            pct_abs = 0.0
        if pct_abs <= _MIN_ADJUSTMENT_PCT:
            results.append({
                "status": "skipped",
                "product_id": product_id,
                "reason": "adjustment_below_threshold",
            })
            continue

        # ── Guard: positive suggested price ──────────────────
        try:
            price = float(suggested_price)
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            results.append({
                "status": "skipped",
                "product_id": product_id,
                "reason": "non_positive_price",
            })
            continue

        # ── Guard: variant ids must be available ─────────────
        variant_ids = variant_lookup.get(product_id, [])
        if not variant_ids:
            results.append({
                "status": "skipped",
                "product_id": product_id,
                "reason": "missing_variant_ids",
            })
            continue

        # ── Common params ────────────────────────────────────
        narrative = (
            f"product_optimization: adjust price to "
            f"${price:.2f} ({adjustment_pct:+.1f}%) — "
            f"{adj.get('rationale', '')}"
        ).strip()
        params: dict[str, Any] = {
            "product_id": product_id,
            "new_price": price,
            "variant_ids": list(variant_ids),
            "current_price": adj.get("current_price"),
            "adjustment_pct": adjustment_pct,
            "rationale": adj.get("rationale", ""),
        }

        if require_approval:
            # ── Path A: enqueue for approval ────────────────
            try:
                from core.approval import get_approval_queue
                action = get_approval_queue().enqueue(
                    engine="product_optimization",
                    action_type="apply_strategic_price",
                    capability="SHOPIFY_UPDATE_VARIANTS",
                    params=params,
                    narrative=narrative,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "product_optimization enqueue raised "
                    "for %s: %s", product_id, exc,
                )
                results.append({
                    "status": "skipped",
                    "product_id": product_id,
                    "reason": f"enqueue_raised: {exc}",
                })
                continue

            _record_writeback_safely(
                params=params, success=True,
            )

            results.append({
                "status": "queued",
                "product_id": product_id,
                "pending_action_id": action.id,
                "suggested_price": price,
                "adjustment_pct": adjustment_pct,
            })
            continue

        # ── Path B: direct execute via router ───────────────
        result = _direct_apply_via_router(
            product_id=product_id,
            new_price=price,
            variant_ids=variant_ids,
        )
        if result.get("ok"):
            _record_writeback_safely(
                params=params, success=True,
            )
            results.append({
                "status": "applied",
                "product_id": product_id,
                "suggested_price": price,
                "adjustment_pct": adjustment_pct,
                "variants_updated": result.get(
                    "variants_updated", 0,
                ),
            })
        else:
            err = result.get("error", "unknown")
            _record_writeback_safely(
                params=params, success=False, error=err,
            )
            results.append({
                "status": "skipped",
                "product_id": product_id,
                "reason": f"direct_apply_failed: {err}",
            })

    return results


def _record_writeback_safely(
    *,
    params: dict[str, Any],
    success: bool,
    error: str | None = None,
) -> None:
    """Best-effort Phase 8 writeback recording. Failures are
    logged and swallowed so the recorder never breaks the
    apply path."""
    try:
        from engines._writeback_recorder import record_writeback
        record_writeback(
            engine="product_optimization",
            action_type="apply_strategic_price",
            capability="SHOPIFY_UPDATE_VARIANTS",
            params=params,
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "writeback recorder raised for %s: %s",
            params.get("product_id", ""), exc,
        )


def _direct_apply_via_router(
    *,
    product_id: str,
    new_price: float,
    variant_ids: list[str],
) -> dict[str, Any]:
    """Call ``SHOPIFY_UPDATE_VARIANTS`` directly via the
    adapter router. Returns ``{ok, variants_updated, error}``.
    Never raises."""
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"router_import_failed: {exc}",
        }
    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False, "error": f"router_init_failed: {exc}",
        }

    payload = {
        "product_id": product_id,
        "variants": [
            {"id": vid, "price": f"{new_price:.2f}"}
            for vid in variant_ids
        ],
    }
    try:
        result = router.execute(
            Capability.SHOPIFY_UPDATE_VARIANTS, payload,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"router_raised: {exc}",
        }

    if not getattr(result, "ok", False):
        return {
            "ok": False,
            "error": str(getattr(result, "error", "rejected")),
        }
    return {
        "ok": True,
        "variants_updated": len(variant_ids),
    }
