"""Chatbot Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the chatbot engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CustomerInfo(TypedDict, total=False):
    """Customer interacting with chatbot."""
    id: str
    name: str
    email: str
    tier: str
    order_history: list[dict[str, Any]]


class ConversationMessage(TypedDict, total=False):
    """Single message in conversation history."""
    role: str
    content: str
    timestamp: str


class ChatbotInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    message: str
    customer: CustomerInfo
    conversation_history: list[ConversationMessage]
    context: dict[str, Any]


# ---------------------------------------------------------------------------
# Intermediate types — intent routing
# ---------------------------------------------------------------------------

class IntentResult(TypedDict):
    """Intent classification from intent_router."""
    intent: str
    confidence: float
    entities: dict[str, list[str]]
    sub_intent: str


# ---------------------------------------------------------------------------
# Intermediate types — response generation
# ---------------------------------------------------------------------------

class GeneratedResponse(TypedDict):
    """Generated response from response_generator."""
    response: str
    suggested_actions: list[str]
    references: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — conversation management
# ---------------------------------------------------------------------------

class ConversationState(TypedDict):
    """Conversation state from conversation_manager."""
    turn_count: int
    topic: str
    resolved: bool
    context_summary: str


# ---------------------------------------------------------------------------
# Intermediate types — escalation
# ---------------------------------------------------------------------------

class EscalationDecision(TypedDict):
    """Escalation decision from escalation_handler."""
    escalate: bool
    reason: str
    priority: str
    department: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ChatbotOutputData(TypedDict):
    """The 'data' block of the engine output."""
    response: str
    intent: str
    confidence: float
    suggested_actions: list[str]
    escalate: bool
    conversation_state: ConversationState


class ChatbotMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ChatbotOutput(TypedDict):
    """Final output of the chatbot engine."""
    status: str
    data: ChatbotOutputData | None
    meta: ChatbotMeta
    error: str | None
