"""Autonomous Control Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the autonomous control engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ActionItem(TypedDict, total=False):
    """Single action to evaluate."""
    id: str
    type: str
    target: str
    params: dict[str, Any]
    risk_level: str


class SafetyLimits(TypedDict, total=False):
    """Safety boundary configuration."""
    max_actions_per_minute: int
    max_cost_per_action: float
    blocked_targets: list[str]
    require_approval_above: float


class ResourceBudget(TypedDict, total=False):
    """Resource budget constraints."""
    max_cpu_pct: float
    max_memory_mb: int
    max_api_calls: int
    max_cost_usd: float


class AutonomousControlInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    actions: list[ActionItem]
    safety_limits: SafetyLimits
    resource_budget: ResourceBudget


# ---------------------------------------------------------------------------
# Intermediate types — safety check
# ---------------------------------------------------------------------------

class SafetyCheckResult(TypedDict):
    """Result of safety check for a single action."""
    action_id: str
    action_type: str
    safe: bool
    violations: list[str]
    risk_score: float


# ---------------------------------------------------------------------------
# Intermediate types — resource monitoring
# ---------------------------------------------------------------------------

class ResourceUsage(TypedDict):
    """Current resource usage snapshot."""
    cpu_pct: float
    memory_mb: int
    api_calls_used: int
    cost_used_usd: float
    within_budget: bool
    headroom_pct: float


# ---------------------------------------------------------------------------
# Intermediate types — rollback
# ---------------------------------------------------------------------------

class RollbackPoint(TypedDict):
    """A rollback checkpoint."""
    action_id: str
    checkpoint_id: str
    reversible: bool
    rollback_steps: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — governor
# ---------------------------------------------------------------------------

class GovernorDecision(TypedDict):
    """Governor rate/scope decision."""
    action_id: str
    allowed: bool
    throttled: bool
    delay_seconds: float
    reason: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ApprovedAction(TypedDict):
    """An action that passed all checks."""
    action_id: str
    action_type: str
    safe: bool
    throttled: bool


class BlockedAction(TypedDict):
    """An action that was blocked."""
    action_id: str
    action_type: str
    reason: str
    violations: list[str]


class AutonomousControlData(TypedDict):
    """The 'data' block of the engine output."""
    approved: list[ApprovedAction]
    blocked: list[BlockedAction]
    resource_usage: ResourceUsage
    rollback_points: list[RollbackPoint]


class AutonomousControlMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class AutonomousControlOutput(TypedDict):
    """Final output of the autonomous control engine."""
    status: str
    data: AutonomousControlData | None
    meta: AutonomousControlMeta
    error: str | None
