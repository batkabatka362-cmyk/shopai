"""Niche-aware product image alt-text suggestion generator.

Most Shopify stores ship product images with empty
``alt`` attributes. Cost:

  * **Accessibility:** screen readers announce
    "image" -- useless for visually impaired buyers.
  * **SEO:** Google can't index image-search
    results without alt text. Beauty / fashion / home
    lose a significant traffic source.
  * **Indexability:** product pages with empty alts
    score lower in Google's image-search-rich
    snippets.

This module generates niche-aware alt-text suggestions
per product. The Shopify product adapter doesn't currently
expose a media-alt write path, so this module is
**operator-facing reference content**: the suggestions
are persisted as a Shopify page (``product-alt-text``)
the operator pastes into the Admin UI per image.

Once a ``SHOPIFY_UPDATE_PRODUCT_MEDIA_ALT`` adapter
ships, the same suggestion list can drive automatic
write.

Return shape from :func:`generate_product_alt_text`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "suggestions": [
            {
                "product_id": "gid://...",
                "title": "Vitamin C Serum",
                "alt_text": "Acme Beauty Vitamin C
                  Serum -- brightening skincare in
                  glass bottle, 30ml",
                "rationale": "Brand + product + key
                  category + visible detail (size)",
            },
            ...
        ],
        "skipped": [
            {product_id, reason},
        ],
    }
"""
from __future__ import annotations

import html
import logging
from typing import Any, Iterable

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Per-niche tone fragment used in alt-text generation.
# Each entry is the bridge phrase between the product
# title and the visual description.
_NICHE_DESCRIPTORS: dict[str, str] = {
    "beauty": "skincare / beauty product",
    "fashion": "apparel / fashion piece",
    "tech": "tech product / electronics",
    "home": "home goods / decor",
    "food": "food / pantry item",
    "pets": "pet product",
    "fitness": "fitness gear / supplement",
    "jewelry": "jewelry piece",
    "outdoor": "outdoor gear",
    "baby": "baby / nursery product",
    "general": "product",
}


# Niche-specific visible-detail hints to enrich the alt.
# These suggest WHAT to mention about the image (size /
# colour / material / setting).
_NICHE_DETAIL_HINTS: dict[str, list[str]] = {
    "beauty": ["packaging", "size_ml", "colour_finish"],
    "fashion": ["fabric", "fit", "colour", "model_pose"],
    "tech": ["model_number", "form_factor", "colour"],
    "home": ["material", "dimensions", "setting"],
    "food": ["pack_size", "ingredients_visible"],
    "pets": ["pack_size", "species_image"],
    "fitness": ["size_dose", "form_factor"],
    "jewelry": [
        "metal",
        "stone",
        "size_carat",
        "setting",
    ],
    "outdoor": [
        "model_size",
        "weather_rating",
        "trail_setting",
    ],
    "baby": ["age_stage", "fabric", "colour"],
    "general": ["packaging", "size"],
}


_ALT_TEXT_PAGE_TITLE: str = "Product Alt Text"
_ALT_TEXT_PAGE_HANDLE: str = "product-alt-text"


_MAX_ALT_CHARS: int = 125  # screen-reader friendly cap


