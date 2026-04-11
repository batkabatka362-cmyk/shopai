"""Webhook Handler Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the webhook handler engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class WebhookInfo(TypedDict, total=False):
    """Webhook metadata from the incoming request."""
    topic: str
    shop_domain: str
    hmac_header: str
    webhook_id: str


class WebhookInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    webhook: WebhookInfo
    raw_payload: dict[str, Any]
    shared_secret: str


class WebhookInput(TypedDict, total=False):
    """Full engine input."""
    status: str
    data: WebhookInputData
    meta: dict[str, Any]
    error: str | None


# ---------------------------------------------------------------------------
# Intermediate types — signature verification
# ---------------------------------------------------------------------------

class VerificationResult(TypedDict):
    """Result from signature_verifier."""
    signature_valid: bool
    hmac_computed: str


# ---------------------------------------------------------------------------
# Intermediate types — event classification
# ---------------------------------------------------------------------------

class EventInfo(TypedDict):
    """Classified event from event_classifier."""
    category: str
    action: str
    priority: str
    topic: str


# ---------------------------------------------------------------------------
# Intermediate types — payload parsing
# ---------------------------------------------------------------------------

class ParsedPayload(TypedDict):
    """Parsed and normalized payload from payload_parser."""
    entity_type: str
    entity_id: str
    normalized: dict[str, Any]


# ---------------------------------------------------------------------------
# Intermediate types — routing
# ---------------------------------------------------------------------------

class RouteEntry(TypedDict):
    """Single route target from engine_router."""
    engine: str
    action: str
    priority: str
    payload_key: str


class RouteDecision(TypedDict):
    """Routing decision from engine_router."""
    routes: list[RouteEntry]


# ---------------------------------------------------------------------------
# Intermediate types — execution tracking
# ---------------------------------------------------------------------------

class DispatchRecord(TypedDict):
    """Single dispatch record from execution_tracker."""
    engine: str
    action: str
    priority: str
    webhook_id: str
    dispatch_status: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class WebhookVerification(TypedDict):
    """Verification block in engine output."""
    signature_valid: bool
    hmac_match: bool


class WebhookEvent(TypedDict):
    """Event block in engine output."""
    topic: str
    category: str
    action: str
    priority: str


class WebhookRouting(TypedDict):
    """Routing block in engine output."""
    target_engines: list[RouteEntry]


class WebhookExecution(TypedDict):
    """Execution block in engine output."""
    dispatched_count: int
    dispatch_status: list[DispatchRecord]


class WebhookOutputData(TypedDict):
    """The 'data' block of the engine output."""
    webhook_id: str
    verification: WebhookVerification
    event: WebhookEvent
    parsed_payload: ParsedPayload
    routing: WebhookRouting
    execution: WebhookExecution


class WebhookMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class WebhookOutput(TypedDict):
    """Final output of the webhook handler engine."""
    status: str
    data: WebhookOutputData | None
    meta: WebhookMeta
    error: str | None
