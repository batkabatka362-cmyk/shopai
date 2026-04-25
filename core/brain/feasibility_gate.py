"""Feasibility gate — hard / soft constraint filter over actions.

Not every decision should be taken even if it scores well. Budgets
cap spend, inventory caps promise, SLAs cap acceptable latency. A
policy that greedily picks the highest-utility option violates these
and the owner finds out the hard way.

This gate centralises:

  • Named constraints with predicates and optional repair hints
  • ``evaluate(action)`` → Verdict("feasible" | "infeasible", violations)
  • ``filter(actions)`` → only feasible ones
  • ``best_feasible(options, utility_fn)`` → highest-utility feasible

Four canonical constraint builders:

    budget_cap("ads_daily", limit=20.0, extractor=lambda a: a.cost)
    floor_cap("min_margin", floor=0.15, extractor=lambda a: a.margin)
    inventory_cap("sku_123", on_hand=12, extractor=lambda a: a.qty)
    sla_cap("api_latency_ms", limit=500, extractor=...)

Custom predicates compose with ``Constraint(name, predicate, ...)``.

Complements the existing ``constraint_solver.py`` (LP-style optimiser):
this module is a *gate*, not an allocator.

Pure stdlib. Deterministic. No LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


Predicate = Callable[[Any], bool]


@dataclass
class Constraint:
    name: str
    predicate: Predicate
    repair_hint: str = ""
    severity: str = "hard"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Constraint.name required")
        if self.severity not in ("hard", "soft"):
            raise ValueError("severity must be hard|soft")

    def check(self, action: Any) -> bool:
        try:
            return bool(self.predicate(action))
        except Exception:
            return False


@dataclass
class Violation:
    constraint: str
    severity: str
    repair_hint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "constraint": self.constraint,
            "severity": self.severity,
            "repair_hint": self.repair_hint,
        }


@dataclass
class Verdict:
    feasible: bool
    violations: list[Violation] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "feasible": self.feasible,
            "violations": [v.as_dict() for v in self.violations],
        }


class FeasibilityGate:
    def __init__(self) -> None:
        self._constraints: dict[str, Constraint] = {}

    def register(
        self, constraint: Constraint, overwrite: bool = False,
    ) -> None:
        if constraint.name in self._constraints and not overwrite:
            raise ValueError(
                f"constraint {constraint.name!r} already registered",
            )
        self._constraints[constraint.name] = constraint

    def unregister(self, name: str) -> bool:
        return self._constraints.pop(name, None) is not None

    def constraints(self) -> list[Constraint]:
        return list(self._constraints.values())

    # ── Evaluation ────────────────────────────────────────

    def evaluate(self, action: Any) -> Verdict:
        violations: list[Violation] = []
        any_hard = False
        for c in self._constraints.values():
            if not c.check(action):
                violations.append(Violation(
                    constraint=c.name,
                    severity=c.severity,
                    repair_hint=c.repair_hint,
                ))
                if c.severity == "hard":
                    any_hard = True
        return Verdict(feasible=not any_hard, violations=violations)

    def filter(
        self, actions: Iterable[Any],
    ) -> list[tuple[Any, Verdict]]:
        return [(a, self.evaluate(a)) for a in actions]

    def feasible_only(self, actions: Iterable[Any]) -> list[Any]:
        return [a for a, v in self.filter(actions) if v.feasible]

    def best_feasible(
        self,
        options: Iterable[Any],
        utility_fn: Callable[[Any], float],
    ) -> Any | None:
        best = None
        best_u = float("-inf")
        for a in options:
            if not self.evaluate(a).feasible:
                continue
            u = utility_fn(a)
            if u > best_u:
                best = a
                best_u = u
        return best


# ── Canonical constraint builders ─────────────────────────

def budget_cap(
    name: str,
    limit: float,
    extractor: Callable[[Any], float],
    severity: str = "hard",
) -> Constraint:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    return Constraint(
        name=name,
        predicate=lambda a: float(extractor(a)) <= float(limit),
        repair_hint=f"reduce value to ≤ {limit}",
        severity=severity,
    )


def floor_cap(
    name: str,
    floor: float,
    extractor: Callable[[Any], float],
    severity: str = "hard",
) -> Constraint:
    return Constraint(
        name=name,
        predicate=lambda a: float(extractor(a)) >= float(floor),
        repair_hint=f"raise value to ≥ {floor}",
        severity=severity,
    )


def inventory_cap(
    sku: str,
    on_hand: int,
    extractor: Callable[[Any], int],
    severity: str = "hard",
) -> Constraint:
    if on_hand < 0:
        raise ValueError("on_hand must be non-negative")
    return Constraint(
        name=f"inventory:{sku}",
        predicate=lambda a: int(extractor(a)) <= int(on_hand),
        repair_hint=f"only {on_hand} available for {sku}",
        severity=severity,
    )


def sla_cap(
    name: str,
    max_latency_ms: float,
    extractor: Callable[[Any], float],
    severity: str = "soft",
) -> Constraint:
    return Constraint(
        name=name,
        predicate=lambda a: float(extractor(a)) <= float(max_latency_ms),
        repair_hint=(
            f"shrink workload or switch route; cap {max_latency_ms}ms"
        ),
        severity=severity,
    )


def value_in(
    name: str,
    extractor: Callable[[Any], Any],
    allowed: Iterable[Any],
    severity: str = "hard",
) -> Constraint:
    allowed_set = set(allowed)
    return Constraint(
        name=name,
        predicate=lambda a: extractor(a) in allowed_set,
        repair_hint=f"must be one of {sorted(allowed_set, key=str)}",
        severity=severity,
    )
