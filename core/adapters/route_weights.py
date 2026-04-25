"""Route-weight ledger — stub.

The brain's reflection phase can penalize ``(adapter, capability)``
pairs that flake more than their declared priority implies. Real
implementation would persist the penalty so the router prefers
alternatives on the next cycle. Until then the ledger records
nothing and reports zero penalties applied.
"""
from __future__ import annotations

from typing import Any


class _RouteWeightLedger:
    def apply_reflection_report(self, report: Any) -> int:
        return 0


_LEDGER = _RouteWeightLedger()


def get_route_weight_ledger() -> _RouteWeightLedger:
    return _LEDGER
