"""Global Brain — pattern aggregator.

Aggregates patterns across multiple knowledge items, finding recurring
themes and trends. Groups similar knowledge items and detects patterns
that span multiple sources.

Model note: Would use Mistral for semantic pattern detection.
No connections to other modules — called only from flow.py.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any


def aggregate_patterns(
    extracted_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate patterns across extracted knowledge items.

    Identifies recurring themes, trends, and correlations that appear
    across multiple knowledge items from potentially different engines.

    Args:
        extracted_items: List of ExtractedKnowledge dicts.

    Returns:
        Structured dict with status and patterns list.

    Model note: In production, Mistral would perform semantic clustering
    and cross-item relationship detection. Here we use tag-based and
    keyword-based grouping.
    """
    try:
        if not extracted_items:
            return {
                "status": "success",
                "patterns": [],
                "error": None,
            }

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        patterns: list[dict[str, Any]] = []

        # --- Strategy 1: Tag co-occurrence patterns ---
        tag_groups = _group_by_tags(extracted_items)
        for tag, group_items in tag_groups.items():
            if len(group_items) < 2:
                continue
            pattern_id = _make_pattern_id("tag", tag)
            ids = [it.get("knowledge_id", "") for it in group_items]
            sources = list({it.get("source_engine", "") for it in group_items})
            confidence = min(0.9, 0.4 + 0.1 * len(group_items))

            description = (
                f"Recurring theme '{tag}' detected across "
                f"{len(group_items)} knowledge items from {len(sources)} source(s)"
            )
            patterns.append({
                "pattern_id": pattern_id,
                "description": description,
                "pattern_type": "recurring",
                "supporting_items": ids,
                "frequency": len(group_items),
                "confidence": round(confidence, 4),
                "first_seen": timestamp,
                "last_seen": timestamp,
            })

        # --- Strategy 2: Cross-engine patterns ---
        engine_groups = _group_by_source(extracted_items)
        if len(engine_groups) >= 2:
            cross_patterns = _detect_cross_engine_patterns(engine_groups, timestamp)
            patterns.extend(cross_patterns)

        # --- Strategy 3: Knowledge-type concentration ---
        type_groups = _group_by_type(extracted_items)
        for ktype, group_items in type_groups.items():
            if len(group_items) < 2:
                continue
            pattern_id = _make_pattern_id("type_concentration", ktype)
            ids = [it.get("knowledge_id", "") for it in group_items]
            confidence = min(0.85, 0.3 + 0.1 * len(group_items))

            description = (
                f"Concentration of '{ktype}' knowledge: "
                f"{len(group_items)} items detected"
            )
            patterns.append({
                "pattern_id": pattern_id,
                "description": description,
                "pattern_type": "trend",
                "supporting_items": ids,
                "frequency": len(group_items),
                "confidence": round(confidence, 4),
                "first_seen": timestamp,
                "last_seen": timestamp,
            })

        # --- Strategy 4: Content-similarity patterns ---
        sim_patterns = _detect_content_similarity_patterns(extracted_items, timestamp)
        patterns.extend(sim_patterns)

        return {
            "status": "success",
            "patterns": patterns,
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "patterns": [],
            "error": f"Pattern aggregation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Grouping helpers
# ---------------------------------------------------------------------------

def _group_by_tags(
    items: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group knowledge items by their tags."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        for tag in item.get("tags", []):
            # Skip engine names and raw categories as grouping keys
            if tag in ("insight", "error", "pattern", "metric"):
                continue
            groups.setdefault(tag, []).append(item)
    return groups


def _group_by_source(
    items: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group knowledge items by source engine."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        source = item.get("source_engine", "unknown")
        groups.setdefault(source, []).append(item)
    return groups


def _group_by_type(
    items: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group knowledge items by knowledge type."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        ktype = item.get("knowledge_type", "unknown")
        groups.setdefault(ktype, []).append(item)
    return groups


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------

def _detect_cross_engine_patterns(
    engine_groups: dict[str, list[dict[str, Any]]],
    timestamp: str,
) -> list[dict[str, Any]]:
    """Detect patterns that span multiple engines.

    Model note: Mistral would do semantic matching across engines.
    Here we compare tag overlap.
    """
    patterns: list[dict[str, Any]] = []
    engines = list(engine_groups.keys())

    for i in range(len(engines)):
        for j in range(i + 1, len(engines)):
            eng_a, eng_b = engines[i], engines[j]
            items_a = engine_groups[eng_a]
            items_b = engine_groups[eng_b]

            tags_a = set()
            for it in items_a:
                tags_a.update(it.get("tags", []))
            tags_b = set()
            for it in items_b:
                tags_b.update(it.get("tags", []))

            # Remove engine name tags and raw categories
            strip_tags = {eng_a, eng_b, "insight", "error", "pattern", "metric"}
            tags_a -= strip_tags
            tags_b -= strip_tags

            overlap = tags_a & tags_b
            if not overlap:
                continue

            all_ids = (
                [it.get("knowledge_id", "") for it in items_a]
                + [it.get("knowledge_id", "") for it in items_b]
            )
            confidence = min(0.85, 0.3 + 0.1 * len(overlap))
            description = (
                f"Cross-engine pattern between '{eng_a}' and '{eng_b}': "
                f"shared themes {sorted(overlap)}"
            )
            pattern_id = _make_pattern_id("cross", f"{eng_a}_{eng_b}")
            patterns.append({
                "pattern_id": pattern_id,
                "description": description,
                "pattern_type": "correlation",
                "supporting_items": all_ids,
                "frequency": len(all_ids),
                "confidence": round(confidence, 4),
                "first_seen": timestamp,
                "last_seen": timestamp,
            })

    return patterns


def _detect_content_similarity_patterns(
    items: list[dict[str, Any]],
    timestamp: str,
) -> list[dict[str, Any]]:
    """Detect patterns based on content word overlap.

    Model note: Mistral would use embeddings for semantic similarity.
    Here we use Jaccard similarity on word sets.
    """
    patterns: list[dict[str, Any]] = []
    n = len(items)
    if n < 2:
        return patterns

    # Precompute word sets
    word_sets: list[set[str]] = []
    for item in items:
        words = set(item.get("content", "").lower().split())
        # Remove very common words
        words -= {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "and", "or", "but", "not", "this", "that", "it", "as",
        }
        word_sets.append(words)

    # Find pairs with high Jaccard similarity
    seen_pairs: set[tuple[str, str]] = set()
    for i in range(min(n, 50)):  # cap to avoid O(n^2) blow-up
        for j in range(i + 1, min(n, 50)):
            if not word_sets[i] or not word_sets[j]:
                continue
            intersection = word_sets[i] & word_sets[j]
            union = word_sets[i] | word_sets[j]
            jaccard = len(intersection) / len(union) if union else 0.0

            if jaccard < 0.3:
                continue

            id_i = items[i].get("knowledge_id", str(i))
            id_j = items[j].get("knowledge_id", str(j))
            pair_key = (min(id_i, id_j), max(id_i, id_j))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            shared_words = sorted(intersection)[:5]
            description = (
                f"Content similarity detected between items "
                f"(shared terms: {shared_words})"
            )
            pattern_id = _make_pattern_id("similarity", f"{id_i}_{id_j}")
            patterns.append({
                "pattern_id": pattern_id,
                "description": description,
                "pattern_type": "correlation",
                "supporting_items": [id_i, id_j],
                "frequency": 2,
                "confidence": round(min(0.9, jaccard + 0.2), 4),
                "first_seen": timestamp,
                "last_seen": timestamp,
            })

    return patterns


def _make_pattern_id(prefix: str, key: str) -> str:
    """Generate a deterministic pattern ID."""
    raw = f"{prefix}:{key}"
    return "p_" + hashlib.sha256(raw.encode()).hexdigest()[:12]
