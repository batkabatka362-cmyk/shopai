"""Content Generation Engine — Shopify product-description applier.

Phase 7.2 wireup. The engine generates product descriptions
(headline + body) for a given product. Without writeback, the
merchant has to copy/paste the LLM output into Shopify by hand.
This wireup pushes the generated body into
``SHOPIFY_UPDATE_PRODUCT.descriptionHtml`` automatically when
the caller opts in.

Stricter safety than the discount minters because this overwrites
existing product copy:

  * Only acts when ``content_type == "product_description"``
    (other content types — ad copy, social posts, email — don't
    map to a product field).
  * The product must carry a Shopify GID (``product.id``).
  * Body must be non-empty after stripping whitespace.
  * Optional ``min_seo_score`` + ``min_readability_score`` floors
    let callers gate on quality. Defaults 0 (any score
    acceptable).
  * ``data.apply_content == True`` opt-in.

Returns a single result dict (not a list — content_generation
runs per-product per-call) so callers can inspect what was
written or why it was skipped.

Phase 8 integration: every adapter call (success or failure) is
recorded via ``engines._writeback_recorder.record_writeback`` so
the autonomous loop can later correlate description rewrites with
conversion-rate impact.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.content_generation.applier")


# Only this content type maps to a Shopify product field.
_APPLIABLE_CONTENT_TYPES = {"product_description"}


def apply_description(
    *,
    product: dict[str, Any],
    content_block: dict[str, Any],
    content_type: str,
    seo_score: float = 0.0,
    readability_score: float = 0.0,
    min_seo_score: float = 0.0,
    min_readability_score: float = 0.0,
) -> dict[str, Any]:
    """Update a product's description in Shopify with generated content.

    Args:
        product: Input product dict — must have ``id`` (Shopify GID).
        content_block: Generated content dict from the engine —
            uses the ``body`` field (HTML-ready text).
        content_type: Engine input content_type
            (``"product_description"`` is the only mintable type;
            ``"ad_copy"`` / ``"email"`` / etc. are skipped).
        seo_score: Engine-computed SEO quality 0-1.
        readability_score: Engine-computed readability 0-1.
        min_seo_score: Floor — skip if SEO below this. Default 0
            (any score acceptable).
        min_readability_score: Floor — skip if readability below
            this. Default 0.

    Returns:
        ``{product_id, applied, body_length, error}`` — single
        dict, not list, since the engine runs per-product.
    """
    product_id = str(product.get("id", "")).strip()
    body = str(content_block.get("body", "")).strip()
    body_length = len(body)

    base_result: dict[str, Any] = {
        "product_id": product_id,
        "applied": False,
        "body_length": body_length,
        "error": None,
    }

    # ---- Pre-flight gates ----
    if content_type not in _APPLIABLE_CONTENT_TYPES:
        base_result["error"] = "content_type_not_appliable"
        return base_result

    if not product_id:
        base_result["error"] = "product_id_missing"
        return base_result

    if not body:
        base_result["error"] = "body_empty"
        return base_result

    if seo_score < min_seo_score:
        base_result["error"] = "below_min_seo_score"
        return base_result

    if readability_score < min_readability_score:
        base_result["error"] = "below_min_readability_score"
        return base_result

    # ---- Resolve router + capability ----
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        base_result["error"] = "router_unavailable"
        return base_result

    # ---- Adapter call ----
    recorder_params = {
        "product_id": product_id,
        "body_length": body_length,
        "seo_score": seo_score,
        "readability_score": readability_score,
    }

    try:
        result = router.execute(
            capability,
            {"id": product_id, "description_html": body},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "apply_description raised for %s: %s", product_id, exc,
        )
        record_writeback(
            engine="content_generation",
            action_type="apply_description",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=False,
            error=f"adapter_raised: {exc}",
        )
        base_result["error"] = f"adapter_raised: {exc}"
        return base_result

    if not getattr(result, "ok", False):
        err = getattr(result, "error", "unknown")
        logger.debug(
            "apply_description failed for %s: %s", product_id, err,
        )
        record_writeback(
            engine="content_generation",
            action_type="apply_description",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=False,
            error=f"adapter_failed: {err}",
        )
        base_result["error"] = f"adapter_failed: {err}"
        return base_result

    record_writeback(
        engine="content_generation",
        action_type="apply_description",
        capability="SHOPIFY_UPDATE_PRODUCT",
        params=recorder_params,
        success=True,
    )
    base_result["applied"] = True
    return base_result


def enqueue_description_for_approval(
    *,
    product: dict[str, Any],
    content_block: dict[str, Any],
    content_type: str,
    seo_score: float = 0.0,
    readability_score: float = 0.0,
    min_seo_score: float = 0.0,
    min_readability_score: float = 0.0,
) -> dict[str, Any]:
    """Park a generated description in the approval queue.

    Per-engine alternative to :func:`apply_description` —
    selected by the flow when ``data.require_approval=True``.
    Same upfront filters as the direct path; on success returns
    ``{product_id, applied=False, body_length, error="queued",
    pending_action_id}``. The merchant's approval page will see
    a body-length / SEO / readability summary in the narrative
    so they can sanity-check without scrolling through the full
    HTML.

    Description rewrites overwrite existing copy, so the
    queue gating is especially valuable here — a regrettable
    rewrite is hard to roll back without the merchant's
    pre-existing description handy.
    """
    product_id = str(product.get("id", "")).strip()
    body = str(content_block.get("body", "")).strip()
    body_length = len(body)

    base_result: dict[str, Any] = {
        "product_id": product_id,
        "applied": False,
        "body_length": body_length,
        "error": None,
        "pending_action_id": None,
    }

    if content_type not in _APPLIABLE_CONTENT_TYPES:
        base_result["error"] = "content_type_not_appliable"
        return base_result
    if not product_id:
        base_result["error"] = "product_id_missing"
        return base_result
    if not body:
        base_result["error"] = "body_empty"
        return base_result
    if seo_score < min_seo_score:
        base_result["error"] = "below_min_seo_score"
        return base_result
    if readability_score < min_readability_score:
        base_result["error"] = "below_min_readability_score"
        return base_result

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        base_result["error"] = "approval_queue_unavailable"
        return base_result

    headline = str(content_block.get("headline", "")).strip()
    narrative = (
        f"Rewrite description for {product_id} "
        f"({body_length} chars"
        + (f", headline: \"{headline[:60]}\"" if headline else "")
        + f", SEO {seo_score:.2f}, readability {readability_score:.2f})"
        + " — DESTRUCTIVE, overwrites existing copy"
    )
    params = {
        "product_id": product_id,
        "body_length": body_length,
        "headline": headline,
        "body_preview": body[:200],
        "seo_score": seo_score,
        "readability_score": readability_score,
    }

    try:
        action = queue.enqueue(
            engine="content_generation",
            action_type="apply_description",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=params,
            narrative=narrative,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "enqueue raised for %s: %s", product_id, exc,
        )
        base_result["error"] = f"enqueue_raised: {exc}"
        return base_result

    base_result["error"] = "queued"
    base_result["pending_action_id"] = action.id
    return base_result


# ── Helpers ────────────────────────────────────────────────────


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
