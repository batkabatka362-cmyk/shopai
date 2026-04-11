"""Browse Recovery Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the browse recovery engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class SessionRecord(TypedDict, total=False):
    """Single browse session record."""
    user_id: str
    pages_viewed: list[str]
    products_viewed: list[str]
    duration: float
    cart_items: list[str]


class BrowseRecoveryInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    sessions: list[SessionRecord]
    products: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Intermediate types — session analysis
# ---------------------------------------------------------------------------

class AnalyzedSession(TypedDict):
    """Per-session analysis from session_analyzer."""
    user_id: str
    pages_viewed_count: int
    products_viewed_count: int
    duration: float
    cart_items_count: int
    is_browse_abandon: bool
    engagement_level: str


# ---------------------------------------------------------------------------
# Intermediate types — intent scoring
# ---------------------------------------------------------------------------

class IntentScore(TypedDict):
    """Per-user intent score from intent_scorer."""
    user_id: str
    intent_score: float
    signals: list[str]
    purchase_likelihood: str


# ---------------------------------------------------------------------------
# Intermediate types — offer building
# ---------------------------------------------------------------------------

class RecoveryOffer(TypedDict):
    """Per-user recovery offer from offer_builder."""
    user_id: str
    offer_type: str
    discount_pct: float
    featured_products: list[str]
    message: str
    urgency: str


# ---------------------------------------------------------------------------
# Intermediate types — sequence planning
# ---------------------------------------------------------------------------

class RecoverySequence(TypedDict):
    """Per-user recovery sequence from sequence_planner."""
    user_id: str
    steps: list[dict[str, Any]]
    total_touches: int
    duration_days: int
    channel_mix: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class RecoveryTarget(TypedDict):
    """Single recovery target in engine output."""
    user_id: str
    intent_score: float
    viewed_products: list[str]
    recommended_offer: RecoveryOffer
    sequence: RecoverySequence


class BrowseRecoveryData(TypedDict):
    """The 'data' block of the engine output."""
    recovery_targets: list[RecoveryTarget]
    total_recoverable: int
    estimated_revenue: float


class BrowseRecoveryMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class BrowseRecoveryOutput(TypedDict):
    """Final output of the browse recovery engine."""
    status: str
    data: BrowseRecoveryData | None
    meta: BrowseRecoveryMeta
    error: str | None
