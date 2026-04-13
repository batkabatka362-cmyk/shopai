"""Global Brain — all TypedDicts and type aliases.

Single source of truth for every data shape in the global brain engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Engine output (raw input from other engines)
# ---------------------------------------------------------------------------

class EngineOutput(TypedDict, total=False):
    """Raw output from any engine, arriving as input to Global Brain."""
    source_engine: str
    timestamp: str
    data: dict[str, Any]


# ---------------------------------------------------------------------------
# Knowledge types
# ---------------------------------------------------------------------------

class RawKnowledge(TypedDict, total=False):
    """A single raw knowledge item before extraction."""
    source_engine: str
    content: str
    category: str           # "insight", "error", "pattern", "metric"
    timestamp: str
    raw_data: dict[str, Any]


class ExtractedKnowledge(TypedDict, total=False):
    """Knowledge item after extraction by Mistral."""
    knowledge_id: str
    content: str
    knowledge_type: str     # "fact", "insight", "rule", "correlation"
    source_engine: str
    confidence: float       # 0.0–1.0
    tags: list[str]
    timestamp: str
    raw_source: str


# ---------------------------------------------------------------------------
# Pattern types
# ---------------------------------------------------------------------------

class Pattern(TypedDict, total=False):
    """A detected pattern across multiple knowledge items."""
    pattern_id: str
    description: str
    pattern_type: str       # "recurring", "trend", "anomaly", "correlation"
    supporting_items: list[str]   # knowledge_ids that support this pattern
    frequency: int
    confidence: float
    first_seen: str
    last_seen: str


# ---------------------------------------------------------------------------
# Structured knowledge
# ---------------------------------------------------------------------------

class StructuredKnowledge(TypedDict, total=False):
    """Knowledge structured into categories by Qwen."""
    knowledge_id: str
    content: str
    knowledge_type: str
    category: str           # "market", "product", "customer", "operational", "financial"
    subcategory: str
    source_engine: str
    confidence: float
    tags: list[str]
    timestamp: str
    structured_at: str


# ---------------------------------------------------------------------------
# Vector store types
# ---------------------------------------------------------------------------

class VectorEntry(TypedDict, total=False):
    """An entry in the vector store."""
    entry_id: str
    content: str
    vector: list[float]
    metadata: dict[str, Any]
    timestamp: str


# ---------------------------------------------------------------------------
# Memory types
# ---------------------------------------------------------------------------

class MemoryEntry(TypedDict, total=False):
    """A record in the memory store."""
    entry_id: str
    knowledge: StructuredKnowledge
    score: float
    stored_at: str
    access_count: int
    last_accessed: str


# ---------------------------------------------------------------------------
# Retrieval types
# ---------------------------------------------------------------------------

class RetrievalResult(TypedDict, total=False):
    """A single result from the retriever."""
    entry_id: str
    content: str
    category: str
    relevance_score: float
    source_engine: str
    timestamp: str
    knowledge_type: str


class ContextPayload(TypedDict, total=False):
    """Context payload delivered to requesting engines."""
    context: list[RetrievalResult]
    related_patterns: list[Pattern]
    recommendations: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class GlobalBrainOutput(TypedDict):
    """Final output of the global brain engine."""
    status: str
    data: dict[str, Any] | None
    meta: dict[str, Any]
    error: str | None
