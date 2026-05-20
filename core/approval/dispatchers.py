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


# ── fraud_detection → SHOPIFY_TAG_ORDER ─────────────────────────


@register_dispatcher("apply_fraud_tag")
def _apply_fraud_tag_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay fraud_detection's order-tag write.

    The applier parks ``{order_id, tags, verdict, risk_score,
    confidence}``. Only ``order_id`` + ``tags`` flow to the
    SHOPIFY_TAG_ORDER call; the rest is context for operator
    review at trace time.
    """
    order_id = str(params.get("order_id", "")).strip()
    tags = params.get("tags") or []
    if (
        not order_id
        or not isinstance(tags, list)
        or not tags
    ):
        return False, {"error": "missing_order_id_or_tags"}
    return _router_call(
        "SHOPIFY_TAG_ORDER", {"id": order_id, "tags": tags},
    )


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

    Reads the full body from ``params["body"]`` (added by
    ``enqueue_description_for_approval``). Falls back to
    ``body_preview`` for backwards compatibility with rows
    queued before that change — but only when the preview
    actually carries the entire original body
    (``body_length <= len(body_preview)``). When the legacy
    preview is shorter than the original body, the dispatcher
    refuses replay rather than write a truncated description;
    operators must re-enqueue with the upgraded payload shape.
    """
    pid = str(params.get("product_id", "")).strip()
    if not pid:
        return False, {"error": "missing_product_id"}

    body = str(params.get("body", "")).strip()
    if body:
        return _router_call(
            "SHOPIFY_UPDATE_PRODUCT",
            {"id": pid, "description_html": body},
        )

    # Backwards-compat: pre-follow-up rows only stored a
    # 200-char ``body_preview``. Safe to replay only when the
    # preview equals the original body (the original was short
    # enough to fit under the cap).
    body_preview = str(params.get("body_preview", "")).strip()
    body_length = int(params.get("body_length", 0) or 0)
    if not body_preview:
        return False, {"error": "missing_body"}
    if body_length > len(body_preview):
        return False, {
            "error": (
                "body_truncated_in_queue: legacy row carries only "
                f"a {len(body_preview)}-char preview but the original "
                f"body was {body_length} chars; replaying would "
                "truncate. Re-enqueue with the post-follow-up "
                "payload (full ``body`` field) and approve the fresh "
                "recommendation."
            ),
        }
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


# ── Generic per-customer/per-segment mint dispatcher ────────────
#
# cart_recovery, browse_recovery, email_marketing, wholesale_b2b
# all enqueue with the same shape: token + value + value_kind +
# ttl_days + code_prefix. Engine-specific extras (customer_id,
# order_total, likelihood) are passed through unchanged — the
# mint helper only cares about the five core fields. Each engine
# has its own registration so audit coverage (Pattern K) sees an
# explicit per-engine pairing rather than a catch-all that hides
# per-engine wireup.


def _generic_mint_dispatch(
    params: dict[str, Any],
    *,
    default_ttl_days: int,
) -> tuple[bool, dict[str, Any]]:
    """Shared body for engines that enqueue the standard mint shape."""
    token = str(params.get("token", "")).strip()
    value = params.get("value")
    value_kind = str(params.get("value_kind", "")).strip()
    code_prefix = str(params.get("code_prefix", "")).strip()
    if not token or value is None or value_kind not in {
        "percentage", "amount",
    } or not code_prefix:
        return False, {
            "error": "missing_or_invalid_mint_params",
            "needed": (
                "token, value, value_kind (percentage|amount), "
                "code_prefix"
            ),
        }

    ttl_raw = params.get("ttl_days")
    try:
        ttl_days = (
            int(ttl_raw) if ttl_raw is not None else default_ttl_days
        )
    except (TypeError, ValueError):
        return False, {"error": "invalid_ttl_days"}

    try:
        from engines._recovery_codes import mint_recovery_code
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"mint_helper_import_failed: {exc}"}

    try:
        minted = mint_recovery_code(
            token=token,
            code_prefix=code_prefix,
            value=value,
            value_kind=value_kind,
            ttl_days=ttl_days,
        )
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"mint_raised: {exc}"}

    if minted is None:
        return False, {"error": "mint_returned_none"}
    return True, dict(minted)


