"""Niche-aware SEO meta enricher for products.

A Shopify product without ``seo_title`` + ``seo_description``
gets ranked by Google using just its handle and on-page H1.
Most stores leave these blank, which means Google guesses --
and Google's guess is rarely the conversion-optimised
headline a real merchant would write.

This module fills the gap. For each product missing meta
fields, it generates niche-appropriate title_tag (50-60 chars)
+ meta_description (140-160 chars) interpolated from the
product's own title + product_type + vendor.

Mirrors the ``product_description_enricher`` pattern (PR
that introduced the deterministic-template approach). Pure
interpolation -- no LLM call -- so it works offline and on
cold-start stores. A future PR can swap in an LLM body for
operator-approved meta when one's available.

Returns shape::

    {
        "generated": [
            {product_id, title, seo_title, seo_description},
            ...
        ],
        "skipped": [
            {product_id, reason},
            ...
        ],
    }

The applier pushes through the EXISTING
``SHOPIFY_UPDATE_PRODUCT`` adapter (no new capability;
products.py already accepts ``seo_title`` / ``seo_description``
kwargs). Records via Pattern Z.

Why "measurable outcome": every product gets a search-engine-
friendly snippet. A future ``launch_audit`` extension can
count the percentage of products with non-empty SEO fields
as a readiness indicator.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Iterable

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Per-niche tagline fragments used in the meta description.
_NICHE_TAGLINES: dict[str, str] = {
    "beauty": "Clean beauty, honest results.",
    "fashion": "Curated styles for real bodies.",
    "tech": "Premium tech that just works.",
    "home": "Thoughtful design, built to last.",
    "food": "Small-batch flavours, honestly sourced.",
    "general": "Quality you can trust.",
}

# title_tag character target. Google clips at ~60 chars on
# desktop; we aim for 50-58 to leave room for the storefront
# suffix Shopify appends.
_TITLE_MAX = 58

# meta_description character target. Google's recommended
# range is 120-160; we aim for 145-155 to stay safe across
# device classes.
_META_TARGET_MIN = 120
_META_MAX = 158


def enrich_seo(
    products: Iterable[dict[str, Any]],
    *,
    niche: str = "general",
    store_name: str = "",
    overwrite_existing: bool = False,
) -> dict[str, Any]:
    """Generate SEO title + meta description for products.

    Args:
        products: Iterable of product dicts in the friendly
            shape ``SHOPIFY_LIST_PRODUCTS`` emits. Each may
            optionally carry ``seo_title`` / ``seo_description``
            from a previous read; those are PRESERVED unless
            ``overwrite_existing=True``.
        niche: Niche key for tone. Unknown -> ``general``.
        store_name: Optional brand suffix appended to the
            title when there's room.
        overwrite_existing: When True, replace existing
            meta even if non-empty (use for forced refresh
            after a brand rename).

    Returns:
        ``{generated, skipped}`` -- generated items carry
        ``{product_id, title, seo_title, seo_description}``;
        skipped items carry ``{product_id, reason}``.
    """
    if not products:
        return {"generated": [], "skipped": []}

    niche_n = (niche or "general").strip().lower() or "general"
    tagline = _NICHE_TAGLINES.get(
        niche_n, _NICHE_TAGLINES["general"],
    )
    brand_suffix = (store_name or "").strip()

    generated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for product in products:
        if not isinstance(product, dict):
            continue
        product_id = product.get("id") or ""
        title = (product.get("title") or "").strip()
        if not product_id:
            skipped.append({
                "product_id": "",
                "reason": "missing_product_id",
            })
            continue
        if not title:
            skipped.append({
                "product_id": product_id,
                "reason": "missing_title",
            })
            continue

        existing_seo_title = (
            product.get("seo_title") or ""
        ).strip()
        existing_seo_desc = (
            product.get("seo_description") or ""
        ).strip()

        # Skip when both fields already have content unless
        # the caller forces overwrite.
        if (
            not overwrite_existing
            and existing_seo_title
            and existing_seo_desc
        ):
            skipped.append({
                "product_id": product_id,
                "reason": "existing_seo_ok",
            })
            continue

        product_type = (
            product.get("product_type")
            or product.get("type")
            or ""
        )
        vendor = product.get("vendor", "") or ""

        # ── Path 1: LLM ──────────────────────────────────────
        llm_pair = _enrich_one_via_llm(
            title=title,
            product_type=product_type,
            vendor=vendor,
            niche=niche_n,
            brand_suffix=brand_suffix,
            tagline=tagline,
        )
        if llm_pair is not None:
            seo_title, seo_description = llm_pair
        else:
            # ── Path 2: Templates ────────────────────────────
            seo_title = _build_title(title, brand_suffix)
            seo_description = _build_meta(
                title=title,
                product_type=product_type,
                vendor=vendor,
                tagline=tagline,
            )

        # If the caller already had ONE of the two fields and
        # we're not overwriting, keep the existing one.
        if not overwrite_existing:
            if existing_seo_title:
                seo_title = existing_seo_title
            if existing_seo_desc:
                seo_description = existing_seo_desc

        generated.append({
            "product_id": product_id,
            "title": title,
            "seo_title": seo_title,
            "seo_description": seo_description,
        })

    return {"generated": generated, "skipped": skipped}


def apply_seo(
    updates: list[dict[str, Any]],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Push generated SEO metadata via SHOPIFY_UPDATE_PRODUCT.

    Args:
        updates: List from :func:`enrich_seo`'s ``generated``
            field. Each carries ``product_id`` + ``seo_title``
            + ``seo_description``.
        store_id: Optional per-store Pattern Z scope.

    Returns:
        ``{applied_count, results}``.
    """
    if not isinstance(updates, list) or not updates:
        return {"applied_count": 0, "results": []}

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        results = [
            {
                "product_id": u.get("product_id", ""),
                "ok": False,
                "error": "router_unavailable",
            }
            for u in updates
        ]
        for r in results:
            _record(
                product_id=r["product_id"],
                success=False, store_id=store_id,
                error=r["error"],
            )
        return {"applied_count": 0, "results": results}

    results: list[dict[str, Any]] = []
    applied = 0
    for upd in updates:
        product_id = upd.get("product_id", "")
        seo_title = upd.get("seo_title", "")
        seo_description = upd.get("seo_description", "")
        if not product_id or (
            not seo_title and not seo_description
        ):
            results.append({
                "product_id": product_id,
                "ok": False,
                "error": "missing_product_id_or_seo",
            })
            _record(
                product_id=product_id, success=False,
                store_id=store_id,
                error="missing_product_id_or_seo",
            )
            continue

        params: dict[str, Any] = {"id": product_id}
        if seo_title:
            params["seo_title"] = seo_title
        if seo_description:
            params["seo_description"] = seo_description

        try:
            adapter_result = router.execute(
                capability, params,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "seo_meta_enricher router raised for %s: %s",
                product_id, exc,
            )
            results.append({
                "product_id": product_id,
                "ok": False,
                "error": f"adapter_raise: {exc}",
            })
            _record(
                product_id=product_id, success=False,
                store_id=store_id, error=str(exc),
            )
            continue
        ok = bool(getattr(adapter_result, "ok", False))
        error = getattr(adapter_result, "error", None)
        if ok:
            applied += 1
            results.append({
                "product_id": product_id,
                "ok": True,
                "error": None,
            })
            _record(
                product_id=product_id, success=True,
                store_id=store_id, error=None,
            )
        else:
            results.append({
                "product_id": product_id,
                "ok": False,
                "error": str(error or "rejected"),
            })
            _record(
                product_id=product_id, success=False,
                store_id=store_id,
                error=str(error or "rejected"),
            )
    return {"applied_count": applied, "results": results}


