"""Niche-aware product description enricher.

Many Shopify stores launch with products that have either no
description or a one-liner pulled straight from a supplier.
That's the conversion equivalent of an empty page -- visitors
land on the PDP and bounce because there's nothing to read.

This module fills that gap deterministically (no LLM required
for the first pass). For each product missing a substantive
description, it generates a niche-aware HTML body interpolated
from the product's own metadata (title, type, vendor, tags).

What "real measurable outcome" looks like here:

  * Before: product page renders with a 30-character supplier
    blurb or none at all.
  * After: product page has 200+ words of niche-appropriate
    copy explaining what it is, why it matters, what's in the
    box.

The applier pushes through the EXISTING
``SHOPIFY_UPDATE_PRODUCT`` adapter (no new capability).
Records via Pattern Z so the autonomous learning loop sees
every enrichment attempt -- and a future ``launch_audit``
check can verify the percentage of products with non-empty
descriptions.

API
---

::

    from engines.store_setup.product_description_enricher import (
        enrich_products,
    )

    result = enrich_products(
        products=products_from_shopify,
        niche="beauty",
        min_existing_length=80,  # skip if existing body >= 80 chars
    )
    # result = {
    #     "generated": list[{product_id, title, body_html}],
    #     "skipped":   list[{product_id, reason}],
    # }

The applier is a separate function so callers that want to
review the generated copy before pushing (e.g. operator
approval) can stop after :func:`enrich_products` and resume
via :func:`apply_descriptions` later.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Iterable

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Niche-specific framing phrases used in the description body.
_NICHE_CONTEXT: dict[str, dict[str, str]] = {
    "beauty": {
        "intro": (
            "Curated for everyday confidence."
        ),
        "promise": (
            "Clean formulas. Honest ingredients. "
            "Real results."
        ),
    },
    "fashion": {
        "intro": (
            "Designed for the way you actually dress."
        ),
        "promise": (
            "Quality fabrics. Timeless cuts. "
            "Sized to fit real bodies."
        ),
    },
    "tech": {
        "intro": (
            "Built for daily use, not just product photos."
        ),
        "promise": (
            "Reliable performance. Premium materials. "
            "Designed to last."
        ),
    },
    "home": {
        "intro": (
            "A small upgrade that you'll notice every day."
        ),
        "promise": (
            "Thoughtful design. Sustainable materials. "
            "Built to last past the next move."
        ),
    },
    "food": {
        "intro": (
            "Sourced from people who actually care about "
            "the ingredients."
        ),
        "promise": (
            "Small batch. Honest sourcing. Real flavour."
        ),
    },
    "general": {
        "intro": (
            "Hand-picked for the people who shop with us."
        ),
        "promise": (
            "Quality first. No filler. Honest pricing."
        ),
    },
}


def enrich_products(
    products: Iterable[dict[str, Any]],
    *,
    niche: str = "general",
    min_existing_length: int = 80,
) -> dict[str, Any]:
    """Generate description bodies for products that need one.

    Args:
        products: Iterable of product dicts in the friendly
            shape ``SHOPIFY_LIST_PRODUCTS`` emits
            (``{id, title, body_html, vendor, product_type,
            tags, ...}``). Empty/None iterables short-circuit
            to ``{generated: [], skipped: []}``.
        niche: Niche key for tone. Unknown niches fall back
            to ``general``.
        min_existing_length: If a product already has a
            description with at least this many characters,
            skip it (the operator's existing copy wins).

    Returns:
        ``{generated: [...], skipped: [...]}`` -- the generated
        list carries ``{product_id, title, body_html}``; the
        skipped list carries ``{product_id, reason}``.
    """
    if not products:
        return {"generated": [], "skipped": []}

    niche_n = (niche or "general").strip().lower() or "general"
    context = _NICHE_CONTEXT.get(
        niche_n, _NICHE_CONTEXT["general"],
    )
    min_existing_length = max(0, int(min_existing_length))

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

        existing_body = (
            product.get("body_html")
            or product.get("description")
            or ""
        )
        if (
            isinstance(existing_body, str)
            and len(existing_body.strip()) >= min_existing_length
        ):
            skipped.append({
                "product_id": product_id,
                "reason": (
                    f"existing_description_ok "
                    f"({len(existing_body.strip())} chars)"
                ),
            })
            continue

        # ── Path 1: LLM ──────────────────────────────────────
        llm_body = _enrich_one_via_llm(
            product=product, niche=niche_n, context=context,
        )
        if llm_body:
            body_html = llm_body
        else:
            # ── Path 2: Templates ────────────────────────────
            body_html = _build_description(product, context)
        generated.append({
            "product_id": product_id,
            "title": title,
            "body_html": body_html,
        })

    return {"generated": generated, "skipped": skipped}


# ── LLM-driven enrichment (per product) ───────────────────


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")

# A landing-quality body should be 150-400 words. Below 100
# words is a degenerate result -- fall back to template.
_LLM_MIN_BODY_CHARS = 600


def _enrich_one_via_llm(
    *,
    product: dict[str, Any],
    niche: str,
    context: dict[str, str],
) -> str | None:
    """Generate a single product's body_html via the LLM router.

    Returns the HTML body on success, ``None`` on any failure
    (caller falls back to template builder). Never raises.
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

    title = (product.get("title") or "").strip()
    product_type = (
        product.get("product_type")
        or product.get("type")
        or ""
    ).strip()
    vendor = (product.get("vendor") or "").strip()
    tags = product.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    tags_line = ", ".join(str(t) for t in tags[:8]) if tags else "n/a"

    system_prompt = (
        "You are an expert Shopify product copywriter. Write "
        "product descriptions that convert. Lead with the "
        f"benefit, not the feature. Niche framing: '{context.get('intro', '')}' "
        f"and '{context.get('promise', '')}'. Length: 200-400 "
        "words. Format: clean HTML with <p>, <ul>, <li> tags "
        "(no <html>/<body> wrapper, no <h1>). Always respond "
        "with STRICT JSON; no markdown fences."
    )

    user_prompt = (
        f"Product: {title}\n"
        f"Product type: {product_type or 'n/a'}\n"
        f"Vendor: {vendor or 'n/a'}\n"
        f"Tags: {tags_line}\n"
        f"Niche: {niche}\n\n"
        "Return STRICT JSON in this exact shape:\n"
        "{\n"
        '  "body_html": "the full HTML body (200-400 words, <p>/<ul>/<li>)"\n'
        "}"
    )

    try:
        result = router.execute(Capability.CHAT_COMPLETE, {
            "system": system_prompt,
            "prompt": user_prompt,
            "max_tokens": 1500,
            "temperature": 0.7,
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

    body_html = str(parsed.get("body_html") or "").strip()
    if not body_html:
        return None

    # Degenerate-result guard: too short means the model
    # likely returned a slogan, not a description. Fall back.
    if len(body_html) < _LLM_MIN_BODY_CHARS:
        return None

    return body_html


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


def apply_descriptions(
    updates: list[dict[str, Any]],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Push generated descriptions via SHOPIFY_UPDATE_PRODUCT.

    Args:
        updates: List from :func:`enrich_products`'s
            ``generated`` field. Each carries ``product_id``
            + ``body_html``.
        store_id: Optional per-store Pattern Z scope.

    Returns:
        ``{applied_count, results}`` -- per-product
        ``{product_id, ok, error}``.
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
        body = upd.get("body_html", "")
        if not product_id or not body:
            results.append({
                "product_id": product_id,
                "ok": False,
                "error": "missing_product_id_or_body",
            })
            _record(
                product_id=product_id, success=False,
                store_id=store_id,
                error="missing_product_id_or_body",
            )
            continue
        try:
            adapter_result = router.execute(capability, {
                "id": product_id,
                "body_html": body,
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "product_description_enricher: router raised "
                "for %s: %s", product_id, exc,
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


# ── Helpers ────────────────────────────────────────────────


def _build_description(
    product: dict[str, Any],
    context: dict[str, str],
) -> str:
    """Build the HTML body for one product.

    The template uses the product's own metadata (title,
    product_type, vendor, tags) to keep the copy specific
    enough that it doesn't read like Lorem Ipsum. Pure
    interpolation -- no LLM call -- so it works offline + on
    cold-start stores.
    """
    title = (product.get("title") or "").strip()
    product_type = (
        product.get("product_type")
        or product.get("type")
        or ""
    ).strip()
    vendor = (product.get("vendor") or "").strip()
    tags = product.get("tags") or []
    if isinstance(tags, str):
        tags = [
            t.strip() for t in tags.split(",") if t.strip()
        ]
    if not isinstance(tags, list):
        tags = []
    tags_clean = [str(t).strip() for t in tags if str(t).strip()]

    intro = context.get("intro", "")
    promise = context.get("promise", "")

    parts: list[str] = []
    parts.append(f"<h2>{title}</h2>")
    parts.append(f"<p><em>{intro}</em></p>")
    descriptor = product_type or "product"
    parts.append(
        f"<p>The <strong>{title}</strong> is a "
        f"{descriptor} we picked because it does what it says "
        "on the tin -- no marketing fluff, no hidden trade-offs.</p>"
    )

    if vendor:
        parts.append(
            f"<p>Made by <strong>{vendor}</strong>, with the "
            "same quality control we'd want on every order.</p>"
        )

    if tags_clean:
        parts.append("<h3>Highlights</h3>")
        parts.append("<ul>")
        for tag in tags_clean[:6]:
            parts.append(f"<li>{tag}</li>")
        parts.append("</ul>")

    parts.append(f"<p>{promise}</p>")
    parts.append(
        "<h3>What's in the box</h3>"
        "<ul>"
        f"<li>1 × {title}</li>"
        "<li>Care + use instructions where applicable</li>"
        "</ul>"
    )
    return "".join(parts)


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
            action_type="apply_product_description",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=params,
            success=bool(success),
            error=error,
            metrics={"product_id": product_id},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_description_enricher record_writeback "
            "raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_description_enricher router import "
            "failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_description_enricher capability resolve "
            "failed: %s", exc,
        )
        return None
