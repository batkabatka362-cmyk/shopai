"""Chain Transforms — smart data mapping between engines.

When Engine A outputs one format and Engine B expects another,
transforms bridge the gap. Common e-commerce field mappings built-in.
"""
from __future__ import annotations

import copy
from typing import Any

from utils.helpers import safe_float, safe_int

# ── Common field aliases ──
PRODUCT_ALIASES = {
    "selected_products": "products",
    "product_data": "products",
    "product_list": "products",
    "items": "products",
}

PRICE_ALIASES = {
    "unit_price": "price",
    "sale_price": "price",
    "retail_price": "price",
    "list_price": "price",
}

CUSTOMER_ALIASES = {
    "customer_data": "customers",
    "customer_list": "customers",
    "users": "customers",
    "audience": "customers",
}

ALL_ALIASES = {**PRODUCT_ALIASES, **PRICE_ALIASES, **CUSTOMER_ALIASES}


# ── Transform Functions ──

def auto_map_transform(output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Automatically map common field aliases between engines."""
    merged = copy.deepcopy(context)
    merged.update(output)

    # Apply field aliases
    for alias, canonical in ALL_ALIASES.items():
        if alias in merged and canonical not in merged:
            merged[canonical] = merged[alias]

    return merged


def product_to_pricing_transform(output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Transform product selection output to pricing engine input."""
    selected = output.get("selected_products", output.get("products", []))
    if not isinstance(selected, list):
        selected = []

    products = []
    for p in selected:
        if not isinstance(p, dict):
            continue
        products.append({
            "id": p.get("id", ""),
            "name": p.get("name", ""),
            "price": safe_float(p.get("price")),
            "cost": safe_float(p.get("cost")),
            "margin_pct": safe_float(p.get("margin_pct")),
            "total_score": safe_float(p.get("total_score")),
            "category": p.get("category", ""),
        })

    result = copy.deepcopy(context)
    result["products"] = products
    result["pricing_data"] = products
    return result


def pricing_to_content_transform(output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Transform pricing output to content generation input."""
    result = copy.deepcopy(context)

    # Pass pricing recommendations as content context
    recs = output.get("pricing_recommendations", output.get("recommendations", []))
    if isinstance(recs, list):
        result["pricing_context"] = recs

    # Pass optimized prices
    products = output.get("products", context.get("products", []))
    if isinstance(products, list):
        result["product_data"] = products

    return result


def content_to_seo_transform(output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Transform content generation output to SEO optimization input."""
    result = copy.deepcopy(context)

    content = output.get("content_elements", output.get("content", {}))
    if isinstance(content, dict):
        result["page_data"] = {
            "title": content.get("headline", content.get("title", "")),
            "body": content.get("body", content.get("description", "")),
            "keyword": content.get("keyword", context.get("keyword", "")),
        }

    bullets = output.get("bullet_points", [])
    if isinstance(bullets, list):
        result["keywords"] = [b.split()[0] for b in bullets if isinstance(b, str) and b][:5]

    return result


def customer_to_email_transform(output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Transform customer analysis output to email marketing input."""
    result = copy.deepcopy(context)

    # Extract segments for targeting
    segments = output.get("segments", output.get("customer_segments", []))
    if isinstance(segments, list):
        result["target_segments"] = segments

    # Extract at-risk customers for retention
    churn_risks = output.get("churn_risks", output.get("at_risk", []))
    if isinstance(churn_risks, list):
        result["at_risk_customers"] = churn_risks

    # Copy recommendations
    recs = output.get("recommendations", [])
    if isinstance(recs, list):
        result["campaign_recommendations"] = recs

    return result


def seo_to_campaign_transform(output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Transform SEO audit to campaign targeting input."""
    result = copy.deepcopy(context)

    # Extract keywords for ad targeting
    keywords = output.get("keywords", output.get("top_keywords", []))
    if isinstance(keywords, list):
        result["target_keywords"] = keywords

    # Extract page performance for ad copy
    audit = output.get("audit", output.get("seo_audit", {}))
    if isinstance(audit, dict):
        result["seo_score"] = safe_float(audit.get("score"))
        result["seo_issues"] = audit.get("issues", [])

    return result


# ── Transform Registry ──

CHAIN_TRANSFORMS = {
    ("market_research", "pricing"): product_to_pricing_transform,
    ("pricing", "product_description"): pricing_to_content_transform,
    ("pricing", "content_generation"): pricing_to_content_transform,
    ("product_description", "seo"): content_to_seo_transform,
    ("content_generation", "seo"): content_to_seo_transform,
    ("seo", "email_marketing"): seo_to_campaign_transform,
    ("seo", "social_media"): seo_to_campaign_transform,
    ("churn_prediction", "email_marketing"): customer_to_email_transform,
    ("customer_segmentation", "email_marketing"): customer_to_email_transform,
    ("customer_segmentation", "personalization"): customer_to_email_transform,
}


def get_transform(from_engine: str, to_engine: str):
    """Get the best transform for a pair of engines."""
    return CHAIN_TRANSFORMS.get((from_engine, to_engine), auto_map_transform)
