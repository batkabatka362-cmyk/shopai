"""Global Brain — knowledge structurer.

Structures extracted knowledge into categories: market, product,
customer, operational, financial. Assigns subcategories and formats
each item for storage.

Model note: Would use Qwen for structured knowledge formatting.
No connections to other modules — called only from flow.py.
"""
from __future__ import annotations

import time
from typing import Any


# ---------------------------------------------------------------------------
# Category detection keywords
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "market": [
        "market", "competition", "competitor", "industry", "trend",
        "demand", "supply", "share", "economy", "sector", "segment",
    ],
    "product": [
        "product", "inventory", "stock", "catalog", "sku", "item",
        "feature", "quality", "design", "bundle", "listing",
    ],
    "customer": [
        "customer", "user", "audience", "segment", "demographic",
        "retention", "churn", "loyalty", "satisfaction", "behavior",
        "young adult", "buyer", "shopper",
    ],
    "operational": [
        "shipping", "fulfillment", "logistics", "process", "efficiency",
        "workflow", "delivery", "warehouse", "automation", "support",
        "landing page", "bounce", "conversion", "funnel",
    ],
    "financial": [
        "revenue", "profit", "cost", "margin", "roi", "budget",
        "price", "pricing", "discount", "expense", "income", "sales",
    ],
}

_SUBCATEGORY_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "market": {
        "competition": ["competitor", "competition", "market share"],
        "trends": ["trend", "trending", "emerging", "growing"],
        "demand": ["demand", "supply", "seasonal", "spike"],
        "positioning": ["position", "brand", "awareness"],
    },
    "product": {
        "catalog": ["catalog", "listing", "sku", "item"],
        "quality": ["quality", "review", "rating", "defect"],
        "inventory": ["inventory", "stock", "out of stock", "restock"],
        "optimization": ["optimize", "improvement", "enhance"],
    },
    "customer": {
        "acquisition": ["acquisition", "new customer", "attract", "ad", "ads", "campaign"],
        "retention": ["retention", "churn", "loyalty", "repeat"],
        "segmentation": ["segment", "demographic", "age", "young", "audience"],
        "behavior": ["behavior", "pattern", "preference", "click"],
    },
    "operational": {
        "logistics": ["shipping", "delivery", "fulfillment", "warehouse"],
        "conversion": ["conversion", "convert", "bounce", "landing page", "funnel"],
        "automation": ["automation", "automate", "workflow"],
        "support": ["support", "ticket", "complaint"],
    },
    "financial": {
        "revenue": ["revenue", "sales", "income"],
        "costs": ["cost", "expense", "overhead"],
        "profitability": ["profit", "margin", "roi"],
        "pricing": ["price", "pricing", "discount"],
    },
}


def structure_knowledge(
    extracted_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Structure extracted knowledge into categorized items.

    Each item is assigned a category (market, product, customer,
    operational, financial) and a subcategory, then formatted
    for storage.

    Args:
        extracted_items: List of ExtractedKnowledge dicts.

    Returns:
        Structured dict with status and structured_items list.

    Model note: In production, Qwen would perform semantic
    categorization and structured formatting. Here we use
    keyword-based classification.
    """
    try:
        if not extracted_items:
            return {
                "status": "success",
                "structured_items": [],
                "error": None,
            }

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        structured: list[dict[str, Any]] = []

        for item in extracted_items:
            content = item.get("content", "")
            if not content:
                continue

            category = _classify_category(content)
            subcategory = _classify_subcategory(content, category)

            structured.append({
                "knowledge_id": item.get("knowledge_id", ""),
                "content": content,
                "knowledge_type": item.get("knowledge_type", "insight"),
                "category": category,
                "subcategory": subcategory,
                "source_engine": item.get("source_engine", "unknown"),
                "confidence": item.get("confidence", 0.5),
                "tags": item.get("tags", []),
                "timestamp": item.get("timestamp", timestamp),
                "structured_at": timestamp,
            })

        return {
            "status": "success",
            "structured_items": structured,
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "structured_items": [],
            "error": f"Knowledge structuring failed: {exc}",
        }


def _classify_category(content: str) -> str:
    """Classify content into a category using keyword matching.

    Model note: Qwen would perform semantic categorization here.
    """
    lower = content.lower()
    scores: dict[str, float] = {cat: 0.0 for cat in _CATEGORY_KEYWORDS}

    for category, keywords in _CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in lower:
                scores[category] += 1.0

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0.0:
        return "operational"  # default category
    return best


def _classify_subcategory(content: str, category: str) -> str:
    """Classify content into a subcategory within the given category.

    Model note: Qwen would perform semantic subcategorization here.
    """
    lower = content.lower()
    subcats = _SUBCATEGORY_KEYWORDS.get(category, {})

    best_sub = "general"
    best_score = 0.0

    for sub, keywords in subcats.items():
        score = sum(1.0 for kw in keywords if kw in lower)
        if score > best_score:
            best_score = score
            best_sub = sub

    return best_sub
