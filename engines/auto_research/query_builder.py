"""Query Builder — turns a research goal into optimised search queries.

Responsibility: expand a single goal into multiple search angles so the
Search Executor can cast a wide net.  Produces synonyms, question-form
variants, and related-term expansions.

Model note: would use **Qwen** for structured query generation.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from .types import ResearchGoal, SearchQuery


# ---------------------------------------------------------------------------
# Synonym / expansion tables (lightweight, no external dependency)
# ---------------------------------------------------------------------------

_EXPANSIONS: dict[str, list[str]] = {
    "best":      ["top", "leading", "highest rated"],
    "cheap":     ["affordable", "budget", "low cost"],
    "trend":     ["trending", "popular", "emerging"],
    "review":    ["comparison", "analysis", "evaluation"],
    "product":   ["item", "goods", "merchandise"],
    "market":    ["industry", "sector", "space"],
    "growth":    ["expansion", "increase", "surge"],
    "strategy":  ["approach", "method", "tactic"],
    "customer":  ["buyer", "consumer", "shopper"],
    "price":     ["cost", "pricing", "rate"],
}

_QUESTION_PREFIXES = [
    "What are the",
    "How does",
    "Why is",
    "What is the impact of",
]

_DEPTH_MULTIPLIER = {"shallow": 1, "standard": 2, "deep": 3}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_queries(goal: ResearchGoal) -> list[SearchQuery]:
    """Build a set of search queries from a research goal.

    Never mutates *goal* — works on a deep copy.
    Returns a deduplicated, priority-sorted list of ``SearchQuery`` dicts.
    """
    safe_goal: ResearchGoal = copy.deepcopy(goal)

    raw_query: str = safe_goal.get("query", "").strip()
    context: str = safe_goal.get("context", "").strip()
    depth: str = safe_goal.get("depth", "standard")
    max_sources: int = safe_goal.get("max_sources", 10)

    if not raw_query:
        return []

    multiplier: int = _DEPTH_MULTIPLIER.get(depth, 2)
    queries: list[SearchQuery] = []

    # 1. Original query (highest priority)
    queries.append(_make_query(raw_query, angle="original", priority=1.0))

    # 2. Context-enriched variant
    if context:
        enriched = f"{raw_query} {context}"
        queries.append(_make_query(enriched, angle="context_enriched", priority=0.95))

    # 3. Synonym expansions
    for synonym_query in _expand_synonyms(raw_query):
        queries.append(_make_query(synonym_query, angle="synonym", priority=0.80))

    # 4. Question-form variants
    for qf in _question_forms(raw_query):
        queries.append(_make_query(qf, angle="question_form", priority=0.70))

    # 5. Related-term expansions
    for related in _related_terms(raw_query):
        queries.append(_make_query(related, angle="related_term", priority=0.60))

    # 6. Narrowed sub-queries (split on commas / "and")
    sub_parts = re.split(r",|\band\b", raw_query)
    if len(sub_parts) > 1:
        for part in sub_parts:
            part = part.strip()
            if part:
                queries.append(_make_query(part, angle="sub_query", priority=0.55))

    # Deduplicate by normalised text
    queries = _deduplicate(queries)

    # Apply depth multiplier as a cap
    cap = min(max_sources * multiplier, len(queries))
    queries = sorted(queries, key=lambda q: q["priority"], reverse=True)[:cap]

    return queries


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_query(text: str, *, angle: str, priority: float) -> SearchQuery:
    return SearchQuery(text=text.strip(), angle=angle, priority=round(priority, 2))


def _expand_synonyms(query: str) -> list[str]:
    """Replace known words with synonyms, one substitution at a time."""
    results: list[str] = []
    lower = query.lower()
    for word, synonyms in _EXPANSIONS.items():
        if word in lower:
            for syn in synonyms:
                variant = re.sub(rf"\b{re.escape(word)}\b", syn, lower, count=1)
                results.append(variant)
    return results


def _question_forms(query: str) -> list[str]:
    """Turn a declarative query into question-form variants."""
    results: list[str] = []
    for prefix in _QUESTION_PREFIXES:
        results.append(f"{prefix} {query}?")
    return results


def _related_terms(query: str) -> list[str]:
    """Generate related-term expansions by appending domain modifiers."""
    modifiers = ["statistics", "case study", "2025", "comparison", "forecast"]
    return [f"{query} {mod}" for mod in modifiers]


def _deduplicate(queries: list[SearchQuery]) -> list[SearchQuery]:
    """Remove duplicate queries by normalised text hash."""
    seen: set[str] = set()
    unique: list[SearchQuery] = []
    for q in queries:
        key = _normalise(q["text"])
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())