@register_dispatcher("mint_cart_recovery_code")
def _mint_cart_recovery_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay cart_recovery's per-customer recovery-code mint."""
    return _generic_mint_dispatch(params, default_ttl_days=7)


@register_dispatcher("mint_browse_recovery_code")
def _mint_browse_recovery_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay browse_recovery's per-user browse-recovery code."""
    return _generic_mint_dispatch(params, default_ttl_days=7)


@register_dispatcher("mint_campaign_code")
def _mint_campaign_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay email_marketing's per-campaign code mint."""
    return _generic_mint_dispatch(params, default_ttl_days=14)


@register_dispatcher("mint_wholesale_code")
def _mint_wholesale_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay wholesale_b2b's per-account volume-discount mint."""
    return _generic_mint_dispatch(params, default_ttl_days=30)


# ── selection_decision → SHOPIFY_ADD_TAGS ───────────────────────


@register_dispatcher("tag_selection_selected")
def _tag_selection_selected_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay selection_decision's per-product selected tag.

    Enqueue carries ``{product_id, tag, verdict, confidence,
    title}``. The adapter side wants ``{id, tags: [tag]}`` —
    same shape as catalog_apply_tags (verdict / confidence /
    title are kept in approval-side params for operator
    context but aren't part of the mutation).
    SHOPIFY_ADD_TAGS is additive — existing tags preserved.
    """
    product_id = str(params.get("product_id", "")).strip()
    tag = str(params.get("tag", "")).strip()
    if not product_id or not tag:
        return False, {"error": "missing_product_id_or_tag"}
    return _router_call(
        "SHOPIFY_ADD_TAGS",
        {"id": product_id, "tags": [tag]},
    )


# ── customer_segmentation → SHOPIFY_TAG_CUSTOMER ────────────────


@register_dispatcher("apply_segment_tag")
def _apply_segment_tag_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay customer_segmentation's per-customer tag write.

    Enqueue carries ``{customer_id, tag, segment}``. The adapter
    side wants ``{id, tags: [tag]}`` — same translation the live
    applier does (segment is kept in approval-side params for
    operator context but isn't part of the Shopify mutation).
    """
    customer_id = str(params.get("customer_id", "")).strip()
    tag = str(params.get("tag", "")).strip()
    if not customer_id or not tag:
        return False, {"error": "missing_customer_id_or_tag"}
    return _router_call(
        "SHOPIFY_TAG_CUSTOMER",
        {"id": customer_id, "tags": [tag]},
    )


# ── landing_page → SHOPIFY_CREATE_PAGE ──────────────────────────


@register_dispatcher("apply_landing_page")
def _apply_landing_page_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay landing_page's variant-page creation.

    The applier pre-builds the wire format under
    ``adapter_params`` (title/handle/body_html/template_suffix
    etc.) at enqueue time, so the dispatcher just forwards it
    verbatim — the wire-format authoring lives in the engine,
    where the proposal's full context (best_variant, copy
    template) is still available.
    """
    adapter_params = params.get("adapter_params")
    if not isinstance(adapter_params, dict) or not adapter_params:
        return False, {"error": "missing_adapter_params"}
    return _router_call("SHOPIFY_CREATE_PAGE", adapter_params)


# ── inventory → SHOPIFY_UPDATE_PRODUCT.tags (merged) ────────────


@register_dispatcher("apply_inventory_tags")
def _apply_inventory_tags_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay inventory's state-tag write.

    Enqueue carries ``{product_id, merged_tags, state_tags,
    tags_added}``; only ``id`` + ``tags`` reach Shopify. The
    ``merged_tags`` list is already deduped on the engine side
    (existing + new state tags) so it's the verbatim payload —
    no re-merge at dispatch time.
    """
    pid = str(params.get("product_id", "")).strip()
    merged = params.get("merged_tags") or []
    if not pid or not isinstance(merged, list) or not merged:
        return False, {"error": "missing_product_id_or_tags"}
    return _router_call(
        "SHOPIFY_UPDATE_PRODUCT", {"id": pid, "tags": merged},
    )


# ── legal_document → SHOPIFY_CREATE_PAGE (pre-built params) ─────


