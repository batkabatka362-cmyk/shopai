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
    """Customer profile information."""
    customer_id: str
    name: str
    email: str
    loyalty_tier: str          # bronze, silver, gold, platinum
    lifetime_value: float
    open_tickets: int
    last_contact_date: str


class CustomerServiceInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    message: str
    customer: CustomerInfo
    channel: str               # chat, email, phone, social
    session_id: str


# ---------------------------------------------------------------------------
# Intermediate types — intent classification
# ---------------------------------------------------------------------------

class ExtractedEntities(TypedDict, total=False):
    """Entities extracted from the customer message."""
    order_ids: list[str]
    product_names: list[str]
    dates: list[str]
    amounts: list[float]


class IntentResult(TypedDict):
    """Result of intent classification."""
    primary: str
    secondary: str | None
    confidence: float
    extracted_entities: ExtractedEntities


# ---------------------------------------------------------------------------
# Intermediate types — order lookup
# ---------------------------------------------------------------------------

class OrderInfo(TypedDict, total=False):
    """Order information from order lookup."""
    id: str
    status: str
    tracking_number: str
    carrier: str
    estimated_delivery: str
    is_late: bool
    days_late: int


class OrderLookupResult(TypedDict):
    """Result of order lookup."""
    found: bool
    order: OrderInfo | None


# ---------------------------------------------------------------------------
# Intermediate types — knowledge search
# ---------------------------------------------------------------------------

class KnowledgeArticle(TypedDict):
    """A single knowledge-base article result."""
    article_id: str
    title: str
    snippet: str
    relevance_score: float


# ---------------------------------------------------------------------------
# Intermediate types — response builder
# ---------------------------------------------------------------------------

class SuggestedAction(TypedDict, total=False):
    """A single suggested action for the customer."""
    action: str
    label: str
    url: str
    trigger: str


class ResponseResult(TypedDict):
    """Result of response building."""
    message: str
    tone: str
    suggested_actions: list[SuggestedAction]


# ---------------------------------------------------------------------------
# Intermediate types — escalation router
# ---------------------------------------------------------------------------

class EscalationResult(TypedDict):
    """Result of escalation routing."""
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
    channel: str
    resolution: str
    escalated: bool


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class CustomerServiceData(TypedDict):
    """The 'data' block of the engine output."""
    intent: IntentResult
    order_info: OrderLookupResult | None
    knowledge_results: list[KnowledgeArticle]
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
