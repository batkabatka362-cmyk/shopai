"""Structured types for the engine framework.

Every engine operates on these types — no raw data, no unstructured I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from utils.helpers import generate_id, timestamp_now


class EngineStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass
class EngineInput:
    """Structured input to an engine. All data must be pre-processed."""

    task_id: str
    engine_name: str
    data: dict[str, Any]
    params: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = generate_id("task")


@dataclass
class StepResult:
    """Result of a single execution step within an engine."""

    step_name: str
    model_used: str
    status: EngineStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=timestamp_now)


@dataclass
class EngineStep:
    """Definition of a single step in the engine flow."""

    name: str
    model_role: str  # "analyzer", "worker", "creative", "validator"
    description: str
    required: bool = True
    stop_on_reject: bool = False


@dataclass
class EngineOutput:
    """Structured output from an engine. Always consistent format."""

    task_id: str
    engine_name: str
    status: EngineStatus
    result: dict[str, Any] = field(default_factory=dict)
    steps: list[StepResult] = field(default_factory=list)
    error: str | None = None
    timestamp: str = field(default_factory=timestamp_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "engine_name": self.engine_name,
            "status": self.status.value,
            "result": self.result,
            "steps": [
                {
                    "step_name": s.step_name,
                    "model_used": s.model_used,
                    "status": s.status.value,
                    "output": s.output,
                    "error": s.error,
                    "duration_ms": s.duration_ms,
                    "timestamp": s.timestamp,
                }
                for s in self.steps
            ],
            "error": self.error,
            "timestamp": self.timestamp,
        }
