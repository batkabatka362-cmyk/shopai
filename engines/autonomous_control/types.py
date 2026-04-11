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
    """Single action to be evaluated for safety."""
    id: str
    type: str
    target: str
    params: dict[str, Any]


class SafetyLimits(TypedDict, total=False):
    """Safety boundary configuration."""
    max_actions_per_minute: int
    allowed_action_types: list[str]
    forbidden_targets: list[str]
    max_resource_pct: float


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
# Intermediate types
# ---------------------------------------------------------------------------

class SafetyCheckResult(TypedDict):
    """Result from safety_checker for a single action."""
    action_id: str
    action_type: str
    safe: bool
    reason: str
    risk_level: str


class ResourceUsage(TypedDict):
    """Current resource usage snapshot."""
    cpu_pct: float
    memory_mb: int
    api_calls_used: int
    cost_usd: float
    within_budget: bool


class RollbackPoint(TypedDict):
    """A rollback checkpoint."""
    id: str
    action_id: str
    snapshot: dict[str, Any]
    timestamp: str


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
    """An action approved for execution."""
    action: ActionItem
    safe: bool


class BlockedAction(TypedDict):
    """An action blocked from execution."""
    action: ActionItem
    reason: str


class AutonomousControlData(TypedDict):
    """The 'data' block of engine output."""
    approved: list[ApprovedAction]
    blocked: list[BlockedAction]
    resource_usage: ResourceUsage
    rollback_points: list[RollbackPoint]


class AutonomousControlMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class AutonomousControlOutput(TypedDict):
    """Final output of the autonomous control engine."""
    status: str
    data: AutonomousControlData | None
    meta: AutonomousControlMeta
    error: str | None
