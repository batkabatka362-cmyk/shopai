"""Supplier Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the supplier engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class SupplierInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    suppliers: list
    orders: list
    quality_data: list


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SupplierData(TypedDict):
    """The 'data' block of engine output."""
    scores: list
    negotiation_tips: list
    relationship_health: dict


class SupplierMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class SupplierOutput(TypedDict):
    """Final output of the supplier engine."""
    status: str
    data: SupplierData | None
    meta: SupplierMeta
    error: str | None
