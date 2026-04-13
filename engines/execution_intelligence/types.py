"""Execution Intelligence Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the execution intelligence engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ActionPlan(TypedDict, total=False):
    """Raw input payload arriving at the engine from the decision engine."""
    status: str
    data: ActionPlanData
    meta: dict[str, Any]
    error: str | None


class ActionPlanData(TypedDict, total=False):
    """The 'data' block inside the input payload."""
    actions: list[ActionItem]


class ActionItem(TypedDict, total=False):
    """A single action from the decision engine."""
    type: str                           # e.g. "create_product", "launch_ad", "update_inventory"
    data: dict[str, Any]                # action-specific payload


# ---------------------------------------------------------------------------
# Parsed task types
# ---------------------------------------------------------------------------

class ParsedTask(TypedDict):
    """A task after parsing from the raw action item."""
    task_id: str
    action_type: str
    parameters: dict[str, Any]
    priority: int                       # 1=highest, 5=lowest
    dependencies: list[str]             # task_ids this depends on
    source_index: int                   # index in original actions list


# ---------------------------------------------------------------------------
# Validated task types
# ---------------------------------------------------------------------------

class ValidatedTask(TypedDict):
    """A task after validation — confirmed ready for execution."""
    task_id: str
    action_type: str
    parameters: dict[str, Any]
    priority: int
    dependencies: list[str]
    source_index: int
    validation: ValidationInfo


class ValidationInfo(TypedDict):
    """Validation metadata attached to a validated task."""
    is_valid: bool
    checks_passed: list[str]
    checks_failed: list[str]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Tool selection types
# ---------------------------------------------------------------------------

class ToolSelection(TypedDict):
    """Tool/API selected for executing a task."""
    task_id: str
    action_type: str
    tool_name: str                      # e.g. "shopify_api", "facebook_ads", "content_generator"
    tool_config: dict[str, Any]         # tool-specific configuration
    execution_mode: str                 # "sync" or "async"


# ---------------------------------------------------------------------------
# Execution result types
# ---------------------------------------------------------------------------

class ExecutionResult(TypedDict):
    """Result from executing a single task."""
    task_id: str
    action_type: str
    status: str                         # "success", "fail", "partial"
    result: dict[str, Any]
    error: str | None
    duration_seconds: float


# ---------------------------------------------------------------------------
# Action result (aggregated)
# ---------------------------------------------------------------------------

class ActionResult(TypedDict):
    """Aggregated result across all executed tasks."""
    executed: list[ExecutionSummary]
    failed: list[ExecutionSummary]
    results: list[TaskResult]
    total: int
    success_count: int
    fail_count: int
    partial_count: int


class ExecutionSummary(TypedDict):
    """Summary of a single task's execution outcome."""
    task_id: str
    type: str
    status: str


class TaskResult(TypedDict):
    """Detailed result for a single task."""
    task_id: str
    result: dict[str, Any]


# ---------------------------------------------------------------------------
# Status report types
# ---------------------------------------------------------------------------

class StatusReport(TypedDict):
    """Execution status report with logs and metrics."""
    overall_status: str                 # "success", "partial", "fail"
    success_rate: float                 # 0.0 to 1.0
    total_tasks: int
    succeeded: int
    failed: int
    logs: list[str]
    elapsed_seconds: float


# ---------------------------------------------------------------------------
# Retry types
# ---------------------------------------------------------------------------

class RetryInfo(TypedDict):
    """Information about retry attempts for a failed task."""
    task_id: str
    attempts: int
    max_retries: int
    last_error: str
    next_delay_seconds: float
    exhausted: bool


# ---------------------------------------------------------------------------
# Error classification types
# ---------------------------------------------------------------------------

class ErrorClassification(TypedDict):
    """Classified error with recovery strategy."""
    task_id: str
    error_type: str                     # "transient", "permanent", "partial"
    error_message: str
    recoverable: bool
    recovery_strategy: str              # "retry", "skip", "fallback", "abort"
    severity: str                       # "low", "medium", "high", "critical"


# ---------------------------------------------------------------------------
# Memory types
# ---------------------------------------------------------------------------

class ExecutionRecord(TypedDict, total=False):
    """A stored execution record."""
    record_id: str
    timestamp: str
    action_types: list[str]
    input_hash: str
    total_tasks: int
    success_count: int
    fail_count: int
    overall_status: str
    results: list[dict[str, Any]]
    logs: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ExecutionIntelligenceOutput(TypedDict):
    """Final output of the execution intelligence engine."""
    status: str
    data: ExecutionIntelligenceData | None
    meta: ExecutionIntelligenceMeta
    error: str | None


class ExecutionIntelligenceData(TypedDict):
    """The 'data' block of the engine output."""
    executed: list[ExecutionSummary]
    failed: list[ExecutionSummary]
    results: list[TaskResult]
    logs: list[str]


class ExecutionIntelligenceMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