# ── LLM-driven enrichment (per product) ───────────────────


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _enrich_one_via_llm(
    *,
    title: str,
    product_type: str,
    vendor: str,
    niche: str,
    brand_suffix: str,
    tagline: str,
) -> tuple[str, str] | None:
    """Generate ``(seo_title, seo_description)`` for a single
    product via the LLM router.

    Returns the pair on success, ``None`` on any failure
    (caller falls back to the template builders). Never
    raises.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None

    try:
        from core.adapters import get_router as _get_router_fn
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM router import failed: %s", exc)
        return None

    try:
        router = _get_router_fn()
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM router init failed: %s", exc)
        return None

    system_prompt = (
        "You are an expert e-commerce SEO copywriter. Your "
        "single job: write Google-friendly SEO meta for "
        "Shopify products. STRICT length rules: title <= "
        f"{_TITLE_MAX} chars, description {_META_TARGET_MIN}-"
        f"{_META_MAX} chars. Lead with the benefit, fit the "
        "keyword naturally. Always respond with STRICT JSON; "
        "no markdown fences, no commentary outside the JSON."
    )

    brand_line = (
        f"Store/brand: {brand_suffix}\n"
        if brand_suffix
        else "Store/brand: (unbranded)\n"
    )
    vendor_line = (
        f"Vendor: {vendor}\n" if vendor else ""
    )
    user_prompt = (
        f"Product: {title}\n"
        f"{brand_line}"
        f"Product type: {product_type or 'n/a'}\n"
        f"{vendor_line}"
        f"Niche: {niche}\n"
        f"Niche tagline guide: {tagline}\n\n"
        f"Return STRICT JSON:\n"
        '{\n'
        f'  "seo_title": "search-friendly title (<= {_TITLE_MAX} chars)",\n'
        f'  "seo_description": "search-friendly description ({_META_TARGET_MIN}-{_META_MAX} chars)"\n'
        '}'
    )

    try:
        result = router.execute(Capability.CHAT_COMPLETE, {
            "system": system_prompt,
            "prompt": user_prompt,
            "max_tokens": 400,
            "temperature": 0.5,  # lower -- SEO meta favors precision
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM call raised for %s: %s", title, exc)
        return None

    if not getattr(result, "ok", False):
        logger.debug(
            "LLM call returned not-ok for %s: %s",
            title, getattr(result, "error", "unknown"),
        )
        return None

    text = ((result.data or {}).get("text") or "").strip()
    if not text:
        return None

    parsed = _parse_llm_json(text)
    if not parsed:
        return None

    seo_title = str(parsed.get("seo_title") or "").strip()
    seo_description = str(parsed.get("seo_description") or "").strip()

    if not seo_title or not seo_description:
        return None

    # Enforce length caps post-LLM (don't trust the model).
    if len(seo_title) > _TITLE_MAX:
        seo_title = _truncate_at_word(seo_title, _TITLE_MAX)
    if len(seo_description) > _META_MAX:
        seo_description = _truncate_at_word(seo_description, _META_MAX)
    # A too-short description is fine to surface -- Google
    # accepts it -- but if the model returned literally a few
    # chars, treat that as a degenerate result.
    if len(seo_description) < 40:
        return None

    return (seo_title, seo_description)


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON parse, tolerates markdown fences."""
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        pass
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        return None


