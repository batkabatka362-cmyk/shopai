"""Strategy coherence monitor — do actions match the stated strategy?

strategy_planner declares plans like "focus on high-AOV SKUs this
week" or "cut ad spend until ROAS recovers". If subsequent decisions
contradict that (e.g. launching a low-AOV SKU, or raising ad budget
despite a falling ROAS), the strategy is only nominal. This module
cross-checks declared strategy clauses against recorded actions and
flags drift.

Each strategy is a set of ``StrategyClause`` constraints:

  • ``required_tag``     — action must carry this tag
  • ``forbidden_tag``    — action must NOT carry this tag
  • ``max_stake_sum``    — capped cumulative stake across actions

When an action is recorded, the monitor checks every active
strategy's clauses. Violations emit ``CoherenceAlert`` with the
offending action id, clause id, and reason.

Pure stdlib, deterministic. Complements ``coherence_checker`` (which
flags reasoning vs belief contradictions) by checking *actions vs
strategy*.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.strategy_coherence_monitor")


ClauseKind = Literal[
    "required_tag", "forbidden_tag", "max_stake_sum",
]


@dataclass
class StrategyClause:
    id: str
    kind: ClauseKind
    value: Any                 # tag string or numeric cap
    description: str = ""

    def __post_init__(self) -> None:
        if self.kind not in (
            "required_tag", "forbidden_tag", "max_stake_sum",
        ):
            raise ValueError(
                "kind must be required_tag|forbidden_tag|"
                "max_stake_sum",
            )
        if self.kind == "max_stake_sum":
            try:
                float(self.value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "max_stake_sum value must be numeric",
                ) from exc
        else:
            if not isinstance(self.value, str) or not self.value:
                raise ValueError(
                    f"{self.kind} value must be a non-empty str",
                )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "value": self.value,
            "description": self.description,
        }


@dataclass
class Strategy:
    id: str
    name: str
    clauses: list[StrategyClause]
    active: bool = True
    created_ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "clauses": [c.as_dict() for c in self.clauses],
            "active": self.active,
            "created_ts": self.created_ts,
        }


@dataclass
class ActionRecord:
    id: str
    kind: str
    stake: float
    tags: tuple[str, ...]
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "stake": round(self.stake, 4),
            "tags": list(self.tags),
            "ts": self.ts,
        }


@dataclass
class CoherenceAlert:
    id: str
    strategy_id: str
    clause_id: str
    action_id: str
    reason: str
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "strategy_id": self.strategy_id,
            "clause_id": self.clause_id,
            "action_id": self.action_id,
            "reason": self.reason,
            "ts": self.ts,
        }


class StrategyCoherenceMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._strategies: dict[str, Strategy] = {}
        self._actions: list[ActionRecord] = []
        self._alerts: list[CoherenceAlert] = []
        self._stake_sums: dict[str, float] = defaultdict(float)
        # strategy_id → cumulative stake (for max_stake_sum)

    # ── Strategy lifecycle ───────────────────────────────

    def declare(
        self,
        *,
        name: str,
        clauses: Iterable[StrategyClause],
        strategy_id: str | None = None,
    ) -> Strategy:
        if not name:
            raise ValueError("name required")
        clause_list = list(clauses)
        if not clause_list:
            raise ValueError("at least one clause required")
        sid = strategy_id or uuid.uuid4().hex
        strategy = Strategy(
            id=sid, name=name,
            clauses=clause_list,
            active=True,
            created_ts=time.time(),
        )
        with self._lock:
            self._strategies[sid] = strategy
            self._stake_sums[sid] = 0.0
        return strategy

    def deactivate(self, strategy_id: str) -> bool:
        with self._lock:
            s = self._strategies.get(strategy_id)
            if s is None:
                return False
            s.active = False
            return True

    # ── Action intake ────────────────────────────────────

    def record_action(
        self,
        *,
        kind: str,
        stake: float,
        tags: Iterable[str] = (),
        action_id: str | None = None,
        ts: float | None = None,
    ) -> list[CoherenceAlert]:
        if not kind:
            raise ValueError("kind required")
        if not 0.0 <= stake <= 1.0:
            raise ValueError("stake must be in [0, 1]")
        aid = action_id or uuid.uuid4().hex
        timestamp = float(ts if ts is not None else time.time())
        action = ActionRecord(
            id=aid, kind=str(kind),
            stake=float(stake),
            tags=tuple(str(t) for t in tags if t),
            ts=timestamp,
        )
        alerts: list[CoherenceAlert] = []
        with self._lock:
            self._actions.append(action)
            tag_set = set(action.tags)
            for strategy in self._strategies.values():
                if not strategy.active:
                    continue
                for clause in strategy.clauses:
                    violated = False
                    reason = ""
                    if clause.kind == "required_tag":
                        if clause.value not in tag_set:
                            violated = True
                            reason = (
                                f"action missing required tag "
                                f"{clause.value!r}"
                            )
                    elif clause.kind == "forbidden_tag":
                        if clause.value in tag_set:
                            violated = True
                            reason = (
                                f"action carries forbidden tag "
                                f"{clause.value!r}"
                            )
                    elif clause.kind == "max_stake_sum":
                        self._stake_sums[strategy.id] += action.stake
                        cap = float(clause.value)
                        if self._stake_sums[strategy.id] > cap:
                            violated = True
                            reason = (
                                f"cumulative stake "
                                f"{self._stake_sums[strategy.id]:.2f}"
                                f" exceeds cap {cap:.2f}"
                            )
                    if violated:
                        alert = CoherenceAlert(
                            id=uuid.uuid4().hex,
                            strategy_id=strategy.id,
                            clause_id=clause.id,
                            action_id=action.id,
                            reason=reason,
                            ts=time.time(),
                        )
                        self._alerts.append(alert)
                        alerts.append(alert)
            if len(self._alerts) > 500:
                del self._alerts[: len(self._alerts) - 500]
        return alerts

    # ── Queries ──────────────────────────────────────────

    def strategy(self, strategy_id: str) -> Strategy | None:
        with self._lock:
            return self._strategies.get(strategy_id)

    def active_strategies(self) -> list[Strategy]:
        with self._lock:
            return [
                s for s in self._strategies.values() if s.active
            ]

    def alerts(
        self, *, limit: int = 50,
    ) -> list[CoherenceAlert]:
        with self._lock:
            return list(self._alerts[-max(1, int(limit)):])

    def violation_rate(self) -> float:
        with self._lock:
            if not self._actions:
                return 0.0
            violating_actions = {a.action_id for a in self._alerts}
            return (
                len(violating_actions) / len(self._actions)
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "strategies": len(self._strategies),
                "active": sum(
                    1 for s in self._strategies.values()
                    if s.active
                ),
                "actions": len(self._actions),
                "alerts": len(self._alerts),
            }

    def reset(self) -> int:
        with self._lock:
            n = (
                len(self._strategies)
                + len(self._actions)
                + len(self._alerts)
            )
            self._strategies.clear()
            self._actions.clear()
            self._alerts.clear()
            self._stake_sums.clear()
        return n
