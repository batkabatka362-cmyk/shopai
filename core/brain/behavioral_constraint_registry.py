"""Behavioral constraint registry — soft owner rules.

Owners declare preferences that don't fit hard safety rules:

  • "don't touch pricing between 9pm and 6am"
  • "never raise ad budget on Fridays"
  • "avoid pausing campaigns below 3-day data"

These are *soft* constraints — the brain may still act if
overriding is explicit. They differ from:

  • ``action_safety_guard``  — hard safety cutoffs
  • ``feasibility_gate``      — "can we do it at all"
  • ``ethics_gate``           — moral/policy constraints

Each constraint has a predicate over (action, context) and a
severity. Violations are recorded, not blocked; callers decide
whether to proceed. The registry produces ``ConstraintAlert``
objects the owner can review, and tracks per-constraint violation
counts so chronic violations get promoted.

Pure stdlib, deterministic.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.behavioral_constraint_registry")


Severity = Literal["info", "warn", "severe"]


@dataclass
class BehavioralConstraint:
    id: str
    name: str
    predicate: Callable[
        [dict[str, Any], dict[str, Any]], bool,
    ]
    severity: Severity
    description: str = ""
    active: bool = True

    def __post_init__(self) -> None:
        if self.severity not in ("info", "warn", "severe"):
            raise ValueError(
                "severity must be info|warn|severe",
            )


@dataclass
class ConstraintAlert:
    id: str
    constraint_id: str
    action_kind: str
    severity: Severity
    note: str
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "constraint_id": self.constraint_id,
            "action_kind": self.action_kind,
            "severity": self.severity,
            "note": self.note,
            "ts": self.ts,
        }


@dataclass
class EvaluationResult:
    alerts: list[ConstraintAlert]
    any_severe: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "alerts": [a.as_dict() for a in self.alerts],
            "any_severe": self.any_severe,
        }


class BehavioralConstraintRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._constraints: dict[str, BehavioralConstraint] = {}
        self._alerts: list[ConstraintAlert] = []
        self._violation_counts: dict[str, int] = defaultdict(int)

    # ── Register ─────────────────────────────────────────

    def register(
        self,
        *,
        name: str,
        predicate: Callable[
            [dict[str, Any], dict[str, Any]], bool,
        ],
        severity: Severity = "warn",
        description: str = "",
        constraint_id: str | None = None,
    ) -> BehavioralConstraint:
        if not name:
            raise ValueError("name required")
        cid = constraint_id or uuid.uuid4().hex
        constraint = BehavioralConstraint(
            id=cid,
            name=str(name),
            predicate=predicate,
            severity=severity,
            description=str(description),
            active=True,
        )
        with self._lock:
            self._constraints[cid] = constraint
        return constraint

    def deactivate(self, constraint_id: str) -> bool:
        with self._lock:
            c = self._constraints.get(constraint_id)
            if c is None:
                return False
            c.active = False
            return True

    def remove(self, constraint_id: str) -> bool:
        with self._lock:
            return (
                self._constraints.pop(constraint_id, None)
                is not None
            )

    # ── Evaluate ─────────────────────────────────────────

    def evaluate(
        self,
        *,
        action: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        if not action or "kind" not in action:
            raise ValueError("action with 'kind' required")
        ctx = dict(context or {})
        kind = str(action.get("kind", ""))
        with self._lock:
            constraints = [
                c for c in self._constraints.values()
                if c.active
            ]
        alerts: list[ConstraintAlert] = []
        any_severe = False
        for c in constraints:
            try:
                violated = bool(c.predicate(action, ctx))
            except Exception as exc:
                logger.debug(
                    "constraint %s predicate raised: %s",
                    c.id, exc,
                )
                continue
            if not violated:
                continue
            alert = ConstraintAlert(
                id=uuid.uuid4().hex,
                constraint_id=c.id,
                action_kind=kind,
                severity=c.severity,
                note=(
                    f"violated '{c.name}' ({c.description})"
                    if c.description
                    else f"violated '{c.name}'"
                ),
                ts=time.time(),
            )
            alerts.append(alert)
            if c.severity == "severe":
                any_severe = True
            with self._lock:
                self._alerts.append(alert)
                self._violation_counts[c.id] += 1
                if len(self._alerts) > 500:
                    del self._alerts[
                        : len(self._alerts) - 500
                    ]
        return EvaluationResult(
            alerts=alerts, any_severe=any_severe,
        )

    # ── Queries ──────────────────────────────────────────

    def active_constraints(
        self,
    ) -> list[BehavioralConstraint]:
        with self._lock:
            return [
                c for c in self._constraints.values()
                if c.active
            ]

    def violation_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._violation_counts)

    def recent_alerts(
        self, *, limit: int = 20,
    ) -> list[ConstraintAlert]:
        with self._lock:
            return list(
                self._alerts[-max(1, int(limit)):],
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_severity: dict[str, int] = {}
            for a in self._alerts:
                by_severity[a.severity] = (
                    by_severity.get(a.severity, 0) + 1
                )
            return {
                "constraints": len(self._constraints),
                "active": sum(
                    1 for c in self._constraints.values()
                    if c.active
                ),
                "alerts": len(self._alerts),
                "by_severity": by_severity,
            }

    def reset(self) -> int:
        with self._lock:
            n = (
                len(self._constraints)
                + len(self._alerts)
            )
            self._constraints.clear()
            self._alerts.clear()
            self._violation_counts.clear()
        return n