# ── Helpers ────────────────────────────────────────────────


def _build_title(
    product_title: str, brand_suffix: str,
) -> str:
    """Build a title_tag for search engines.

    Strategy: ``<product_title>`` first, then ``| <brand>``
    suffix only when the combined length stays under
    _TITLE_MAX. If the product title alone exceeds the limit
    we truncate cleanly at the last word boundary.
    """
    title = (product_title or "").strip()
    if not title:
        return ""
    if len(title) > _TITLE_MAX:
        # Truncate at word boundary
        return _truncate_at_word(title, _TITLE_MAX)
    if brand_suffix:
        candidate = f"{title} | {brand_suffix}"
        if len(candidate) <= _TITLE_MAX:
            return candidate
    return title


def _build_meta(
    *,
    title: str,
    product_type: str,
    vendor: str,
    tagline: str,
) -> str:
    """Build a meta_description in the 120-158 char range."""
    title = (title or "").strip()
    product_type = (product_type or "").strip()
    vendor = (vendor or "").strip()
    tagline = (tagline or "").strip()

    descriptor = (
        product_type or "product"
    ).lower()
    parts: list[str] = []
    parts.append(f"{title} -- a {descriptor}")
    if vendor:
        parts.append(f" by {vendor}")
    parts.append(f". {tagline}")

    text = "".join(parts).strip()
    if len(text) <= _META_MAX:
        return text
    return _truncate_at_word(text, _META_MAX)


def _truncate_at_word(text: str, limit: int) -> str:
    """Truncate ``text`` to at most ``limit`` characters at the
    last word boundary. Single very-long words are hard-cut."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    if not cut:
        return text[:limit]
    # Trim trailing punctuation so we don't end with a dangling
    # comma / period fragment.
    while cut and cut[-1] in ",.; ":
        cut = cut[:-1]
    return cut


def _record(
    *,
    product_id: str,
    success: bool,
    store_id: str | None,
    error: str | None,
) -> None:
    params: dict[str, Any] = {"product_id": product_id}
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_product_seo",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=params,
            success=bool(success),
            error=error,
            metrics={"product_id": product_id},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "seo_meta_enricher record_writeback raised: %s",
            exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "seo_meta_enricher router import failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "seo_meta_enricher capability resolve failed: %s",
            exc,
        )
        return None
