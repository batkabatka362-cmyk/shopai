"""SupplierDiscovery Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the supplier discovery engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class SupplierDiscoveryInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    product_requirements: dict
    regions: list
    budget: dict


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SupplierDiscoveryData(TypedDict):
    """The 'data' block of engine output."""
    suppliers: list
    recommended: list
    comparison: dict


class SupplierDiscoveryMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class SupplierDiscoveryOutput(TypedDict):
    """Final output of the supplier discovery engine."""
    status: str
    data: SupplierDiscoveryData | None
    meta: SupplierDiscoveryMeta
    error: str | None
