"""Per-engine dispatchers — replay parked params through appliers.

Each function is registered against an ``action_type`` and turns
the queue's friendly-form ``params`` dict back into the engine /
adapter call that the original opt-in path would have run.

Coverage (one entry per Phase 6/7 applier):

  * ``mint_strategy_code``        — discount_strategy
  * ``mint_loyalty_code``         — loyalty
  * ``apply_price_change``        — dynamic_pricing
  * ``apply_tags``                — tag_management
  * ``pay_commission``            — affiliate
  * ``archive_declining_product`` — product_lifecycle
  * ``apply_description``         — content_generation
  * ``apply_seo_meta``            — search_optimization
  * ``catalog_apply_tags``        — catalog

Each dispatcher returns ``(success: bool, result: dict)``. The
success flag flips the queue entry to EXECUTED on True,
FAILED on False; the result dict lands in
``ApprovalAction.result``. Per-dispatcher failures (router
unavailable / adapter rejection / bad params) surface as
``success=False`` with a structured ``result``.

Dispatcher imports are LAZY so this module loads cheaply: the
executor's first call triggers a single import here, and each
dispatcher pulls only what it needs from its engine package.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from core.approval.executor import register_dispatcher

logger = get_logger("core.approval.dispatchers")


# ── Shared helpers ──────────────────────────────────────────────


def _router_call(capability_name: str, friendly_params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Resolve the router + capability and run a single execute.

    Returns ``(success, result_dict)`` so the dispatcher contract
    is uniform — the result dict on failure carries an ``error``
    key, on success carries the adapter response data flattened.
    """
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"router_import_failed: {exc}"}

    capability = getattr(Capability, capability_name, None)
    if capability is None:
        return False, {"error": f"unknown_capability: {capability_name}"}

    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"router_init_failed: {exc}"}

    if router is None:
        return False, {"error": "router_unavailable"}

    try:
        result = router.execute(capability, friendly_params)
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"adapter_raised: {exc}"}

    if not getattr(result, "ok", False):
        return False, {
            "error": f"adapter_failed: {getattr(result, 'error', 'unknown')}",
        }

    data = getattr(result, "data", {}) or {}
    return True, dict(data) if isinstance(data, dict) else {"data": data}


# ── tag_management → SHOPIFY_UPDATE_PRODUCT.tags ────────────────


