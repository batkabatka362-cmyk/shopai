"""Time Intelligence — all TypedDicts and type aliases.

Single source of truth for every data shape in the time intelligence engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class TaskInput(TypedDict, total=False):
    """A single task as received in the input payload."""
    type: str
    priority: str
    deadline: str | None
    dependency: list[str]


class ClassifiedTask(TypedDict):
    """A task after classification."""
    task_id: str
    original_type: str
    classification: str
    urgency: str
    domain: str
    deadline: str | None
    dependencies: list[str]


class PriorityResult(TypedDict):
    """Priority analysis result for a single task."""
    task_id: str
    priority_score: float
    urgency_weight: float
    deadline_weight: float
    dependency_weight: float
    business_impact: float
    model_note: str


class DependencyResult(TypedDict):
    """Dependency resolution result for all tasks."""
    execution_order: list[str]
    blocked_tasks: list[dict[str, Any]]
    ready_tasks: list[str]
    dependency_graph: dict[str, list[str]]
    model_note: str


class TimeEstimate(TypedDict):
    """Time estimate for a single task."""
    task_id: str
    estimated_seconds: float
    complexity: str
    confidence: float


class ScheduledTask(TypedDict):
    """A task after scheduling."""
    task_id: str
    scheduled_time: str
    priority_score: float
    estimated_duration_seconds: float
    slot_index: int
    model_note: str


class QueueEntry(TypedDict):
    """An entry in the execution queue."""
    task_id: str
    priority_score: float
    scheduled_time: str
    status: str
    enqueued_at: str


class ExecutionStatus(TypedDict):
    """Execution status for a single task."""
    task_id: str
    status: str
    started_at: str | None
    completed_at: str | None
    error: str | None
    attempt: int


class RetryInfo(TypedDict):
    """Retry information for a failed task."""
    task_id: str
    retry_count: int
    max_retries: int
    next_retry_at: str
    backoff_seconds: float
    reason: str


class DelayInfo(TypedDict):
    """Delay information for a task that needs to wait."""
    task_id: str
    reason: str
    delay_seconds: float
    resume_at: str


class TimingPlan(TypedDict):
    """Overall timing plan for all tasks."""
    total_estimated_duration: str
    next_execution: str
    slots_used: int
    capacity_remaining: int


class TimeIntelligenceOutput(TypedDict):
    """Final output of the time intelligence engine."""
    status: str
    data: TimeIntelligenceData | None
    meta: TimeIntelligenceMeta
    error: str | None


class TimeIntelligenceData(TypedDict):
    """The data block of the engine output."""
    scheduled_tasks: list[ScheduledTask]
    delayed_tasks: list[DelayInfo]
    blocked_tasks: list[dict[str, Any]]
    execution_order: list[str]
    timing_plan: TimingPlan


class TimeIntelligenceMeta(TypedDict):
    """The meta block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
