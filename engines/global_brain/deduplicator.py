"""Global Brain — deduplicator.

Detects and removes duplicate and near-duplicate knowledge items
using text similarity. Compares content strings using Jaccard
similarity on word n-grams.

No connections to other modules — called only from flow.py.
"""
from __future__ import annotations

from typing import Any


# Similarity threshold above which two items are considered duplicates
_DUPLICATE_THRESHOLD = 0.70
# Similarity threshold for near-duplicates (merged rather than dropped)
_NEAR_DUPLICATE_THRESHOLD = 0.50


def deduplicate_knowledge(
    structured_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Remove duplicate and near-duplicate knowledge items.

    Uses Jaccard similarity on word 2-grams (shingles) to detect
    duplicates. Exact duplicates (same content) are removed. Near-
    duplicates (high similarity) keep the higher-confidence version.

    Args:
        structured_items: List of StructuredKnowledge dicts.

    Returns:
        Structured dict with status, unique_items, and dedup stats.
    """
    try:
        if not structured_items:
            return {
                "status": "success",
                "unique_items": [],
                "duplicates_removed": 0,
                "near_duplicates_merged": 0,
                "error": None,
            }

        # ---- Step 1: Exact content dedup ----
        seen_content: dict[str, int] = {}
        after_exact: list[dict[str, Any]] = []
        exact_removed = 0

        for item in structured_items:
            content_key = item.get("content", "").strip().lower()
            if content_key in seen_content:
                # Keep the one with higher confidence
                existing_idx = seen_content[content_key]
                existing = after_exact[existing_idx]
                if item.get("confidence", 0.0) > existing.get("confidence", 0.0):
                    after_exact[existing_idx] = item
                exact_removed += 1
            else:
                seen_content[content_key] = len(after_exact)
                after_exact.append(item)

        # ---- Step 2: Near-duplicate detection via shingle similarity ----
        shingle_sets = [_compute_shingles(it.get("content", "")) for it in after_exact]
        keep_flags = [True] * len(after_exact)
        near_merged = 0

        for i in range(len(after_exact)):
            if not keep_flags[i]:
                continue
            for j in range(i + 1, len(after_exact)):
                if not keep_flags[j]:
                    continue
                sim = _jaccard_similarity(shingle_sets[i], shingle_sets[j])
                if sim >= _DUPLICATE_THRESHOLD:
                    # Near-exact duplicate: keep higher confidence
                    if after_exact[j].get("confidence", 0.0) > after_exact[i].get("confidence", 0.0):
                        keep_flags[i] = False
                        near_merged += 1
                        break  # i is dropped, stop comparing i
                    else:
                        keep_flags[j] = False
                        near_merged += 1
                elif sim >= _NEAR_DUPLICATE_THRESHOLD:
                    # Near-duplicate: merge tags, keep higher confidence one
                    winner_idx = i if after_exact[i].get("confidence", 0.0) >= after_exact[j].get("confidence", 0.0) else j
                    loser_idx = j if winner_idx == i else i
                    # Merge tags
                    winner_tags = set(after_exact[winner_idx].get("tags", []))
                    loser_tags = set(after_exact[loser_idx].get("tags", []))
                    after_exact[winner_idx]["tags"] = list(winner_tags | loser_tags)
                    keep_flags[loser_idx] = False
                    near_merged += 1
                    if loser_idx == i:
                        break

        unique_items = [it for it, keep in zip(after_exact, keep_flags) if keep]

        return {
            "status": "success",
            "unique_items": unique_items,
            "duplicates_removed": exact_removed,
            "near_duplicates_merged": near_merged,
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "unique_items": list(structured_items),
            "duplicates_removed": 0,
            "near_duplicates_merged": 0,
            "error": f"Deduplication failed (items preserved): {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_shingles(text: str, n: int = 2) -> set[str]:
    """Compute character n-gram shingles from lowercased text.

    Using word-level bigrams for better semantic similarity.
    """
    words = text.lower().split()
    if len(words) < n:
        return set(words)
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0
