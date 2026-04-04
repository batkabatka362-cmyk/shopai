"""Workflow Builder Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the workflow builder engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class WorkflowStep(TypedDict, total=False):
    engine: str
    config: dict[str, Any]
    depends_on: list[str]


class WorkflowBuilderInputData(TypedDict, total=False):
    steps: list[WorkflowStep]
    context: dict[str, Any]


class DesignedStep(TypedDict):
    step_id: str
    engine: str
    config: dict[str, Any]
    depends_on: list[str]
    estimated_duration_seconds: float


class DependencyGraph(TypedDict):
    steps_ordered: list[str]
    dependencies: dict[str, list[str]]
    parallel_groups: list[list[str]]


class ValidationResult(TypedDict):
    valid: bool
    errors: list[str]
    warnings: list[str]


class ExecutionPlan(TypedDict):
    total_steps: int
    parallel_groups: list[list[str]]
    estimated_duration_seconds: float
    execution_order: list[str]


class WorkflowBuilderData(TypedDict):
    workflow: dict[str, Any]
    validation: ValidationResult
    execution_plan: ExecutionPlan
    estimated_duration: float


class WorkflowBuilderMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class WorkflowBuilderOutput(TypedDict):
    status: str
    data: WorkflowBuilderData | None
    meta: WorkflowBuilderMeta
    error: str | None
