"""CustomerSupport Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the customer support engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CustomerSupportInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    tickets: list
    resolutions: list
    agents: list


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class CustomerSupportData(TypedDict):
    """The 'data' block of engine output."""
    classified_tickets: list
    suggested_resolutions: list
    workload_report: dict
    satisfaction_scores: dict


class CustomerSupportMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class CustomerSupportOutput(TypedDict):
    """Final output of the customer support engine."""
    status: str
    data: CustomerSupportData | None
    meta: CustomerSupportMeta
    error: str | None
