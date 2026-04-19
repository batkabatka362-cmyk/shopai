"""Utility blender — multi-objective scoring with owner preferences.

Shopify decisions rarely optimise one number. Killing an ad raises
profit but drops attribution data. Scaling lowers risk-adjusted ROAS
but grows AOV. utility_blender combines several signed objectives
into a single utility score with:

  • Per-objective weights (owner preference dials)
  • Normalisation — each objective gets mapped into [0..1] so they
    are comparable regardless of unit (dollars vs ratios vs counts)
  • Hard floors — if any objective falls below its floor, utility is
    zero (Leontief corner), which prevents pareto-dominated picks

Callers register objectives once:

    blender.register(Objective(
        name="roas", direction="max", weight=1.0,
        low=0.5, high=3.0, floor=1.0,
    ))

Then for every candidate option:

    score = blender.score({"roas": 2.1, "refund_rate": 0.05, ...})
    best  = blender.rank([option_a, option_b, ...])

Pure stdlib. Deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


Direction = Literal["max", "min"]


@dataclass
class Objective:
    name: str
    direction: Direction = "max"
    weight: float = 1.0
    low: float = 0.0       # value mapping low → 0
    high: float = 1.0      # value mapping high → 1
    floor: float | None = None   # below this, utility = 0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Objective.name required")
        if self.direction not in ("max", "min"):
            raise ValueError("direction must be 'max' or 'min'")
        if self.weight < 0:
            raise ValueError("weight must be non-negative")
        if self.high == self.low:
            raise ValueError("low and high must differ")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "direction": self.direction,
            "weight": self.weight,
            "low": self.low,
            "high": self.high,
            "floor": self.floor,
        }

    def normalise(self, value: float) -> float:
        if self.direction == "max":
            raw = (value - self.low) / (self.high - self.low)
        else:
            raw = (self.high - value) / (self.high - self.low)
        return max(0.0, min(1.0, raw))

    def violates_floor(self, value: float) -> bool:
        if self.floor is None:
            return False
        if self.direction == "max":
            return value < self.floor
        return value > self.floor


@dataclass
class UtilityReport:
    score: float
    weighted_components: dict[str, float]
    raw_components: dict[str, float]
    floor_violations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "weighted_components": {
                k: round(v, 4) for k, v in self.weighted_components.items()
            },
            "raw_components": self.raw_components,
            "floor_violations": list(self.floor_violations),
        }


class UtilityBlender:
    def __init__(self) -> None:
        self._objectives: dict[str, Objective] = {}

    def register(self, obj: Objective, overwrite: bool = False) -> None:
        if obj.name in self._objectives and not overwrite:
            raise ValueError(
                f"objective {obj.name!r} already registered",
            )
        self._objectives[obj.name] = obj

    def unregister(self, name: str) -> bool:
        return self._objectives.pop(name, None) is not None

    def objectives(self) -> list[Objective]:
        return list(self._objectives.values())

    def score(
        self,
        values: dict[str, float],
        *,
        missing_policy: Literal["zero", "skip", "raise"] = "zero",
    ) -> UtilityReport:
        """Score a single candidate. Missing objective values default
        to 0 (pessimistic) unless the caller changes ``missing_policy``.
        """
        if not self._objectives:
            return UtilityReport(
                score=0.0, weighted_components={}, raw_components={},
            )
        raw: dict[str, float] = {}
        weighted: dict[str, float] = {}
        violations: list[str] = []
        total_weight = 0.0
        for obj in self._objectives.values():
            if obj.name not in values:
                if missing_policy == "raise":
                    raise KeyError(
                        f"missing value for objective {obj.name!r}",
                    )
                if missing_policy == "skip":
                    continue
                # "zero" — treat missing as zero-normalised
                value = obj.low if obj.direction == "max" else obj.high
            else:
                value = float(values[obj.name])
            raw[obj.name] = value
            if obj.violates_floor(value):
                violations.append(obj.name)
            norm = obj.normalise(value)
            contrib = norm * obj.weight
            weighted[obj.name] = contrib
            total_weight += obj.weight

        if total_weight == 0:
            base = 0.0
        else:
            base = sum(weighted.values()) / total_weight

        score = 0.0 if violations else base
        return UtilityReport(
            score=score, weighted_components=weighted,
            raw_components=raw, floor_violations=violations,
        )

    def rank(
        self,
        options: Iterable[dict[str, Any]],
        *,
        value_key: str = "values",
        name_key: str = "name",
    ) -> list[tuple[str, UtilityReport]]:
        """Rank candidate options (list of dicts) by score descending.

        Each option dict should have a ``name`` and a ``values``
        mapping of objective_name → number. Keys configurable via the
        kwargs above for callers with a different schema.
        """
        results: list[tuple[str, UtilityReport]] = []
        for opt in options:
            results.append(
                (
                    str(opt.get(name_key, "")),
                    self.score(opt.get(value_key, {}) or {}),
                ),
            )
        results.sort(key=lambda pair: -pair[1].score)
        return results
