"""Product Launch Engine — winner → complete launch plan spec.

Consumes a scored winner record (from :mod:`engines.winning_products`),
an optional normalised supplier product (from a sourcing adapter),
and an optional creative pack (from :mod:`engines.ad_creative_generator`)
to produce a single *launch plan*:

  * ``sourcing``        — supplier cost, origin, shipping window
  * ``pricing``         — cost → retail math with margin guard
  * ``shopify_product`` — ready-to-POST Shopify product draft
  * ``ads_campaign``    — platform campaign draft with targeting
  * ``creative_pack``   — echoed from input (or stub)
  * ``readiness``       — ``ready`` / ``pending_approval`` /
                          ``blocked`` gate signal
  * ``blocks``          — human-readable reasons for block
  * ``approvals_needed``— checklist for the operator
  * ``total_est_cost_usd`` — creative + first-day ad spend

This engine is PURELY DETERMINISTIC — no adapter I/O, no API
calls. It emits a spec that downstream execution consumes.

Pricing formula:
  retail = ceil(total_cost / (1 - margin_pct))  →  round to .99
  retail = max(retail, min_price)

Shipping heuristic by origin country:
  CN/HK → $4   |  US → $2   |  EU (DE/FR/IT/ES/NL) → $3
  default → $3

Block rules:
  - winner verdict == "skip"
  - no cost data (supplier or product)
  - creative_pack readiness == "blocked"
  - calculated margin < 20%
  - ads platform == "meta" and no pixel_id
  - daily_budget_usd <= 0 (when ads config present)
"""
from __future__ import annotations

import copy
import math
import re
import time
from typing import Any

ENGINE_NAME = "product_launch"

_DEFAULT_MARGIN_PCT = 0.35
_MIN_MARGIN_PCT = 0.20
_DEFAULT_MIN_PRICE = 9.99
_DEFAULT_SHIPPING_BUFFER = 3.0
_DEFAULT_DAILY_BUDGET = 10.0

_SHIPPING_BY_ORIGIN: dict[str, float] = {
    "CN": 4.0,
    "HK": 4.0,
    "US": 2.0,
    "DE": 3.0,
    "FR": 3.0,
    "IT": 3.0,
    "ES": 3.0,
    "NL": 3.0,
    "GB": 3.0,
    "UK": 3.0,
    "AU": 3.5,
    "CA": 2.5,
}