@register_dispatcher("apply_legal_document")
def _apply_legal_document_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay legal_document's policy-page creation.

    Same shape as ``apply_landing_page`` — the engine pre-builds
    the full wire format under ``adapter_params`` (title/handle/
    body_html with the policy text). Dispatcher forwards verbatim.
    Operator-context fields (``type``, ``title``, ``handle``) are
    duplicated outside ``adapter_params`` for the queue display
    but are NOT re-sent in the mutation.
    """
    adapter_params = params.get("adapter_params")
    if not isinstance(adapter_params, dict) or not adapter_params:
        return False, {"error": "missing_adapter_params"}
    return _router_call("SHOPIFY_CREATE_PAGE", adapter_params)


# ── shipping_optimization → CREATE_AUTOMATIC_FREE_SHIPPING ──────


@register_dispatcher("apply_shipping_strategy")
def _apply_shipping_strategy_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay shipping_optimization's free-shipping discount.

    The engine assembles a Shopify automatic-discount payload
    (title + starts_at + ends_at + minimum_subtotal) under
    ``adapter_params`` at proposal time. Dispatcher forwards
    verbatim — date math + threshold derivation belong to the
    engine, not replay.
    """
    adapter_params = params.get("adapter_params")
    if not isinstance(adapter_params, dict) or not adapter_params:
        return False, {"error": "missing_adapter_params"}
    return _router_call(
        "SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING", adapter_params,
    )


# ── pricing → SHOPIFY_UPDATE_VARIANTS (per-variant price) ───────


@register_dispatcher("apply_strategic_price")
def _apply_strategic_price_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay pricing's per-product variant-price update.

    Enqueue carries ``{product_id, new_price, variant_ids, ...}``;
    Shopify's bulk variant mutation wants
    ``{product_id, variants: [{id, price}, ...]}``. Dispatcher
    re-assembles that payload from the listed variant ids + the
    new price (formatted to 2 decimal places, matching the live
    applier's format).
    """
    pid = str(params.get("product_id", "")).strip()
    new_price_raw = params.get("new_price")
    variant_ids = params.get("variant_ids") or []
    if not pid or not isinstance(variant_ids, list) or not variant_ids:
        return False, {"error": "missing_product_id_or_variants"}
    try:
        new_price = float(new_price_raw)
    except (TypeError, ValueError):
        return False, {"error": "invalid_new_price"}
    if new_price <= 0:
        return False, {"error": "non_positive_price"}

    price_str = f"{new_price:.2f}"
    variants_payload = [
        {"id": str(vid), "price": price_str}
        for vid in variant_ids if vid
    ]
    if not variants_payload:
        return False, {"error": "no_valid_variant_ids"}

    return _router_call(
        "SHOPIFY_UPDATE_VARIANTS",
        {"product_id": pid, "variants": variants_payload},
    )


# ── returns_management → SHOPIFY_TAG_ORDER ──────────────────────


@register_dispatcher("tag_return_decision")
def _tag_return_decision_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay returns_management's order-tagging decision write.

    Enqueue carries ``{return_id, order_id, tags, refund_amount,
    decision_status, rejection_reason}``; only the order id +
    tags reach Shopify. The other fields are decision-context
    that operators inspect on the approval queue.
    """
    order_id = str(params.get("order_id", "")).strip()
    tags = params.get("tags") or []
    if not order_id or not isinstance(tags, list) or not tags:
        return False, {"error": "missing_order_id_or_tags"}
    return _router_call(
        "SHOPIFY_TAG_ORDER", {"id": order_id, "tags": tags},
    )


# ── bundle → SHOPIFY_CREATE_PRODUCT (pre-built component variants)


@register_dispatcher("apply_bundle_product")
def _apply_bundle_product_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Replay bundle's new-product creation.

    The bundle engine pre-builds the full Shopify product payload
    (title + component variants + bundle pricing) under
    ``adapter_params`` at proposal time. The component graph,
    variant assembly, and savings math all live in the engine's
    proposal step — dispatcher forwards the assembled payload
    verbatim. Operator-context fields (``components``,
    ``bundle_price``, ``savings_pct``, ``estimated_uplift``)
    stay queue-side for review and are NOT re-sent.
    """
    adapter_params = params.get("adapter_params")
    if not isinstance(adapter_params, dict) or not adapter_params:
        return False, {"error": "missing_adapter_params"}
    return _router_call("SHOPIFY_CREATE_PRODUCT", adapter_params)