@register_dispatcher("apply_tags")
def _apply_tags_dispatch(params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Replay tag_management's merged-tag write.

    ``enqueue_tags_for_approval`` parks ``{product_id, merged_tags,
    tags_added, new_tags}`` — the merged list is already
    ready to send.
    """
    pid = str(params.get("product_id", "")).strip()
    merged = params.get("merged_tags") or []
    if not pid or not isinstance(merged, list) or not merged:
        return False, {"error": "missing_product_id_or_tags"}
    return _router_call("SHOPIFY_UPDATE_PRODUCT", {"id": pid, "tags": merged})


# ── catalog → SHOPIFY_ADD_TAGS ──────────────────────────────────


@register_dispatcher("catalog_apply_tags")
def _catalog_apply_tags_dispatch(params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Replay catalog's tag-merge write.

    Catalog uses ``SHOPIFY_ADD_TAGS`` (merge-side) rather than
    ``SHOPIFY_UPDATE_PRODUCT`` (replace-side), so existing tags
    on the product are preserved automatically.
    """
    pid = str(params.get("product_id", "")).strip()
    tags = params.get("tags") or []
    if not pid or not isinstance(tags, list) or not tags:
        return False, {"error": "missing_product_id_or_tags"}
    return _router_call("SHOPIFY_ADD_TAGS", {"id": pid, "tags": tags})


# ── search_optimization → SHOPIFY_UPDATE_PRODUCT.seo ────────────


@register_dispatcher("apply_seo_meta")
def _apply_seo_meta_dispatch(params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Replay search_optimization's SEO-field update.

    Only the fields that actually changed at enqueue time are
    populated in ``params`` (``proposed_title`` is ``None`` when
    only the description differed, and vice versa).
    """
    pid = str(params.get("product_id", "")).strip()
    if not pid:
        return False, {"error": "missing_product_id"}

    payload: dict[str, Any] = {"id": pid}
    title = params.get("proposed_title")
    desc = params.get("proposed_description")
    if isinstance(title, str) and title.strip():
        payload["seo_title"] = title.strip()
    if isinstance(desc, str) and desc.strip():
        payload["seo_description"] = desc.strip()
    if "seo_title" not in payload and "seo_description" not in payload:
        return False, {"error": "no_seo_fields_to_write"}

    return _router_call("SHOPIFY_UPDATE_PRODUCT", payload)


# ── product_lifecycle → SHOPIFY_UPDATE_PRODUCT.status=ARCHIVED ──


@register_dispatcher("archive_declining_product")
def _archive_dispatch(params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Replay product_lifecycle's archive write.

    ``status`` defaults to ``ARCHIVED`` since that's the only
    archival outcome the engine ever enqueues, but the parked
    value is honored if the engine ever extends with ``DRAFT`` /
    ``DELETED`` later.
    """
    pid = str(params.get("product_id", "")).strip()
    if not pid:
        return False, {"error": "missing_product_id"}
    status = str(params.get("status", "ARCHIVED")).strip() or "ARCHIVED"
    return _router_call(
        "SHOPIFY_UPDATE_PRODUCT", {"id": pid, "status": status},
    )


# ── dynamic_pricing → SHOPIFY_UPDATE_VARIANTS ──────────────────


@register_dispatcher("apply_price_change")
def _apply_price_change_dispatch(params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Replay dynamic_pricing's variant-price write.

    Rebuilds the per-variant payload the productVariantsBulkUpdate
    mutation expects — a list of ``{id, price}`` entries with the
    money string rounded to 2 decimals.
    """
    pid = str(params.get("product_id", "")).strip()
    new_price_raw = params.get("new_price")
    variant_ids = params.get("variant_ids") or []
    if not pid or new_price_raw is None or not isinstance(variant_ids, list) or not variant_ids:
        return False, {"error": "missing_product_id_or_price_or_variants"}
    try:
        new_price = float(new_price_raw)
    except (TypeError, ValueError):
        return False, {"error": "invalid_new_price"}
    price_str = f"{new_price:.2f}"
    variants = [{"id": vid, "price": price_str} for vid in variant_ids]
    return _router_call(
        "SHOPIFY_UPDATE_VARIANTS",
        {"product_id": pid, "variants": variants},
    )


# ── affiliate → SHOPIFY_CREATE_GIFT_CARD ────────────────────────


@register_dispatcher("pay_commission")
def _pay_commission_dispatch(params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Replay affiliate's gift-card payout.

    ``enqueue_commissions_for_approval`` already builds the
    full friendly-form gift-card payload (``initial_value``,
    ``currency``, ``note``, optional ``recipient_email`` /
    ``recipient_name`` / ``customer_id``) so this dispatcher is
    a direct forward.
    """
    if not isinstance(params.get("initial_value"), (int, float)):
        return False, {"error": "missing_or_invalid_initial_value"}
    return _router_call("SHOPIFY_CREATE_GIFT_CARD", dict(params))


# ── content_generation → SHOPIFY_UPDATE_PRODUCT.descriptionHtml ─


@register_dispatcher("apply_description")
def _apply_description_dispatch(params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Replay content_generation's description rewrite.

    The enqueue path stores ``body_preview`` (capped at 200
    chars) and ``body_length`` for the merchant approval page
    summary — but NOT the full body. Replaying with only the
    preview would write a truncated description, which is worse
    than refusing to execute. Surface a clear error so the
    engine output explains the limitation; a follow-up will
    extend the enqueue payload to carry the full body when the
    merchant opts into approval-gated description rewrites.
    """
    body_preview = str(params.get("body_preview", "")).strip()
    body_length = int(params.get("body_length", 0) or 0)
    if not body_preview:
        return False, {"error": "missing_body"}
    if body_length > len(body_preview):
        return False, {
            "error": (
                "body_truncated_in_queue: enqueue stored a "
                f"{len(body_preview)}-char preview but the original "
                f"body was {body_length} chars; replaying would "
                "truncate the description. Re-run the engine and "
                "approve the fresh recommendation, or upgrade the "
                "enqueue path to carry the full body."
            ),
        }
    pid = str(params.get("product_id", "")).strip()
    if not pid:
        return False, {"error": "missing_product_id"}
    return _router_call(
        "SHOPIFY_UPDATE_PRODUCT",
        {"id": pid, "description_html": body_preview},
    )


# ── loyalty → shared mint helper (per-customer code) ────────────


@register_dispatcher("mint_loyalty_code")
def _mint_loyalty_dispatch(params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Replay loyalty's per-customer discount-code mint.

    The original ``mint_loyalty_code`` derives the ``token`` from
    the customer GID and the ``title`` from the percentage; this
    dispatcher reuses those private helpers to keep the wire
    format identical to the direct-mint path.
    """
    customer_id = str(params.get("customer_id", "")).strip()
    percentage_raw = params.get("percentage")
    ttl_days_raw = params.get("ttl_days")
    if not customer_id or percentage_raw is None:
        return False, {"error": "missing_customer_id_or_percentage"}
    try:
        percentage = float(percentage_raw)
        ttl_days = int(ttl_days_raw) if ttl_days_raw is not None else 30
    except (TypeError, ValueError):
        return False, {"error": "invalid_percentage_or_ttl"}

    try:
        from engines._recovery_codes import mint_recovery_code
        from engines.loyalty.discount_minter import _build_token
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"loyalty_helpers_import_failed: {exc}"}

    token = _build_token(customer_id)
    title = f"Loyalty reward: {percentage:g}% off"

    try:
        minted = mint_recovery_code(
            token=token,
            code_prefix="LOYALTY",
            value=percentage,
            value_kind="percentage",
            ttl_days=ttl_days,
            title=title,
        )
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"mint_raised: {exc}"}

    if minted is None:
        return False, {"error": "mint_returned_none"}
    return True, dict(minted)


# ── discount_strategy → shared mint helper (storewide promo) ────


@register_dispatcher("mint_strategy_code")
def _mint_strategy_dispatch(params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Replay discount_strategy's storewide promo mint.

    Storewide promos are multi-use (``usage_limit=None``) and
    customer-reusable (``applies_once_per_customer=False``) —
    different from the per-customer loyalty code, hence a
    separate dispatcher rather than a shared helper.
    """
    audience = str(params.get("audience", "all")).strip() or "all"
    percentage_raw = params.get("percentage")
    ttl_days_raw = params.get("ttl_days")
    if percentage_raw is None:
        return False, {"error": "missing_percentage"}
    try:
        percentage = float(percentage_raw)
        ttl_days = int(ttl_days_raw) if ttl_days_raw is not None else 7
    except (TypeError, ValueError):
        return False, {"error": "invalid_percentage_or_ttl"}

    try:
        from engines._recovery_codes import mint_recovery_code
        from engines.discount_strategy.discount_minter import _build_token
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"strategy_helpers_import_failed: {exc}"}

    token = _build_token(audience)
    title = f"Storewide promo: {percentage:g}% off ({audience})"

    try:
        minted = mint_recovery_code(
            token=token,
            code_prefix="PROMO",
            value=percentage,
            value_kind="percentage",
            ttl_days=ttl_days,
            title=title,
            usage_limit=None,
            applies_once_per_customer=False,
        )
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"mint_raised: {exc}"}

    if minted is None:
        return False, {"error": "mint_returned_none"}
    return True, dict(minted)
