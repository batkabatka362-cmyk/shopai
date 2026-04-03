"""Customer Service Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the customer service engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CustomerInfo(TypedDict, total=False):
    """Customer information provided with a service request."""
    customer_id: str
    name: str
    email: str
    loyalty_tier: str          # bronze, silver, gold, platinum
    lifetime_value: float
    contact_count_30d: int     # number of contacts in last 30 days


class CustomerServiceInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    message: str
    customer: CustomerInfo
    context: dict[str, Any]    # optional prior conversation context


# ---------------------------------------------------------------------------
# Intermediate types — intent classification
# ---------------------------------------------------------------------------

class ExtractedEntities(TypedDict, total=False):
    """Entities extracted from customer message."""
    order_ids: list[str]
    product_names: list[str]
    dates: list[str]
    dollar_amounts: list[float]


class IntentResult(TypedDict):
    """Result from intent_classifier."""
    status: str
    primary: str
    secondary: str | None
    confidence: float
    extracted_entities: ExtractedEntities


# ---------------------------------------------------------------------------
# Intermediate types — order lookup
# ---------------------------------------------------------------------------

class OrderDetails(TypedDict, total=False):
    """Order information returned by order_lookup."""
    id: str
    status: str
    tracking_number: str
    carrier: str
    estimated_delivery: str
    is_late: bool
    days_late: int
    items: list[dict[str, Any]]
    total: float


class OrderLookupResult(TypedDict):
    """Result from order_lookup."""
    status: str
    found: bool
    order: OrderDetails | None


# ---------------------------------------------------------------------------
# Intermediate types — knowledge search
# ---------------------------------------------------------------------------

class KnowledgeArticle(TypedDict):
    """Single FAQ/knowledge base article."""
    article_id: str
    title: str
    snippet: str
    relevance_score: float


class KnowledgeSearchResult(TypedDict):
    """Result from knowledge_search."""
    status: str
    results: list[KnowledgeArticle]


# ---------------------------------------------------------------------------
# Intermediate types — response builder
# ---------------------------------------------------------------------------

class SuggestedAction(TypedDict, total=False):
    """Action suggested to the customer."""
    action: str
    label: str
    url: str
    trigger: str


class ResponseResult(TypedDict):
    """Result from response_builder."""
    status: str
    message: str
    tone: str
    suggested_actions: list[SuggestedAction]


# ---------------------------------------------------------------------------
# Intermediate types — escalation routing
# ---------------------------------------------------------------------------

class EscalationResult(TypedDict):
    """Result from escalation_router."""
    status: str
    needed: bool
    reason: str | None
    assigned_team: str | None
    priority: str | None


# ---------------------------------------------------------------------------
# Intermediate types — interaction history
# ---------------------------------------------------------------------------

class InteractionRecord(TypedDict, total=False):
    """A single past interaction record."""
    record_id: str
    timestamp: str
    customer_id: str
    intent: str
    resolution: str
    satisfaction: str


class InteractionHistoryResult(TypedDict):
    """Result from memory_reader."""
    status: str
    records: list[InteractionRecord]
    count: int


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class CustomerServiceData(TypedDict):
    """The 'data' block of the engine output."""
    intent: IntentResult
    order_info: OrderLookupResult | None
    response: ResponseResult
    escalation: EscalationResult


class CustomerServiceMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class CustomerServiceOutput(TypedDict):
    """Final output of the customer service engine."""
    status: str
    data: CustomerServiceData | None
    meta: CustomerServiceMeta
    error: str | None