def generate_product_alt_text(
    products: Iterable[dict[str, Any]],
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build alt-text suggestions for a list of products.

    Args:
        products: Iterable of product dicts in the
            friendly shape SHOPIFY_LIST_PRODUCTS emits
            (id / title / vendor / product_type / tags).
            Empty -> empty result.
        store_name: Brand name (interpolated into every
            alt). Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.

    Returns:
        ``{store_name, niche, suggestions, skipped}``.
        Each suggestion: ``{product_id, title,
        alt_text, rationale}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}
    if not products:
        return {
            "store_name": name,
            "niche": (niche or "general"),
            "suggestions": [],
            "skipped": [],
        }

    niche_n = (niche or "general").strip().lower() or "general"
    descriptor = _NICHE_DESCRIPTORS.get(
        niche_n, _NICHE_DESCRIPTORS["general"],
    )
    detail_hints = _NICHE_DETAIL_HINTS.get(
        niche_n, _NICHE_DETAIL_HINTS["general"],
    )

    suggestions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for product in products:
        if not isinstance(product, dict):
            continue
        pid = product.get("id") or ""
        title = (product.get("title") or "").strip()
        if not pid:
            skipped.append({
                "product_id": "",
                "reason": "missing_product_id",
            })
            continue
        if not title:
            skipped.append({
                "product_id": pid,
                "reason": "missing_title",
            })
            continue

        alt = _build_alt(
            store_name=name,
            title=title,
            descriptor=descriptor,
            product_type=(
                product.get("product_type")
                or product.get("type")
                or ""
            ),
            vendor=product.get("vendor", "") or "",
        )
        suggestions.append({
            "product_id": pid,
            "title": title,
            "alt_text": alt,
            "rationale": _rationale(detail_hints),
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "suggestions": suggestions,
        "skipped": skipped,
    }


def _build_alt(
    *,
    store_name: str,
    title: str,
    descriptor: str,
    product_type: str,
    vendor: str,
) -> str:
    """Compose the alt text string.

    Shopify + WCAG best practice: <= 125 characters,
    brand + product + visible-attribute focus, never
    "image of" prefix.
    """
    pt = (product_type or "").strip()
    vendor_clean = (vendor or "").strip()

    # Build candidate parts in priority order; drop later
    # parts if total exceeds the cap.
    parts: list[str] = [store_name, title]
    if pt and pt.lower() != title.lower():
        parts.append(pt)
    if (
        vendor_clean
        and vendor_clean.lower() != store_name.lower()
    ):
        parts.append(f"by {vendor_clean}")
    parts.append(descriptor)

    alt = " -- ".join(p for p in parts if p)
    if len(alt) <= _MAX_ALT_CHARS:
        return alt
    # Trim back the descriptor / vendor first
    alt = " -- ".join(
        p for p in (store_name, title, pt or descriptor)
        if p
    )
    return alt[:_MAX_ALT_CHARS]


def _rationale(hints: list[str]) -> str:
    """One-line operator-facing rationale per niche."""
    base = "Brand + product + category + visible detail"
    if hints:
        base = (
            f"{base} (consider: "
            f"{', '.join(hints[:3])})"
        )
    return base


def render_alt_text_html(spec: dict[str, Any]) -> str:
    if not isinstance(spec, dict) or not spec.get(
        "suggestions",
    ):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    suggestions = spec.get("suggestions") or []
    skipped = spec.get("skipped") or []

    rows: list[str] = []
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{html.escape(s.get('title', ''))}</td>"
            f"<td><code>{html.escape(s.get('product_id', ''))}</code></td>"
            f"<td>{html.escape(s.get('alt_text', ''))}</td>"
            "</tr>"
        )

    skipped_block = ""
    if skipped:
        skipped_block = (
            "<h2>Skipped Products</h2>"
            "<table class=\"alt-skipped\">"
            "<thead><tr><th>Product ID</th>"
            "<th>Reason</th></tr></thead>"
            "<tbody>"
            + "".join(
                "<tr>"
                f"<td><code>{html.escape(s.get('product_id', ''))}</code></td>"
                f"<td>{html.escape(s.get('reason', ''))}</td>"
                "</tr>"
                for s in skipped
                if isinstance(s, dict)
            ) +
            "</tbody></table>"
        )

    return (
        "<section class=\"product-alt-text\">"
        f"<h1>{name} -- Product Alt Text Suggestions</h1>"
        "<p>Each product image needs descriptive alt "
        "text for accessibility + SEO. Paste the "
        "suggestions below into Shopify Admin -> "
        "Products -> [product] -> Media -> Alt text. "
        "Keep under 125 characters; lead with brand + "
        "product name.</p>"
        "<table class=\"alt-suggestions\">"
        "<thead><tr><th>Product</th><th>ID</th>"
        "<th>Suggested Alt</th></tr></thead>"
        "<tbody>"
        + "".join(rows) +
        "</tbody></table>"
        + skipped_block +
        "</section>"
    )


def apply_alt_text_suggestions(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist suggestions as Shopify page
    ``product-alt-text``.

    No media-alt write adapter exists yet; this is
    operator-facing reference content.
    """
    if not isinstance(spec, dict) or not spec.get(
        "suggestions",
    ):
        return {
            "applied": False,
            "handle": _ALT_TEXT_PAGE_HANDLE,
            "error": "no_alt_text_spec",
        }

    body_html = render_alt_text_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _ALT_TEXT_PAGE_HANDLE,
            "error": "empty_render",
        }

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        _record(
            success=False, store_id=store_id,
            error="router_unavailable", spec=spec,
        )
        return {
            "applied": False,
            "handle": _ALT_TEXT_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _ALT_TEXT_PAGE_TITLE,
        "handle": _ALT_TEXT_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_alt_text router.execute raised: "
            "%s", exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _ALT_TEXT_PAGE_HANDLE,
            "error": f"adapter_raise: {exc}",
        }

    ok = bool(getattr(result, "ok", False))
    error = getattr(result, "error", None)
    _record(
        success=ok, store_id=store_id,
        error=None if ok else str(error or "rejected"),
        spec=spec,
    )
    if ok:
        return {
            "applied": True,
            "handle": _ALT_TEXT_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _ALT_TEXT_PAGE_HANDLE,
        "error": str(error or "rejected"),
    }


# ── Helpers ──────────────────────────────────────────────────


def _record(
    *,
    success: bool,
    store_id: str | None,
    error: str | None,
    spec: dict[str, Any],
) -> None:
    suggestions = spec.get("suggestions") or []
    params: dict[str, Any] = {
        "handle": _ALT_TEXT_PAGE_HANDLE,
        "suggestion_count": len(suggestions),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_product_alt_text",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _ALT_TEXT_PAGE_HANDLE,
                "suggestion_count": len(suggestions),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_alt_text record_writeback raised: "
            "%s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_alt_text router import failed: %s",
            exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_alt_text capability resolve "
            "failed: %s", exc,
        )
        return None