class ProductLaunchEngine:
    """Wrapper class for engine-registry compatibility."""

    ENGINE_NAME = ENGINE_NAME
    engine_name = ENGINE_NAME

    def run(self, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        return run(input_data)


def _fail(msg: str, start: float) -> dict[str, Any]:
    return {
        "status": "error",
        "data": {},
        "meta": {
            "engine": ENGINE_NAME,
            "timestamp": time.time(),
            "elapsed_seconds": round(time.monotonic() - start, 3),
        },
        "error": msg,
    }


def run(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Public entry point — winner → launch plan spec."""
    start = time.monotonic()
    data = copy.deepcopy(input_data or {})

    if data.get("status") == "fail":
        return _fail(data.get("error") or "Upstream failure", start)

    winner = data.get("winner")
    if not isinstance(winner, dict) or not winner:
        return _fail("'winner' dict is required", start)

    product = data.get("product") or {}
    if not isinstance(product, dict):
        return _fail(
            f"'product' must be a dict, got {type(product).__name__}",
            start,
        )

    supplier = data.get("supplier_product") or {}
    if not isinstance(supplier, dict):
        supplier = {}

    creative = data.get("creative_pack") or {}
    if not isinstance(creative, dict):
        creative = {}

    pricing_cfg = data.get("pricing") or {}
    if not isinstance(pricing_cfg, dict):
        pricing_cfg = {}

    shopify_cfg = data.get("shopify") or {}
    if not isinstance(shopify_cfg, dict):
        shopify_cfg = {}

    ads_cfg = data.get("ads") or {}
    if not isinstance(ads_cfg, dict):
        ads_cfg = {}

    auto_approve = bool(data.get("auto_approve", False))
    dry_run = bool(data.get("dry_run", False))

    blocks: list[str] = []
    approvals: list[str] = []

    # ── Block: skip verdict ───────────────────────────
    verdict = str(winner.get("verdict", "") or "").lower()
    if verdict == "skip":
        blocks.append("winner verdict is 'skip' — rejected by scoring")

    # ── Stage 1: sourcing summary ─────────────────────
    sourcing = _build_sourcing_summary(supplier, product)

    # ── Stage 2: pricing math ─────────────────────────
    pricing = _compute_pricing(sourcing, pricing_cfg)
    if pricing["cost_usd"] <= 0:
        blocks.append("no cost data — supply supplier_product or product.cost_usd")
    if pricing["cost_usd"] > 0 and pricing["margin_pct"] < _MIN_MARGIN_PCT:
        blocks.append(
            f"margin {pricing['margin_pct']:.0%} < minimum {_MIN_MARGIN_PCT:.0%}"
        )

    # ── Stage 3: Shopify product draft ────────────────
    shopify_product = _build_shopify_draft(
        winner=winner,
        product=product,
        supplier=supplier,
        pricing=pricing,
        shopify_cfg=shopify_cfg,
    )

    # ── Stage 4: ads campaign draft ───────────────────
    ads_campaign = _build_ads_campaign(
        winner=winner,
        product=product,
        creative=creative,
        ads_cfg=ads_cfg,
    )
    platform = ads_campaign.get("platform", "meta")
    if platform == "meta" and not ads_campaign.get("pixel_id"):
        blocks.append("meta ads require pixel_id in ads config")
    if ads_cfg and ads_campaign.get("daily_budget_usd", 0) <= 0:
        blocks.append("daily_budget_usd must be > 0")

    # ── Stage 5: creative_pack pass-through ───────────
    creative_readiness = str(creative.get("readiness", "") or "")
    if creative_readiness == "blocked":
        creative_blocks = creative.get("blocks") or []
        blocks.append(
            f"creative_pack is blocked: {', '.join(str(b) for b in creative_blocks) or 'unknown'}"
        )

    # ── Cost rollup ───────────────────────────────────
    creative_cost = float(creative.get("total_est_cost_usd", 0) or 0)
    daily_budget = float(ads_campaign.get("daily_budget_usd", 0) or 0)
    total_est_cost = round(creative_cost + daily_budget, 2)

    # ── Readiness verdict ─────────────────────────────
    if blocks:
        readiness = "blocked"
    elif auto_approve:
        readiness = "ready"
    else:
        readiness = "pending_approval"

    # ── Approvals checklist ───────────────────────────
    if not blocks:
        approvals.append("Review pricing and margin")
        approvals.append("Confirm Shopify product draft")
        if creative:
            approvals.append("Approve creative pack")
        approvals.append("Confirm ads campaign budget and targeting")
        if verdict == "watch":
            approvals.append("Winner is 'watch' — confirm conviction")

    launch_plan = {
        "product_key":      winner.get("product_key", ""),
        "winner_verdict":   verdict,
        "winner_score":     winner.get("score", 0),
        "sourcing":         sourcing,
        "pricing":          pricing,
        "shopify_product":  shopify_product,
        "ads_campaign":     ads_campaign,
        "creative_pack":    creative,
        "readiness":        readiness,
        "blocks":           blocks,
        "approvals_needed": approvals,
        "total_est_cost_usd": total_est_cost,
        "dry_run":          dry_run,
    }

    elapsed = round(time.monotonic() - start, 3)
    return {
        "status": "success",
        "data": {"launch_plan": launch_plan},
        "meta": {
            "engine": ENGINE_NAME,
            "timestamp": time.time(),
            "elapsed_seconds": elapsed,
        },
        "error": None,
    }


# ---------------------------------------------------------------------------
# Sourcing summary
# ---------------------------------------------------------------------------


def _build_sourcing_summary(
    supplier: dict[str, Any], product: dict[str, Any],
) -> dict[str, Any]:
    """Extract cost/origin/shipping from supplier_product or product."""
    cost = _to_float(supplier.get("cost_usd")) or _to_float(
        product.get("cost_usd"),
    ) or _to_float(product.get("cost"))
    origin = str(
        supplier.get("origin_country")
        or product.get("origin_country")
        or "",
    ).upper()
    ship_min = _to_int(supplier.get("shipping_days_min")) or _to_int(
        product.get("shipping_days_min"),
    )
    ship_max = _to_int(supplier.get("shipping_days_max")) or _to_int(
        product.get("shipping_days_max"),
    )
    sourcing_id = str(supplier.get("sourcing_id", "") or "")
    source = str(supplier.get("source", "") or "")

    return {
        "sourcing_id":      sourcing_id,
        "source":           source,
        "cost_usd":         cost,
        "origin_country":   origin,
        "shipping_days_min": ship_min,
        "shipping_days_max": ship_max,
    }


def _compute_pricing(
    sourcing: dict[str, Any], cfg: dict[str, Any],
) -> dict[str, Any]:
    """Cost → retail pricing with margin guard."""
    cost = float(sourcing.get("cost_usd", 0) or 0)
    origin = str(sourcing.get("origin_country", "") or "").upper()

    margin_pct = _to_float(cfg.get("margin_pct")) or _DEFAULT_MARGIN_PCT
    if margin_pct > 1:
        margin_pct = margin_pct / 100.0
    margin_pct = max(0.01, min(margin_pct, 0.90))

    min_price = _to_float(cfg.get("min_price")) or _DEFAULT_MIN_PRICE
    shipping_buffer = cfg.get("shipping_buffer_usd")
    if shipping_buffer is not None:
        shipping_est = _to_float(shipping_buffer) or 0.0
    else:
        shipping_est = _SHIPPING_BY_ORIGIN.get(origin, _DEFAULT_SHIPPING_BUFFER)

    total_cost = cost + shipping_est

    if total_cost > 0:
        raw_retail = total_cost / (1 - margin_pct)
        retail = _psychological_price(raw_retail)
        retail = max(retail, min_price)
    else:
        retail = 0.0

    margin_usd = retail - total_cost if retail > 0 else 0.0
    actual_margin = margin_usd / retail if retail > 0 else 0.0

    return {
        "cost_usd":             round(cost, 2),
        "shipping_estimate_usd": round(shipping_est, 2),
        "total_cost_usd":       round(total_cost, 2),
        "retail_usd":           round(retail, 2),
        "margin_usd":           round(margin_usd, 2),
        "margin_pct":           round(actual_margin, 4),
        "target_margin_pct":    round(margin_pct, 4),
        "min_price":            round(min_price, 2),
    }


def _psychological_price(raw: float) -> float:
    """Round up to the nearest X.99 price point."""
    if raw <= 0:
        return 0.0
    whole = math.ceil(raw)
    return float(whole) - 0.01


# ---------------------------------------------------------------------------
# Shopify product draft
# ---------------------------------------------------------------------------


def _build_shopify_draft(
    *,
    winner: dict[str, Any],
    product: dict[str, Any],
    supplier: dict[str, Any],
    pricing: dict[str, Any],
    shopify_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Assemble a Shopify-compatible product draft."""
    title = str(
        product.get("title")
        or supplier.get("title")
        or _title_from_winner(winner)
    )
    description = str(
        product.get("description")
        or supplier.get("description")
        or "",
    )
    body_html = _wrap_html(description) if description else ""

    vendor = str(shopify_cfg.get("vendor", "") or "")
    product_type = str(
        product.get("category")
        or supplier.get("category")
        or "",
    )
    status = str(shopify_cfg.get("status", "draft") or "draft")

    tags = _build_tags(winner, product, shopify_cfg)

    images = _collect_images(product, supplier)

    variants = _build_variants(supplier, pricing, shopify_cfg)

    return {
        "title":        title,
        "body_html":    body_html,
        "vendor":       vendor,
        "product_type": product_type,
        "tags":         tags,
        "status":       status,
        "variants":     variants,
        "images":       images,
    }


def _title_from_winner(winner: dict[str, Any]) -> str:
    hero = winner.get("hero_ad") or {}
    if isinstance(hero, dict):
        headline = str(hero.get("headline", "") or "")
        if headline:
            words = headline.split()[:8]
            return " ".join(words)
    return str(winner.get("product_key", "Untitled Product") or "Untitled Product")


def _wrap_html(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if text.startswith("<"):
        return text
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text]
    return "".join(f"<p>{_escape_html(p)}</p>" for p in paragraphs)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_tags(
    winner: dict[str, Any],
    product: dict[str, Any],
    shopify_cfg: dict[str, Any],
) -> list[str]:
    tags: list[str] = []
    cfg_tags = shopify_cfg.get("tags") or []
    if isinstance(cfg_tags, list):
        tags.extend(str(t) for t in cfg_tags if t)
    product_tags = product.get("tags") or []
    if isinstance(product_tags, list):
        tags.extend(str(t) for t in product_tags if t)
    verdict = str(winner.get("verdict", "") or "")
    if verdict:
        tags.append(f"verdict:{verdict}")
    seen: set[str] = set()
    deduped: list[str] = []
    for t in tags:
        low = t.lower()
        if low not in seen:
            seen.add(low)
            deduped.append(t)
    return deduped


def _collect_images(
    product: dict[str, Any], supplier: dict[str, Any],
) -> list[dict[str, str]]:
    urls: list[str] = []
    for src in (product, supplier):
        imgs = src.get("images") or []
        if isinstance(imgs, list):
            for img in imgs:
                if isinstance(img, str) and img:
                    urls.append(img)
                elif isinstance(img, dict):
                    u = str(img.get("url", "") or img.get("src", "") or "")
                    if u:
                        urls.append(u)
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append({"src": u})
    return out


def _build_variants(
    supplier: dict[str, Any],
    pricing: dict[str, Any],
    shopify_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    retail = pricing.get("retail_usd", 0)
    inv_mgmt = str(
        shopify_cfg.get("inventory_management", "shopify") or "shopify",
    )
    fulfillment = str(
        shopify_cfg.get("fulfillment_service", "manual") or "manual",
    )

    supplier_variants = supplier.get("variants") or []
    if not isinstance(supplier_variants, list):
        supplier_variants = []

    if supplier_variants:
        variants: list[dict[str, Any]] = []
        for sv in supplier_variants:
            if not isinstance(sv, dict):
                continue
            attrs = sv.get("attributes") or {}
            option_vals = list(attrs.values()) if isinstance(attrs, dict) else []
            variants.append({
                "price":                str(retail),
                "sku":                  str(sv.get("sku", "") or ""),
                "inventory_management": inv_mgmt,
                "fulfillment_service":  fulfillment,
                "option1":              str(option_vals[0]) if len(option_vals) > 0 else None,
                "option2":              str(option_vals[1]) if len(option_vals) > 1 else None,
                "option3":              str(option_vals[2]) if len(option_vals) > 2 else None,
            })
        return variants

    return [{
        "price":                str(retail),
        "sku":                  "",
        "inventory_management": inv_mgmt,
        "fulfillment_service":  fulfillment,
    }]


# ---------------------------------------------------------------------------
# Ads campaign draft
# ---------------------------------------------------------------------------


def _build_ads_campaign(
    *,
    winner: dict[str, Any],
    product: dict[str, Any],
    creative: dict[str, Any],
    ads_cfg: dict[str, Any],
) -> dict[str, Any]:
    platform = str(ads_cfg.get("platform", "meta") or "meta").lower()
    raw_budget = ads_cfg.get("daily_budget_usd")
    daily_budget = _to_float(raw_budget) if raw_budget is not None else _DEFAULT_DAILY_BUDGET
    pixel_id = str(ads_cfg.get("pixel_id", "") or "")
    pixel_events = ads_cfg.get("pixel_events") or ["Purchase", "AddToCart"]
    if not isinstance(pixel_events, list):
        pixel_events = ["Purchase", "AddToCart"]

    targeting = ads_cfg.get("targeting") or {}
    if not isinstance(targeting, dict):
        targeting = {}
    targeting.setdefault("countries", ["US"])
    targeting.setdefault("ages", [18, 55])

    title = str(product.get("title", "") or "")
    short_name = " ".join(title.split()[:4]) if title else "Product"
    campaign_name = f"{short_name} — Launch"

    creatives: list[dict[str, Any]] = []
    copy_variants = creative.get("copy_variants") or []
    if isinstance(copy_variants, list):
        for cv in copy_variants:
            if not isinstance(cv, dict):
                continue
            creatives.append({
                "angle":    cv.get("angle", ""),
                "headline": cv.get("headline", ""),
                "body":     cv.get("body", ""),
                "cta":      cv.get("cta", ""),
            })

    return {
        "platform":         platform,
        "campaign_name":    campaign_name,
        "daily_budget_usd": round(daily_budget, 2),
        "pixel_id":         pixel_id,
        "pixel_events":     pixel_events,
        "targeting":        targeting,
        "creatives":        creatives,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_float(val: Any) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _to_int(val: Any) -> int:
    if val is None:
        return 0
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return 0
