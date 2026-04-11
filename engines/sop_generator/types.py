"""SOP Generator Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the SOP generator engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class SopInputData(TypedDict, total=False):
    execution_history: list[dict[str, Any]]
    operations: list[str]


class SopStep(TypedDict):
    step_number: int
    action: str
    details: str
    responsible: str
    estimated_time_minutes: int


class Sop(TypedDict):
    operation: str
    steps: list[SopStep]
    triggers: list[str]
    responsibilities: list[str]


class SopData(TypedDict):
    sops: list[Sop]
    coverage: dict[str, bool]
    gaps: list[str]


class SopMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class SopOutput(TypedDict):
    status: str
    data: SopData | None
    meta: SopMeta
    error: str | None
