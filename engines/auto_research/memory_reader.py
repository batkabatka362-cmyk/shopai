"""Memory Reader — retrieves past research from the memory store.

Responsibility: query the memory store for previous research results,
supporting lookup by query similarity, recency, and confidence filters.
Enables the engine to avoid redundant research and build on prior work.

Model note: no model usage — pure retrieval + ranking.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from .types import MemoryRecord
from .memory_writer import get_store


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_related_research(
    query: str,
    *,
    min_confidence: float = 0.0,
    max_results: int = 5,
) -> list[MemoryRecord]:
    """Find past research records related to *query*.

    Returns records sorted by relevance (token overlap + confidence),
    filtered by the minimum confidence threshold.
    Never mutates the memory store — works on copies.
    """
    store = get_store()
    if not store or not query.strip():
        return []

    query_tokens = _tokenize(query)
    scored: list[tuple[float, MemoryRecord]] = []

    for record in store:
        record = copy.deepcopy(record)

        confidence = record.get("confidence", 0.0)
        if confidence < min_confidence:
            continue

        relevance = _compute_relevance(query_tokens, record)
        # Combined score: relevance (60%) + confidence (40%)
        combined = relevance * 0.6 + confidence * 0.4

        if combined > 0.05:
            scored.append((combined, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _, record in scored[:max_results]]


def get_all_records(*, min_confidence: float = 0.0) -> list[MemoryRecord]:
    """Return all memory records, optionally filtered by confidence.

    Returns deep copies so callers cannot corrupt the store.
    """
    store = get_store()
    results: list[MemoryRecord] = []

    for record in store:
        if record.get("confidence", 0.0) >= min_confidence:
            results.append(copy.deepcopy(record))

    return results


def has_recent_research(query: str, *, max_age_seconds: float = 3600.0) -> bool:
    """Check whether sufficiently recent research exists for this query.

    Uses token-overlap relevance — returns True if a record with
    relevance >= 0.5 exists within the age window.

    Note: age checking requires comparing ISO timestamps.  For simplicity
    this implementation checks only the relevance threshold; production
    would parse and compare datetime objects.
    """
    related = find_related_research(query, max_results=1)
    if not related:
        return False

    # Simple heuristic: if the top match has high overlap, consider it recent
    query_tokens = _tokenize(query)
    relevance = _compute_relevance(query_tokens, related[0])
    return relevance >= 0.5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """Normalize and tokenize text for comparison."""
    text = text.lower()
    tokens = re.findall(r"\b[a-z]{2,}\b", text)
    return set(tokens)


def _compute_relevance(query_tokens: set[str], record: MemoryRecord) -> float:
    """Compute relevance of a memory record to query tokens."""
    if not query_tokens:
        return 0.0

    # Build record token set from query, insight, and findings
    record_text = " ".join([
        record.get("query", ""),
        record.get("insight", ""),
        " ".join(record.get("key_findings", [])),
    ])
    record_tokens = _tokenize(record_text)

    if not record_tokens:
        return 0.0

    overlap = len(query_tokens & record_tokens)
    # Jaccard-like score weighted toward query coverage
    query_coverage = overlap / len(query_tokens)
    record_coverage = overlap / len(record_tokens)

    return query_coverage * 0.7 + record_coverage * 0.3
