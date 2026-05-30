"""Dynamic Pricing Engine — Shopify variant price applier.

Bridges the engine's calculated per-product price adjustments
into actual Shopify variant updates. Each adjustment carries
``{product_id, current_price, new_price, change_pct, reason}``;
the applier finds the matching input product, reads its variants,
and calls ``SHOPIFY_UPDATE_VARIANTS`` with the new price set on
every variant of that product.

Why all variants: the engine produces ONE price per product
(matching the typical "set product price to X" semantic). If
variants need per-variant pricing in the future, the engine's
output shape needs to evolve first; for now the writer treats
every variant of a product as receiving the same new price.

Skipped (no API call) when:

  * The adjustment isn't ``approved`` (validation gate). Engines
    that bypass validation pass adjustments with no approved key
    — those are skipped by design (apply_changes is opt-in but
    a non-validated adjustment shouldn't be auto-applied).
  * The product can't be located in the input list — the applier
    needs the variant list to know what to update.
  * The product has no ``variants`` array. Hydrator-fetched
    products from ``SHOPIFY_LIST_PRODUCTS`` don't include
    variants; callers should pre-fetch with
    ``SHOPIFY_GET_PRODUCT`` (or supply pre-enriched products) if
    they want price changes applied. Documented as a known
    limitation rather than a silent surprise.
  * The router is unavailable / the adapter call fails.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._agi_context import (
    explain_thrash_block,
    should_block_thrashing_store,
)
from engines._writeback_recorder import record_writeback

logger = get_logger("engines.dynamic_pricing.applier")


def apply_price_changes(
    adjustments: list[dict[str, Any]],
    products: list[dict[str, Any]],
    *,
    require_approved: bool = True,
) -> list[dict[str, Any]]:
    """Apply approved price adjustments via SHOPIFY_UPDATE_VARIANTS.

    Args:
        adjustments: Per-product adjustment dicts from the engine.
            Each carries ``product_id``, ``new_price``,
            ``change_pct``, ``reason``, and (when validation ran)
            ``approved``.
        products: The input product list — used as the source of
            variant_ids. Each product needs a ``variants`` list
            with ``id`` (Shopify GID) per variant.
        require_approved: When True (default), only adjustments
            with an explicit ``approved=True`` field are applied.
            Pass False for callers that pre-filter their own
            approval decisions before reaching the writer.

    Returns:
        Per-adjustment list with ``{product_id, applied,
        variants_updated, new_price, error}``. ``applied`` is True
        when the adapter call succeeded; ``error`` is set on every
        skip / failure mode (router unavailable, no variants
        available, validation block, adapter rejection).
    """
    if not isinstance(adjustments, list) or not adjustments:
        return []

    variants_by_product = _build_variants_map(products)

    router = _get_router()
    capability = _get_capability_update_variants()
    if router is None or capability is None:
        return [
            {
                "product_id": str(a.get("product_id", "")),
                "applied": False,
                "variants_updated": 0,
                "new_price": _safe_float(a.get("new_price")),
                "error": "router_unavailable",
            }
            for a in adjustments
        ]

    # Wave 920: thrash guardrail (system-level kill switch).
    # Refuse ALL adjustments when active store is thrashing.
    # Price changes during thrash compound the upstream race.
    try:
        from core.context import get_active_store_id
        active_store_id = get_active_store_id()
    except Exception:  # noqa: BLE001
        active_store_id = None
    if should_block_thrashing_store(active_store_id):
        reason = explain_thrash_block(active_store_id)
        record_writeback(
            engine="dynamic_pricing",
            action_type="apply_price_change",
            capability="SHOPIFY_UPDATE_VARIANTS",
            params={"adjustment_count": len(adjustments)},
            success=False,
            error=reason,
        )
        return [
            {
                "product_id": str(a.get("product_id", "")),
                "applied": False,
                "variants_updated": 0,
                "new_price": _safe_float(a.get("new_price")),
                "error": reason,
            }
            for a in adjustments
        ]

    results: list[dict[str, Any]] = []
    for adj in adjustments:
        if not isinstance(adj, dict):
            continue
        pid = str(adj.get("product_id", "")).strip()
        new_price = _safe_float(adj.get("new_price"))
        if not pid or new_price is None:
            continue

        if require_approved and not _is_approved(adj):
            results.append({
                "product_id": pid,
                "applied": False,
                "variants_updated": 0,
                "new_price": new_price,
                "error": "not_approved",
            })
            continue

        variant_ids = variants_by_product.get(pid) or []
        if not variant_ids:
            results.append({
                "product_id": pid,
                "applied": False,
                "variants_updated": 0,
                "new_price": new_price,
                "error": "no_variants_in_input",
            })
            continue

        # Format price as a string with 2 decimals — the
        # productVariantsBulkUpdate API expects a money string.
        price_str = f"{new_price:.2f}"
        variants_payload = [
            {"id": vid, "price": price_str} for vid in variant_ids
        ]

        recorder_params = {
            "product_id": pid,
            "new_price": new_price,
            "variant_count": len(variant_ids),
        }

        try:
            result = router.execute(
                capability,
                {"product_id": pid, "variants": variants_payload},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_price_changes raised for %s: %s", pid, exc,
            )
            record_writeback(
                engine="dynamic_pricing",
                action_type="apply_price_change",
                capability="SHOPIFY_UPDATE_VARIANTS",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid,
                "applied": False,
                "variants_updated": 0,
                "new_price": new_price,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_price_changes failed for %s: %s", pid, err,
            )
            record_writeback(
                engine="dynamic_pricing",
                action_type="apply_price_change",
                capability="SHOPIFY_UPDATE_VARIANTS",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid,
                "applied": False,
                "variants_updated": 0,
                "new_price": new_price,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="dynamic_pricing",
            action_type="apply_price_change",
            capability="SHOPIFY_UPDATE_VARIANTS",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid,
            "applied": True,
            "variants_updated": len(variant_ids),
            "new_price": new_price,
            "error": None,
        })

    return results


def enqueue_price_changes_for_approval(
    adjustments: list[dict[str, Any]],
    products: list[dict[str, Any]],
    *,
    require_approved: bool = True,
) -> list[dict[str, Any]]:
    """Park approved price adjustments in the approval queue.

    Per-engine alternative to :func:`apply_price_changes` —
    selected by the flow when ``data.require_approval=True``.
    Same upfront filters (must have a product_id, valid
    new_price, change_validator approval, and a non-empty
    variant list); each surviving adjustment enqueues one
    pending action.

    Returns the same shape as :func:`apply_price_changes` but
    with ``applied=False`` and ``error="queued"`` plus an extra
    ``pending_action_id`` field on successfully-queued entries.
    Skip semantics (``not_approved`` / ``no_variants_in_input`` /
    ``router_unavailable``) match the direct path so the engine's
    downstream consumers don't need to special-case the approval
    branch.
    """
    if not isinstance(adjustments, list) or not adjustments:
        return []

    variants_by_product = _build_variants_map(products)

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "product_id": str(a.get("product_id", "")),
                "applied": False,
                "variants_updated": 0,
                "new_price": _safe_float(a.get("new_price")),
                "error": "approval_queue_unavailable",
                "pending_action_id": None,
            }
            for a in adjustments
        ]

    results: list[dict[str, Any]] = []
    for adj in adjustments:
        if not isinstance(adj, dict):
            continue
        pid = str(adj.get("product_id", "")).strip()
        new_price = _safe_float(adj.get("new_price"))
        if not pid or new_price is None:
            continue

        if require_approved and not _is_approved(adj):
            results.append({
                "product_id": pid,
                "applied": False,
                "variants_updated": 0,
                "new_price": new_price,
                "error": "not_approved",
                "pending_action_id": None,
            })
            continue

        variant_ids = variants_by_product.get(pid) or []
        if not variant_ids:
            results.append({
                "product_id": pid,
                "applied": False,
                "variants_updated": 0,
                "new_price": new_price,
                "error": "no_variants_in_input",
                "pending_action_id": None,
            })
            continue

        change_pct = _safe_float(adj.get("change_pct"))
        reason = str(adj.get("reason", ""))[:160]
        narrative = (
            f"Set product {pid} price → ${new_price:.2f} "
            f"({len(variant_ids)} variants"
            + (f", {change_pct:+.1f}%" if change_pct is not None else "")
            + (f", reason: {reason}" if reason else "")
            + ")"
        )
        params = {
            "product_id": pid,
            "new_price": new_price,
            "variant_ids": variant_ids,
            "change_pct": change_pct,
            "reason": reason,
        }

        try:
            action = queue.enqueue(
                engine="dynamic_pricing",
                action_type="apply_price_change",
                capability="SHOPIFY_UPDATE_VARIANTS",
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
                "variants_updated": 0,
                "new_price": new_price,
                "error": f"enqueue_raised: {exc}",
                "pending_action_id": None,
            })
            continue

        results.append({
            "product_id": pid,
            "applied": False,
            "variants_updated": 0,
            "new_price": new_price,
            "error": "queued",
            "pending_action_id": action.id,
        })

    return results


# ── Helpers ────────────────────────────────────────────────────


def _build_variants_map(
    products: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Map product_id → list of variant GIDs from the input."""
    out: dict[str, list[str]] = {}
    if not isinstance(products, list):
        return out
    for p in products:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id", "")).strip()
        if not pid:
            continue
        variants_raw = p.get("variants")
        if not isinstance(variants_raw, list):
            continue
        ids: list[str] = []
        for v in variants_raw:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("id", "")).strip()
            if vid:
                ids.append(vid)
        if ids:
            out[pid] = ids
    return out


def _is_approved(adj: dict[str, Any]) -> bool:
    """Return True only if the adjustment is explicitly approved.

    Adjustments coming through the engine's full pipeline have
    ``approved`` set by the change_validator stage. When that
    stage returns ``approved=True``, the adjustment carries the
    new_price; when False, the engine output already shows
    new_price=current_price so the change is a no-op anyway.

    The applier still re-checks the flag because callers that
    construct adjustments manually shouldn't be able to bypass
    the gate just by skipping the validator.
    """
    raw = adj.get("approved")
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"true", "1", "yes"}


def _safe_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val < 0:
        return None
    return val


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


def _get_capability_update_variants() -> Any | None:
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return Capability.SHOPIFY_UPDATE_VARIANTS
