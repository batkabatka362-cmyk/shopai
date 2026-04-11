"""Meta-Intelligence Governance — all TypedDicts and type aliases.

Single source of truth for every data shape in the meta governance engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class GovernanceInput(TypedDict, total=False):
    """Raw input payload arriving at the engine."""
    status: str
    data: GovernanceInputData
    meta: dict[str, Any]
    error: str | None


class GovernanceInputData(TypedDict, total=False):
    """The 'data' block inside the input payload."""
    engine: str                         # source engine name
    action: dict[str, Any]              # the action being proposed
    context: dict[str, Any]             # current system context


# ---------------------------------------------------------------------------
# Activity monitoring
# ---------------------------------------------------------------------------

class SystemActivity(TypedDict):
    """Classified system activity extracted from input."""
    activity_id: str
    source_engine: str
    activity_type: str                  # "decision", "execution", "learning"
    action_type: str                    # e.g. "launch_ad", "change_price"
    action_details: dict[str, Any]
    context: dict[str, Any]
    timestamp: str


class MonitorResult(TypedDict):
    """Output of the activity monitor."""
    activity: SystemActivity
    classification: str                 # "decision", "execution", "learning"
    severity: str                       # "low", "medium", "high", "critical"
    requires_deep_check: bool


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

class RuleViolation(TypedDict):
    """A single rule violation."""
    rule_id: str
    rule_name: str
    severity: str                       # "warning", "violation", "critical"
    detail: str
    field: str                          # which field triggered it


# ---------------------------------------------------------------------------
# Policy checker
# ---------------------------------------------------------------------------

class PolicyCheck(TypedDict):
    """Result of checking one policy."""
    policy_id: str
    policy_name: str
    passed: bool
    detail: str


# ---------------------------------------------------------------------------
# Risk controller
# ---------------------------------------------------------------------------

class RiskAssessment(TypedDict):
    """Risk assessment for the activity."""
    risk_type: str                      # "financial", "reputation", "operational", "compliance"
    level: str                          # "low", "medium", "high", "critical"
    score: float                        # 0.0–1.0
    detail: str


# ---------------------------------------------------------------------------
# Constraint enforcer
# ---------------------------------------------------------------------------

class ConstraintResult(TypedDict):
    """Result of enforcing one hard constraint."""
    constraint_id: str
    constraint_name: str
    enforced: bool                      # True = constraint was hit
    detail: str
    limit_value: Any
    actual_value: Any


# ---------------------------------------------------------------------------
# Decision validator
# ---------------------------------------------------------------------------

class ValidationResult(TypedDict):
    """Result of validating the decision."""
    check_name: str
    passed: bool
    score: float                        # 0.0–1.0
    detail: str


# ---------------------------------------------------------------------------
# Override handler
# ---------------------------------------------------------------------------

class OverrideDecision(TypedDict):
    """Result of the override handler."""
    override_needed: bool
    action: str                         # "approve", "reject", "modify"
    modifications: dict[str, Any]       # changes to apply if modified
    reasoning: str


# ---------------------------------------------------------------------------
# Audit / Memory
# ---------------------------------------------------------------------------

class AuditEntry(TypedDict):
    """Single audit trail entry."""
    entry_id: str
    timestamp: str
    activity_id: str
    source_engine: str
    action_type: str
    decision: str                       # "approved", "rejected", "modified"
    violations: list[RuleViolation]
    risks: list[RiskAssessment]
    override_applied: bool
    elapsed_seconds: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class GovernanceOutput(TypedDict):
    """Final output of the meta governance engine."""
    status: str                         # "approved", "rejected", "modified"
    data: GovernanceOutputData | None
    meta: GovernanceOutputMeta
    error: str | None


class GovernanceOutputData(TypedDict):
    """The 'data' block of the engine output."""
    decision: str                       # "approved", "approved_with_warning", "rejected", "modified"
    issues: list[str]
    risks: list[RiskAssessment]
    violations: list[RuleViolation]
    suggested_fix: str | None
    override: bool


class GovernanceOutputMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
