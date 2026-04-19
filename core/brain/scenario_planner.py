"""Scenario planner — probability-weighted forward scenarios.

counterfactual_simulator rolls out *one* alternative path. anticipation
predicts a single point estimate. But real planning under uncertainty
needs to reason over *multiple* plausible futures at once.

``ScenarioPlanner`` takes a starting state and a ``ScenarioSpec`` that
describes variable outcomes (e.g. "CTR will be in [0.01, 0.05]") and
produces N concrete ``Scenario`` instances. Each scenario has:

  • id
  • probability        — prior * per-branch weight, normalised
  • state_projection   — resulting state dict
  • expected_value     — value metric if supplied by an evaluator

The planner's ``expected_value()`` method returns the probability-
weighted average. ``regret_bounds()`` returns min/max across
scenarios — the downside and upside the caller is exposing the
business to. Pure stdlib, deterministic, LLM-free.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.scenario_planner")


@dataclass
class Branch:
    label: str
    weight: float                  # relative weight, not probability
    modifier: dict[str, Any] = field(default_factory=dict)
    # Optional callable applied to the starting state
    transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "weight": round(self.weight, 4),
            "modifier": dict(self.modifier),
        }


@dataclass
class ScenarioSpec:
    name: str
    starting_state: dict[str, Any]
    branches: list[Branch]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name required")
        if not self.branches:
            raise ValueError("branches required")
        if any(b.weight <= 0 for b in self.branches):
            raise ValueError("branch weights must be > 0")


@dataclass
class Scenario:
    id: str
    spec_name: str
    label: str
    probability: float
    state_projection: dict[str, Any]
    expected_value: float | None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "spec_name": self.spec_name,
            "label": self.label,
            "probability": round(self.probability, 4),
            "state_projection": dict(self.state_projection),
            "expected_value": (
                round(self.expected_value, 4)
                if self.expected_value is not None else None
            ),
            "note": self.note,
        }


@dataclass
class ScenarioBundle:
    spec_name: str
    scenarios: list[Scenario]
    probability_weighted_value: float | None
    min_value: float | None
    max_value: float | None
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec_name": self.spec_name,
            "scenarios": [s.as_dict() for s in self.scenarios],
            "probability_weighted_value": (
                round(self.probability_weighted_value, 4)
                if self.probability_weighted_value is not None
                else None
            ),
            "min_value": (
                round(self.min_value, 4)
                if self.min_value is not None else None
            ),
            "max_value": (
                round(self.max_value, 4)
                if self.max_value is not None else None
            ),
            "ts": self.ts,
        }


def _apply_branch(
    state: dict[str, Any], branch: Branch,
) -> dict[str, Any]:
    out = dict(state)
    if branch.transform is not None:
        try:
            out = dict(branch.transform(out))
        except Exception as exc:
            logger.debug(
                "branch %s transform failed: %s",
                branch.label, exc,
            )
    for k, v in branch.modifier.items():
        out[k] = v
    return out


class ScenarioPlanner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bundles: list[ScenarioBundle] = []

    def plan(
        self,
        spec: ScenarioSpec,
        *,
        value_fn: Callable[[dict[str, Any]], float] | None = None,
    ) -> ScenarioBundle:
        total_weight = sum(b.weight for b in spec.branches)
        scenarios: list[Scenario] = []
        for b in spec.branches:
            prob = b.weight / total_weight
            state = _apply_branch(spec.starting_state, b)
            ev: float | None = None
            if value_fn is not None:
                try:
                    ev = float(value_fn(state))
                except Exception as exc:
                    logger.debug(
                        "value_fn raised on %s: %s",
                        b.label, exc,
                    )
                    ev = None
            scenarios.append(Scenario(
                id=uuid.uuid4().hex,
                spec_name=spec.name,
                label=b.label,
                probability=prob,
                state_projection=state,
                expected_value=ev,
            ))
        # aggregate
        values = [s.expected_value for s in scenarios]
        if any(v is None for v in values):
            pwv = None
            min_v = None
            max_v = None
        else:
            numeric = [float(v) for v in values]
            pwv = sum(
                s.probability * float(s.expected_value)
                for s in scenarios
            )
            min_v = min(numeric)
            max_v = max(numeric)
        bundle = ScenarioBundle(
            spec_name=spec.name,
            scenarios=scenarios,
            probability_weighted_value=pwv,
            min_value=min_v,
            max_value=max_v,
            ts=time.time(),
        )
        with self._lock:
            self._bundles.append(bundle)
            if len(self._bundles) > 100:
                del self._bundles[: len(self._bundles) - 100]
        return bundle

    def expected_value(self, bundle: ScenarioBundle) -> float:
        if bundle.probability_weighted_value is not None:
            return bundle.probability_weighted_value
        # If no value_fn was supplied, treat all scenarios as equal
        return 0.0

    def regret_bounds(
        self, bundle: ScenarioBundle,
    ) -> tuple[float, float]:
        if bundle.min_value is None or bundle.max_value is None:
            return (0.0, 0.0)
        pwv = self.expected_value(bundle)
        downside = pwv - bundle.min_value
        upside = bundle.max_value - pwv
        return (downside, upside)

    def recent(self, *, limit: int = 10) -> list[ScenarioBundle]:
        with self._lock:
            return list(self._bundles[-max(1, int(limit)):])

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "bundles": len(self._bundles),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._bundles)
            self._bundles.clear()
        return n
