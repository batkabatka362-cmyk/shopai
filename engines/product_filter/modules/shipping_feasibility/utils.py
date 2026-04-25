"""Shared helpers for the shipping feasibility module.

Pre-audit, ``_billable_weight`` lived twice — identical math
in ``code.py`` and ``logic.py`` with slightly different
parameter names. Two copies of the same arithmetic invite
drift (someone tweaks the divisor fallback in one; the
other silently disagrees). This module is the canonical
home.
"""
from __future__ import annotations

from typing import Any


def billable_weight(
    weight_kg: float,
    dimensions_cm: dict[str, Any],
    divisor: float = 5000,
) -> float:
    """Return the greater of actual weight and dimensional
    weight, using the carrier divisor (default 5000, the
    IATA / UPS standard for kg-cm)."""
    if not isinstance(dimensions_cm, dict):
        dimensions_cm = {}
    vol = (
        float(dimensions_cm.get("length", 0) or 0)
        * float(dimensions_cm.get("width", 0) or 0)
        * float(dimensions_cm.get("height", 0) or 0)
    )
    dim_weight = (
        vol / divisor if divisor else float(weight_kg)
    )
    return max(float(weight_kg), dim_weight)
