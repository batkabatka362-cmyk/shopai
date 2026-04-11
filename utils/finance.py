"""Finance computation utilities.

Collects small financial formulas that were duplicated across the codebase
(~40 copies of the margin formula alone, each with subtly different edge
case handling). Centralizing them removes drift between modules and gives
one place to reason about invalid inputs.
"""
from __future__ import annotations

from typing import Any


def margin(
    price: Any,
    cost: Any,
    *,
    default: float = 0.0,
    as_percent: bool = False,
    precision: int | None = None,
    require_cost: bool = True,
) -> float:
    """Profit margin computed from a price and cost.

    Returns ``(price - cost) / price`` by default. Options:

    - ``as_percent=True``: multiplies by 100 (e.g. 0.35 → 35.0).
    - ``precision``: round to N decimal places (None = no rounding).
    - ``default``: value returned when inputs are invalid (see below).
    - ``require_cost``: when True (the default), a missing / non-positive
      cost is treated as "cost unknown" and the default is returned. When
      False, a cost of 0 yields a full 100% margin.

    Invalid inputs (return ``default``):
        - price is None, non-numeric, or <= 0
        - require_cost=True and cost is None, non-numeric, or <= 0

    Negative margins (cost > price) are returned as-is — callers that
    need to filter them can do so explicitly.

    Examples:
        >>> margin(25, 10)
        0.6
        >>> margin(25, 10, as_percent=True, precision=1)
        60.0
        >>> margin(25, None)          # missing cost → default
        0.0
        >>> margin(25, 0, require_cost=False)  # treat 0 as zero cost
        1.0
        >>> margin(0, 5)              # invalid price → default
        0.0
    """
    try:
        p = float(price) if price is not None else 0.0
        c = float(cost) if cost is not None else 0.0
    except (TypeError, ValueError):
        return default

    if p <= 0:
        return default
    if require_cost and c <= 0:
        return default

    val = (p - c) / p
    if as_percent:
        val *= 100.0
    if precision is not None:
        val = round(val, precision)
    return val


def margin_pct(
    price: Any,
    cost: Any,
    *,
    default: float = 0.0,
    precision: int | None = 2,
    require_cost: bool = True,
) -> float:
    """Profit margin as a percent (0-100). Shortcut for ``margin(..., as_percent=True)``.

    Defaults to 2 decimal precision since percent values are typically
    rounded for display.
    """
    return margin(
        price, cost,
        default=default,
        as_percent=True,
        precision=precision,
        require_cost=require_cost,
    )
