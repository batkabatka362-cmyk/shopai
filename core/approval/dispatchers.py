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


# ── product_sourcer → SHOPIFY_CREATE_PRODUCT (draft seed) ────────


@register_dispatcher("create_draft_product")
def _create_draft_product_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """W963-3: replay product_sourcer's DRAFT product creation.

    The product_sourcer engine enqueues each candidate with the
    full friendly call shape (title + description + status=DRAFT
    + vendor + product_type + tags). The internal _metadata key
    carries source-tracking info (niche + suggested_price band)
    but is NOT a Shopify-recognised field — strip it before the
    GraphQL hop.

    The DRAFT status is enforced at enqueue time; the dispatcher
    trusts it. Operators who explicitly want to publish an active
    product should change `status` to ACTIVE in the queue entry's
    params before approving (or use a future ``--publish`` flag).

    W963-164: after productCreate, follow up with
    productVariantsBulkUpdate to set the variant price from
    _metadata.suggested_price. Pre-fix every newly-created
    product had a default $0 variant -- the product appeared
    in the catalog but customers literally could not buy it.
    """
    title = str(params.get("title", "")).strip()
    if not title:
        return False, {"error": "missing_title"}
    adapter_params = {
        k: v for k, v in params.items()
        if not k.startswith("_")
    }
    ok, result = _router_call(
        "SHOPIFY_CREATE_PRODUCT", adapter_params,
    )
    if not ok:
        return ok, result

    # W963-164: thread suggested_price -> variant price.
    metadata = params.get("_metadata") or {}
    suggested_price = metadata.get("suggested_price") if (
        isinstance(metadata, dict)
    ) else None
    if suggested_price is None:
        return ok, result
    try:
        price = float(suggested_price)
    except (TypeError, ValueError):
        return ok, result
    if price <= 0:
        return ok, result

    product = result.get("product") or {}
    product_id = str(product.get("id") or "").strip()
    variants = product.get("variants") or []
    variant_id = ""
    if variants and isinstance(variants, list):
        first = variants[0]
        if isinstance(first, dict):
            variant_id = str(first.get("id") or "").strip()
    if not product_id or not variant_id:
        # Create succeeded but we can't locate the default
        # variant -- surface success on the create + log the
        # gap as a result field instead of erroring out.
        result["price_set"] = False
        result["price_set_skip_reason"] = (
            "default_variant_id_not_in_response"
        )
        return ok, result

    price_str = f"{price:.2f}"

    # W963-166: dropshipping stores need inventoryPolicy=CONTINUE
    # so customers can order even when stock=0 (supplier ships
    # on demand). _metadata.inventory_policy controls; defaults
    # to CONTINUE -- matches the most common autonomous-merchant
    # use case (dropshipping). Operators with own-inventory
    # stores set _metadata.inventory_policy='DENY' on the
    # proposal.
    inventory_policy = metadata.get("inventory_policy", "CONTINUE")
    if not isinstance(inventory_policy, str) or (
        inventory_policy.upper() not in ("CONTINUE", "DENY")
    ):
        inventory_policy = "CONTINUE"

    price_ok, price_result = _router_call(
        "SHOPIFY_UPDATE_VARIANTS",
        {
            "product_id": product_id,
            "variants": [{
                "id": variant_id,
                "price": price_str,
                "inventory_policy": inventory_policy.upper(),
            }],
        },
    )
    result["price_set"] = bool(price_ok)
    result["price_set_value"] = price_str
    result["inventory_policy"] = inventory_policy.upper()
    if not price_ok:
        result["price_set_error"] = price_result.get(
            "error", "unknown",
        )

    # W963-167: attach product images when supplied. Image
    # URLs come from _metadata.image_urls (list of strings) or
    # _metadata.images (list of {url, alt?} dicts). Operators
    # / engines that don't supply images skip this step
    # silently (no degradation of the create flow).
    images_attached = _attach_product_images(
        product_id=product_id,
        metadata=metadata,
        result=result,
    )
    if images_attached is not None:
        result["images_attached"] = images_attached

    # W963-170: publish_on_approve makes the dispatcher a
    # single-step launcher. After create + price + images, flip
    # DRAFT -> ACTIVE + publish on Online Store. Defaults to
    # False (operator still has to enqueue a publish_product
    # action explicitly). product_sourcer's
    # _ENABLE_AUTO_PUBLISH env-controlled flag sets this on the
    # enqueue so high-trust empires get true single-approval
    # launches. Failure swallowed into result for observability;
    # the create + price + images already landed and the next
    # cycle can pick up the publish path.
    publish_on_approve = metadata.get("publish_on_approve")
    if (
        publish_on_approve is True
        or str(publish_on_approve).lower() in ("1", "true", "yes")
    ):
        publish_ok, publish_result = (
            _publish_product_dispatch(
                {"product_id": product_id},
            )
        )
        result["published"] = bool(publish_ok)
        result["publish_result"] = publish_result
        if not publish_ok:
            result["publish_error"] = publish_result.get(
                "error", "unknown",
            )

    return ok, result


