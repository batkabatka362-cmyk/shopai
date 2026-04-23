"""Typed contracts shared across ShopAI layers.

CLAUDE.md §4b.F — engine ↔ adapter data exchange should go
through typed structures so schema drift surfaces at module
load, not inside a retry storm in production.

This package holds the cross-layer enums + dataclasses that
need to be stable. Concrete per-pipeline contracts (e.g.
``LaunchGoal``) live next to their pipeline (``workflows/launch/
context.py``) so the import graph stays flat.
"""
from core.contracts.business_model import (
    BusinessModel,
    Channel,
    RiskLevel,
)

__all__ = [
    "BusinessModel",
    "Channel",
    "RiskLevel",
]
