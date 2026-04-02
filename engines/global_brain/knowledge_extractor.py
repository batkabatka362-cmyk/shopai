"""Global Brain — knowledge extractor.

Extracts knowledge items from ingested raw data: facts, insights, rules,
and correlations. Classifies each item by type and assigns confidence.

Model note: Would use Mistral for knowledge extraction and classification.
No connections to other modules — called only from flow.py.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any


# Keywords that signal different knowledge types
_FACT_SIGNALS = [
    "is", "are", "was", "were", "equals", "amounts to", "costs",
    "measures", "totals", "reaches", "stands at",
]
_RULE_SIGNALS = [
    "should", "must", "always", "never", "require", "if then",
    "when", "avoid", "ensure", "limit", "rule",
]
_CORRELATION_SIGNALS = [
    "correlat", "leads to", "causes", "results in", "increases",
    "decreases", "affects", "impacts", "drives", "linked to",
    "associated with", "converts", "better than", "worse than",
]
_INSIGHT_SIGNALS = [
    "suggests", "indicates", "trend", "pattern", "spike", "drop",
    "opportunity", "risk", "potential", "growth", "decline",
]


def extract_knowledge(
    raw_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Extract structured knowledge from raw ingested items.

    Each raw item is classified into a knowledge type (fact, insight,
    rule, correlation) and assigned a confidence score.

    Args:
        raw_items: List of RawKnowledge dicts from the data ingestor.

    Returns:
        Structured dict with status and extracted_items list.

    Model note: In production, Mistral would classify each item and
    extract deeper relationships. Here we use keyword-based heuristics.
    """
    try:
        if not raw_items:
            return {
                "status": "success",
                "extracted_items": [],
                "error": None,
            }

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        extracted: list[dict[str, Any]] = []

        for item in raw_items:
            content = item.get("content", "")
            if not content or not isinstance(content, str):
                continue

            knowledge_type = _classify_knowledge_type(content)
            confidence = _compute_confidence(content, item)
            tags = _extract_tags(content, item)
            knowledge_id = _generate_id(content, item.get("source_engine", ""))

            extracted.append({
                "knowledge_id": knowledge_id,
                "content": content,
                "knowledge_type": knowledge_type,
                "source_engine": item.get("source_engine", "unknown"),
                "confidence": round(confidence, 4),
                "tags": tags,
                "timestamp": timestamp,
                "raw_source": item.get("category", "unknown"),
            })

        return {
            "status": "success",
            "extracted_items": extracted,
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "extracted_items": [],
            "error": f"Knowledge extraction failed: {exc}",
        }


def _classify_knowledge_type(content: str) -> str:
    """Classify content into a knowledge type using keyword heuristics.

    Model note: Mistral would perform semantic classification here.
    """
    lower = content.lower()

    # Score each type
    scores = {
        "correlation": 0.0,
        "rule": 0.0,
        "fact": 0.0,
        "insight": 0.0,
    }

    for signal in _CORRELATION_SIGNALS:
        if signal in lower:
            scores["correlation"] += 1.0

    for signal in _RULE_SIGNALS:
        if signal in lower:
            scores["rule"] += 1.0

    for signal in _FACT_SIGNALS:
        if signal in lower:
            scores["fact"] += 0.8

    for signal in _INSIGHT_SIGNALS:
        if signal in lower:
            scores["insight"] += 0.9

    # Pick highest scoring type, default to insight
    best_type = max(scores, key=lambda k: scores[k])
    if scores[best_type] == 0.0:
        return "insight"
    return best_type


def _compute_confidence(content: str, item: dict[str, Any]) -> float:
    """Compute a confidence score for a knowledge item.

    Model note: Mistral would assess factual reliability here.
    """
    confidence = 0.5

    # Longer content tends to be more specific
    word_count = len(content.split())
    if word_count >= 10:
        confidence += 0.1
    if word_count >= 20:
        confidence += 0.05

    # Numeric content is often more concrete
    if any(ch.isdigit() for ch in content):
        confidence += 0.1

    # Specific percentage or multiplier references
    if "%" in content or "x " in content.lower():
        confidence += 0.1

    # Source category affects confidence
    category = item.get("category", "")
    if category == "pattern":
        confidence += 0.05
    elif category == "error":
        confidence += 0.1  # errors are usually factual
    elif category == "metric":
        confidence += 0.15

    return min(confidence, 1.0)


def _extract_tags(content: str, item: dict[str, Any]) -> list[str]:
    """Extract descriptive tags from content.

    Model note: Mistral would do semantic tagging here.
    """
    tags: list[str] = []
    lower = content.lower()

    # Domain tags
    tag_map = {
        "marketing": ["ad", "ads", "campaign", "marketing", "social media",
                       "instagram", "facebook", "email", "seo"],
        "pricing": ["price", "pricing", "cost", "discount", "margin"],
        "conversion": ["conversion", "convert", "bounce", "landing page", "funnel"],
        "customer": ["customer", "user", "audience", "segment", "demographic",
                      "young adult", "retention"],
        "product": ["product", "inventory", "stock", "catalog", "sku"],
        "revenue": ["revenue", "sales", "profit", "roi", "income"],
        "seasonal": ["season", "seasonal", "weekend", "holiday", "summer", "winter"],
        "competition": ["competitor", "competition", "market share"],
    }

    for tag, keywords in tag_map.items():
        for keyword in keywords:
            if keyword in lower:
                tags.append(tag)
                break

    # Add source category as tag
    category = item.get("category", "")
    if category:
        tags.append(category)

    # Add source engine as tag
    source = item.get("source_engine", "")
    if source:
        tags.append(source)

    return list(set(tags))


def _generate_id(content: str, source: str) -> str:
    """Generate a deterministic knowledge ID from content and source."""
    raw = f"{source}:{content}"
    return "k_" + hashlib.sha256(raw.encode()).hexdigest()[:12]