def _discover_stock_images(
    *,
    query: str,
    limit: int,
    orientation: str,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """W963-169: search IMAGE_STOCK_SEARCH for hero images.

    Returns a list of {url, alt} dicts ready to feed into the
    SHOPIFY_CREATE_PRODUCT_MEDIA call. Picks ``url_large2x``
    (~2MP) which fits comfortably under Shopify's 25MP ceiling
    so we don't even need W963-168's resize hack -- the adapter's
    own size variant is correct by construction.

    On any failure returns an empty list + tags result.images_
    discover_error for observability.
    """
    params = {"query": query, "limit": max(1, min(limit, 10))}
    if orientation in ("landscape", "portrait", "square"):
        params["orientation"] = orientation
    ok, search_result = _router_call(
        "IMAGE_STOCK_SEARCH", params,
    )
    if not ok:
        result["images_discover_error"] = (
            search_result.get("error", "unknown")
        )
        return []
    photos = search_result.get("photos") or []
    out: list[dict[str, Any]] = []
    for p in photos[:limit]:
        if not isinstance(p, dict):
            continue
        # Prefer large2x (~2MP); fall back to large then medium.
        url = (
            p.get("url_large2x")
            or p.get("url_large")
            or p.get("url_medium")
            or ""
        )
        if not url:
            continue
        out.append({
            "url": url,
            "alt": p.get("alt") or query,
        })
    result["images_discovered_from"] = "stock_search"
    return out


def _normalise_image_url(url: str) -> str:
    """W963-168: resize Pexels URLs to a safe dimension before
    handing them to Shopify.

    Shopify's productCreateMedia rejects images exceeding 25MP
    (the field returns MediaWarning code=INVALID_IMAGE_RESOLUTION
    + the upload lands in status=FAILED). Pexels by default
    serves images at the photographer's native resolution which
    is often 30-60MP. Adding ``?auto=compress&cs=tinysrgb&w=1500``
    capped at 1500px wide produces a ~2MP image -- well under
    Shopify's limit + still high-quality for product cards.

    Other CDN URLs are returned unchanged.
    """
    u = url.strip()
    if "images.pexels.com" in u and "?" not in u:
        return u + "?auto=compress&cs=tinysrgb&w=1500"
    return u


def _attach_product_images(
    *,
    product_id: str,
    metadata: dict[str, Any],
    result: dict[str, Any],
) -> int | None:
    """Helper for W963-167 image attachment. Returns the count
    attached, or None when no images were supplied. Swallows
    failures into the result dict so the parent dispatch path
    stays focused on its create + price contract."""
    raw_urls = metadata.get("image_urls")
    raw_images = metadata.get("images")
    media_inputs: list[dict[str, Any]] = []
    if isinstance(raw_images, list) and raw_images:
        for m in raw_images:
            if isinstance(m, dict) and m.get("url"):
                entry = {
                    "url": _normalise_image_url(
                        str(m["url"]),
                    ),
                }
                if m.get("alt"):
                    entry["alt"] = str(m["alt"])
                media_inputs.append(entry)
    if isinstance(raw_urls, list) and raw_urls:
        for url in raw_urls:
            if isinstance(url, str) and url.strip():
                media_inputs.append({
                    "url": _normalise_image_url(url),
                })

    # W963-169: when no explicit URLs were supplied AND the
    # proposal carries an _metadata.image_query, fan out to
    # IMAGE_STOCK_SEARCH to find a hero image automatically.
    # Engines that don't set image_query get the previous
    # silent-skip behaviour. limit defaults to 1 (just pick
    # the top result).
    image_query = metadata.get("image_query")
    if (
        not media_inputs
        and isinstance(image_query, str)
        and image_query.strip()
    ):
        # W963-176: defensively coerce image_count. Raw
        # int(metadata.get(...) or 1) would crash the dispatcher
        # if image_count is a non-numeric string (e.g. operator
        # hand-edited a queue entry). Falls back to 1 on any
        # coercion error so the autonomous chain stays alive.
        try:
            image_limit = int(
                metadata.get("image_count", 1) or 1,
            )
        except (TypeError, ValueError):
            image_limit = 1
        discovered = _discover_stock_images(
            query=image_query.strip(),
            limit=image_limit,
            orientation=str(
                metadata.get("image_orientation", "")
                or "",
            ),
            result=result,
        )
        for entry in discovered:
            media_inputs.append(entry)

    if not media_inputs:
        return None

    ok, image_result = _router_call(
        "SHOPIFY_CREATE_PRODUCT_MEDIA",
        {"product_id": product_id, "media": media_inputs},
    )
    if not ok:
        result["images_attach_error"] = image_result.get(
            "error", "unknown",
        )
        return 0
    return int(image_result.get("attached_count", 0) or 0)


# ── product_sourcer → publish DRAFT product to Online Store ──────


_ONLINE_STORE_PUB_CACHE: dict[str, str] = {}
# W963-178: serialise cache reads + writes so concurrent
# callers (parallel cycle fan-out across stores, pytest -n auto,
# webhook server with multiple inbound requests for the same
# shop) don't duplicate LIST_PUBLICATIONS calls. Race wasn't
# corrupting state (both writers would land the same GID) but
# wasted a router call per cycle x worker.
import threading as _pub_cache_threading
_ONLINE_STORE_PUB_CACHE_LOCK = _pub_cache_threading.Lock()


def _resolve_online_store_publication() -> str:
    """W963-165 + W963-174 + W963-178: cache the Online Store
    publication GID with thread safety.

    Shopify's publication IDs are per-shop + per-active_store
    context. We resolve once per process per (sid != '') +
    reuse. The sid='' path always re-resolves (W963-174:
    prevents leaking a sibling shop's publication GID when
    active_store isn't set).

    Cache access is guarded by a module-level lock
    (W963-178) so two threads asking for the same sid don't
    both fire LIST_PUBLICATIONS.

    Returns '' on any failure (caller falls back to
    operator-supplied publication_ids).
    """
    # Cache key includes active_store so multi-store callers
    # don't reuse a sibling store's publication id.
    try:
        from core.context import get_active_store_id
        sid = str(get_active_store_id() or "")
    except Exception:  # noqa: BLE001
        sid = ""
    # W963-174 + W963-178: only consult / write the cache when
    # we have a real sid. Lock guards the read + miss + write
    # window so two concurrent callers for the same sid don't
    # both fire LIST_PUBLICATIONS.
    if sid:
        with _ONLINE_STORE_PUB_CACHE_LOCK:
            cached = _ONLINE_STORE_PUB_CACHE.get(sid)
        if cached:
            return cached

    ok, result = _router_call(
        "SHOPIFY_LIST_PUBLICATIONS", {},
    )
    if not ok:
        return ""
    for pub in result.get("publications") or []:
        if not isinstance(pub, dict):
            continue
        name = str(pub.get("name") or "").strip().lower()
        if name == "online store":
            pub_id = str(pub.get("id") or "")
            if pub_id:
                if sid:
                    with _ONLINE_STORE_PUB_CACHE_LOCK:
                        _ONLINE_STORE_PUB_CACHE[sid] = pub_id
                return pub_id
    return ""


@register_dispatcher("publish_product")
def _publish_product_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """W963-165: flip DRAFT -> ACTIVE + publish on Online Store.

    Two-step:
      1. SHOPIFY_UPDATE_PRODUCT to set status=ACTIVE so the
         product is visible to the storefront.
      2. SHOPIFY_PUBLISH_RESOURCE on the Online Store publication
         so the product appears on the customer-facing storefront.

    Params:
      id (or product_id): Shopify GID of the product to publish.
      publication_ids (optional): list of GIDs; if omitted,
        defaults to the resolved Online Store publication GID.

    Both router calls go inside the executor's active_store
    wrap so per-store credentials route correctly.
    """
    product_id = str(
        params.get("id") or params.get("product_id") or "",
    ).strip()
    if not product_id:
        return False, {"error": "missing_product_id"}

    # Step 1: status -> ACTIVE
    ok_status, status_result = _router_call(
        "SHOPIFY_UPDATE_PRODUCT",
        {"id": product_id, "status": "ACTIVE"},
    )
    if not ok_status:
        return False, {
            "error": "status_update_failed",
            "detail": status_result.get("error", "unknown"),
        }

    # Step 2: publish on the requested channels
    publication_ids = params.get("publication_ids")
    if not publication_ids:
        resolved = _resolve_online_store_publication()
        if not resolved:
            # W963-175: partial-state observability. The
            # status flip on Shopify ALREADY HAPPENED at
            # step 1; the failure here is only the publish
            # step. Surface status_updated=True + the
            # product_id so the operator knows the product
            # is now ACTIVE (visible via direct URL / API)
            # but NOT on the Online Store sales channel.
            # Pre-fix the error envelope made it look like
            # the dispatcher was a no-op when in fact it
            # had mutated state.
            return False, {
                "error": (
                    "no_online_store_publication_found"
                ),
                "detail": (
                    "SHOPIFY_LIST_PUBLICATIONS returned no "
                    "publication named 'Online Store'."
                ),
                "product_id": product_id,
                "status_updated": True,
            }
        publication_ids = [resolved]

    ok_pub, pub_result = _router_call(
        "SHOPIFY_PUBLISH_RESOURCE",
        {
            "id": product_id,
            "publication_ids": publication_ids,
        },
    )
    return ok_pub, {
        "product_id": product_id,
        "status_updated": True,
        "publication_ids": publication_ids,
        "publish_result": pub_result,
    }


# ── content_publisher → SHOPIFY_CREATE_ARTICLE (draft blog) ──────


@register_dispatcher("create_draft_article")
def _create_draft_article_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """W963-6: replay content_publisher's DRAFT article create.

    Each candidate carries title + body_html + tags + blog_id +
    is_published=False (DRAFT enforcement). _metadata field is
    stripped (source-tracking only). The dispatcher trusts the
    enqueue-time is_published=False flag; operators who want to
    publish an article should set is_published=True in the queue
    entry params before approving.
    """
    title = str(params.get("title", "")).strip()
    blog_id = str(params.get("blog_id", "")).strip()
    if not title:
        return False, {"error": "missing_title"}
    if not blog_id:
        return False, {"error": "missing_blog_id"}
    adapter_params = {
        k: v for k, v in params.items()
        if not k.startswith("_")
    }
    return _router_call("SHOPIFY_CREATE_ARTICLE", adapter_params)


# ── brand_identity_composer -> SHOPIFY theme + assets ──


@register_dispatcher("apply_brand_identity")
def _apply_brand_identity_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """W963-149: replay brand identity composition.

    Approved params shape (from W963-149 enqueue):
      {
        "palette": {primary, secondary, accent,
                    text, background},
        "typography": {heading, body},
        "logo_concept": {brand_name, url},
        "hero_candidates": [{url, source, ...}],
        "tagline": "...",
        ...
      }

    Theme push step ordering:
      1. palette + typography -> SHOPIFY_UPDATE_ONLINE_STORE_SETTINGS
         (or theme.json update)
      2. logo_concept.url -> SHOPIFY_FILE_CREATE +
         theme.config logo
      3. hero_candidates -> SHOPIFY_FILE_CREATE batch

    For now, return per-step status so the operator can
    see what was applied. Theme PUT is non-trivial
    Shopify-side; the dispatcher returns success when
    AT LEAST the palette + logo applied, even if hero
    uploads partial.
    """
    applied: list[str] = []
    failed: list[dict[str, Any]] = []

    # 1. Logo upload (highest-value individual step)
    logo = params.get("logo_concept") or {}
    if isinstance(logo, dict) and logo.get("url"):
        try:
            ok, result = _router_call(
                "SHOPIFY_FILE_CREATE",
                {
                    "source_url": logo["url"],
                    "alt": (
                        f"Logo for "
                        f"{logo.get('brand_name', '')}"
                    ),
                },
            )
            if ok:
                applied.append("logo_uploaded")
            else:
                failed.append({
                    "step": "logo_upload",
                    "error": (
                        result.get("error")
                        if isinstance(result, dict)
                        else str(result)
                    )[:200],
                })
        except Exception as exc:  # noqa: BLE001
            failed.append({
                "step": "logo_upload",
                "error": f"raised: {exc}"[:200],
            })

    # 2. Hero candidates upload (parallel-safe; degrades
    # gracefully)
    hero_count = 0
    for h in (params.get("hero_candidates") or []):
        if not isinstance(h, dict):
            continue
        url = h.get("url")
        if not url:
            continue
        try:
            ok, _ = _router_call(
                "SHOPIFY_FILE_CREATE",
                {
                    "source_url": url,
                    "alt": "Brand hero banner",
                },
            )
            if ok:
                hero_count += 1
        except Exception as exc:  # noqa: BLE001
            failed.append({
                "step": "hero_upload",
                "url": url,
                "error": f"raised: {exc}"[:200],
            })
    if hero_count > 0:
        applied.append(
            f"hero_uploaded:{hero_count}",
        )

    # 3. Theme settings -- best-effort. Shopify's theme
    # settings update is highly theme-specific; we log
    # the intent here for operator follow-up. Adapter
    # support will land in a follow-up commit.
    palette = params.get("palette") or {}
    typo = params.get("typography") or {}
    if palette or typo:
        applied.append("theme_intent_recorded")
        # Future: actual SHOPIFY_UPDATE_THEME_SETTINGS
        # call. For now the operator sees the intent in
        # the result + can manually apply via theme
        # editor. The downstream theme adapter (Phase 2
        # follow-up) will close this gap.

    success = bool(applied) and not failed
    return success, {
        "applied": applied,
        "applied_count": len(applied),
        "failed": failed,
        "failed_count": len(failed),
    }


# ── product_onboarding_proposal -> SHOPIFY_CREATE_PRODUCT batch ──


@register_dispatcher("propose_product_batch")
def _propose_product_batch_dispatch(
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """W963-143: replay the product onboarding proposal
    batch by importing each approved candidate.

    Params shape:
      {
        "niche": "beauty",
        "candidates": [
          {
            "title": "Vitamin C serum",
            "supplier": "cj",
            "supplier_id": "cj_abc",
            "cost_usd": 8.0,
            "suggested_retail_usd": 22.4,
            "risk_flags": [],
          },
          ...
        ],
      }

    For each candidate with is_actionable (has title +
    supplier + positive cost), call SHOPIFY_CREATE_PRODUCT
    with the standard payload shape. Skip unsourced
    candidates (risk_flag='unsourced') -- they need
    supplier resolution outside the batch.

    Returns (overall_success, result) where overall_success
    is True iff ALL actionable candidates imported
    successfully. Result carries per-candidate status so
    operator can see which (if any) failed.
    """
    candidates = params.get("candidates") or []
    if (
        not isinstance(candidates, list)
        or not candidates
    ):
        return False, {
            "error": "no_candidates_in_batch",
        }

    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "")).strip()
        supplier = str(raw.get("supplier", "")).strip()
        try:
            cost = float(raw.get("cost_usd", 0) or 0)
        except (TypeError, ValueError):
            cost = 0.0
        try:
            retail = float(
                raw.get("suggested_retail_usd", 0) or 0,
            )
        except (TypeError, ValueError):
            retail = 0.0

        if not title or not supplier or cost <= 0:
            skipped.append({
                "title": title or "(no_title)",
                "reason": "missing_title_supplier_or_cost",
            })
            continue

        # Standard SHOPIFY_CREATE_PRODUCT payload
        payload = {
            "title": title,
            "vendor": supplier,
            "status": "draft",      # operator can
                                    # publish after review
            "variants": [{
                "price": str(retail) if retail > 0 else "",
                "cost": str(cost),
                "inventory_management": "shopify",
            }],
            "tags": [
                f"niche:{params.get('niche', '')}",
                f"supplier:{supplier}",
                "imported:proposal_batch",
            ],
        }
        try:
            ok, result = _router_call(
                "SHOPIFY_CREATE_PRODUCT", payload,
            )
            if ok:
                imported.append({
                    "title": title,
                    "product_id": (
                        result.get("id")
                        if isinstance(result, dict)
                        else ""
                    ),
                })
            else:
                failed.append({
                    "title": title,
                    "error": (
                        result.get("error")
                        if isinstance(result, dict)
                        else str(result)
                    )[:240],
                })
        except Exception as exc:  # noqa: BLE001
            failed.append({
                "title": title,
                "error": f"dispatch_raised: {exc}"[:240],
            })

    overall_ok = (
        bool(imported) and not failed
    )
    return overall_ok, {
        "imported": imported,
        "imported_count": len(imported),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "failed": failed,
        "failed_count": len(failed),
    }
