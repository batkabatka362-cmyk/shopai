"""AutonomousExecution Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the autonomous execution engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class AutonomousExecutionInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    actions: list
    execution_config: dict


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class AutonomousExecutionData(TypedDict):
    """The 'data' block of engine output."""
    executed: list
    failed: list
    progress: dict


class AutonomousExecutionMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class AutonomousExecutionOutput(TypedDict):
    """Final output of the autonomous execution engine."""
    status: str
    data: AutonomousExecutionData | None
    meta: AutonomousExecutionMeta
    error: str | None
