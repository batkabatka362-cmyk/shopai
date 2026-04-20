"""Delegation router — where should this task run?

Every task arriving at the brain has an implicit routing question:

  • ``owner``   — blocking human question; needs a person's call
  • ``engine``  — deterministic engine can handle (rule-based)
  • ``llm``     — requires generative/fuzzy reasoning
  • ``skip``    — not worth doing right now

The router takes a ``Task`` (kind, stakes, novelty, capability_name,
urgency) and returns a ``Route`` with a target + confidence + reason.
Rules are registered in priority order; a default catch-all uses
capability_registry to check "can we do this?".

Complements ``delegation_`` concepts elsewhere: ``meta_router``
routes across LLM *providers*; ``delegation_router`` routes across
*execution targets* (human/engine/LLM/skip). Pure stdlib.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.delegation_router")


Target = Literal["owner", "engine", "llm", "skip"]


@dataclass
class Task:
    kind: str
    stakes: float           # 0..1
    novelty: float          # 0..1
    capability_name: str    # looked up in capability_registry
    urgency: int            # 0 = leisurely, 3 = fire drill
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "stakes": round(self.stakes, 4),
            "novelty": round(self.novelty, 4),
            "capability_name": self.capability_name,
            "urgency": self.urgency,
            "note": self.note,
        }


@dataclass
class Route:
    id: str
    target: Target
    reason: str
    confidence: float
    rule_id: str
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target": self.target,
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
            "rule_id": self.rule_id,
            "ts": self.ts,
        }


@dataclass
class RoutingRule:
    id: str
    priority: int         # lower wins
    matches: Callable[[Task], bool]
    target: Target
    reason: str
    confidence: float = 0.8


def _high_stakes(task: Task) -> bool:
    return task.stakes >= 0.8


def _novel_and_uncertain(task: Task) -> bool:
    return task.novelty >= 0.7 and task.stakes >= 0.4


def _urgent_low_stakes(task: Task) -> bool:
    return task.urgency >= 2 and task.stakes < 0.4


_DEFAULT_RULES: tuple[RoutingRule, ...] = (
    RoutingRule(
        id="safety_to_owner",
        priority=10,
        matches=_high_stakes,
        target="owner",
        reason="high stakes — owner approval required",
        confidence=0.95,
    ),
    RoutingRule(
        id="novel_to_llm",
        priority=20,
        matches=_novel_and_uncertain,
        target="llm",
        reason="novel situation — generative reasoning needed",
        confidence=0.7,
    ),
    RoutingRule(
        id="urgent_low_to_engine",
        priority=30,
        matches=_urgent_low_stakes,
        target="engine",
        reason="urgent + low-stakes — run deterministic engine",
        confidence=0.8,
    ),
)


class DelegationRouter:
    def __init__(
        self,
        *,
        rules: Iterable[RoutingRule] | None = None,
        capability_check: Callable[[str], bool] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._rules: list[RoutingRule] = list(
            rules if rules is not None else _DEFAULT_RULES,
        )
        self._rules.sort(key=lambda r: r.priority)
        self._capability_check = capability_check
        self._recent: list[Route] = []

    # ── Rule registry ────────────────────────────────────

    def register_rule(self, rule: RoutingRule) -> None:
        with self._lock:
            self._rules.append(rule)
            self._rules.sort(key=lambda r: r.priority)

    def unregister_rule(self, rule_id: str) -> bool:
        with self._lock:
            before = len(self._rules)
            self._rules = [
                r for r in self._rules if r.id != rule_id
            ]
            return len(self._rules) < before

    # ── Route ────────────────────────────────────────────

    def route(self, task: Task) -> Route:
        if not 0.0 <= task.stakes <= 1.0:
            raise ValueError("stakes must be in [0, 1]")
        if not 0.0 <= task.novelty <= 1.0:
            raise ValueError("novelty must be in [0, 1]")
        if task.urgency < 0:
            raise ValueError("urgency must be ≥ 0")
        with self._lock:
            rules = list(self._rules)
            cap_check = self._capability_check
        for rule in rules:
            try:
                if rule.matches(task):
                    route = Route(
                        id=uuid.uuid4().hex,
                        target=rule.target,
                        reason=rule.reason,
                        confidence=rule.confidence,
                        rule_id=rule.id,
                        ts=time.time(),
                    )
                    self._archive(route)
                    return route
            except Exception as exc:
                logger.debug(
                    "rule %s matches raised: %s",
                    rule.id, exc,
                )
        # Fallback based on capability
        has_capability = (
            cap_check(task.capability_name)
            if cap_check is not None else True
        )
        if not has_capability:
            route = Route(
                id=uuid.uuid4().hex,
                target="skip",
                reason=(
                    f"capability {task.capability_name!r} "
                    "not ready"
                ),
                confidence=0.9,
                rule_id="capability_gap",
                ts=time.time(),
            )
        else:
            route = Route(
                id=uuid.uuid4().hex,
                target="engine",
                reason="no rule matched; defaulting to engine",
                confidence=0.6,
                rule_id="default_engine",
                ts=time.time(),
            )
        self._archive(route)
        return route

    def _archive(self, route: Route) -> None:
        with self._lock:
            self._recent.append(route)
            if len(self._recent) > 200:
                del self._recent[: len(self._recent) - 200]

    # ── Queries ──────────────────────────────────────────

    def recent(self, *, limit: int = 20) -> list[Route]:
        with self._lock:
            return list(self._recent[-max(1, int(limit)):])

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_target: dict[str, int] = {}
            for r in self._recent:
                by_target[r.target] = (
                    by_target.get(r.target, 0) + 1
                )
            return {
                "rules": len(self._rules),
                "rule_ids": sorted(
                    r.id for r in self._rules
                ),
                "routed": len(self._recent),
                "by_target": by_target,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._recent)
            self._recent.clear()
        return n
