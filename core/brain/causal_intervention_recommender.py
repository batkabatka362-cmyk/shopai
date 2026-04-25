"""Causal intervention recommender — rank actions to move a KPI.

causal_graph finds WHICH features drive a KPI. uplift_estimator finds
the treatment-effect SIZE. This module joins the two: given the
drivers + their effects + candidate interventions on those drivers,
it ranks interventions by expected gain toward the desired direction,
discounted by an optional cost per intervention.

An ``Intervention`` is:

    name, feature, delta (amount of change), cost_usd, side_effects

For each registered intervention, the recommender:

  1. Looks up the causal driver weight for (feature → kpi).
  2. Estimates impact = driver_weight × delta × direction_multiplier.
  3. Discounts by cost_usd / cost_scale.
  4. Penalises side effects on other KPIs.

Returns a ranked list. Pure stdlib, deterministic. No LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.causal_intervention_recommender")


Direction = Literal["up", "down"]


@dataclass
class Intervention:
    name: str
    feature: str              # which causal driver this moves
    delta: float              # signed magnitude of change
    cost_usd: float = 0.0
    description: str = ""
    side_effects: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Intervention.name required")
        if not self.feature:
            raise ValueError("Intervention.feature required")
        if self.cost_usd < 0:
            raise ValueError("cost_usd must be ≥ 0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "feature": self.feature,
            "delta": round(self.delta, 4),
            "cost_usd": round(self.cost_usd, 4),
            "description": self.description,
            "side_effects": dict(self.side_effects),
        }


@dataclass
class Recommendation:
    intervention: Intervention
    expected_impact: float
    cost_adjusted: float
    side_effect_penalty: float
    confidence: float
    notes: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return (
            self.cost_adjusted - self.side_effect_penalty
        ) * self.confidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "intervention": self.intervention.as_dict(),
            "expected_impact": round(self.expected_impact, 4),
            "cost_adjusted": round(self.cost_adjusted, 4),
            "side_effect_penalty": round(self.side_effect_penalty, 4),
            "confidence": round(self.confidence, 4),
            "score": round(self.score, 4),
            "notes": list(self.notes),
        }


class CausalInterventionRecommender:
    """Stateless recommender parameterised by a driver lookup."""

    def __init__(
        self,
        *,
        driver_weight_fn: Callable[[str, str], float] | None = None,
        cost_scale: float = 10.0,
        side_effect_weight: float = 1.0,
    ) -> None:
        if cost_scale <= 0:
            raise ValueError("cost_scale must be positive")
        if side_effect_weight < 0:
            raise ValueError("side_effect_weight must be ≥ 0")
        self._driver_weight_fn = driver_weight_fn
        self._cost_scale = float(cost_scale)
        self._side_effect_weight = float(side_effect_weight)

    def _driver_weight(
        self, feature: str, kpi: str,
    ) -> float:
        if self._driver_weight_fn is None:
            return 0.0
        try:
            return float(self._driver_weight_fn(feature, kpi))
        except Exception as exc:
            logger.debug(
                "driver_weight_fn(%s, %s) raised: %s",
                feature, kpi, exc,
            )
            return 0.0

    def _recommendation_for(
        self,
        interv: Intervention,
        *,
        kpi: str,
        direction: Direction,
    ) -> Recommendation:
        direction_mult = 1.0 if direction == "up" else -1.0
        weight = self._driver_weight(interv.feature, kpi)
        # Raw impact: weight × delta × direction_multiplier
        # (if weight is positive and delta negative, effect is negative
        # which we want when direction=down).
        raw_impact = weight * interv.delta * direction_mult
        # Cost-adjusted: subtract a scaled cost.
        cost_penalty = interv.cost_usd / self._cost_scale
        cost_adjusted = raw_impact - cost_penalty
        # Side-effect penalty: any non-target KPI that would MOVE
        # (absolute value × weight)
        side_penalty = 0.0
        notes: list[str] = []
        for other_kpi, other_delta in interv.side_effects.items():
            if other_kpi == kpi:
                continue
            w = self._driver_weight(interv.feature, other_kpi)
            pen = abs(w * other_delta) * self._side_effect_weight
            side_penalty += pen
            if pen > 0:
                notes.append(
                    f"side_effect on {other_kpi}: {w * other_delta:+.3f}",
                )
        # Confidence = |weight| clipped to [0, 1]; un-modelled drivers
        # → confidence = 0 so they don't surface as the top pick.
        confidence = max(0.0, min(1.0, abs(weight)))
        return Recommendation(
            intervention=interv,
            expected_impact=raw_impact,
            cost_adjusted=cost_adjusted,
            side_effect_penalty=side_penalty,
            confidence=confidence,
            notes=notes,
        )

    # ── Public API ───────────────────────────────────────

    def recommend(
        self,
        interventions: Iterable[Intervention],
        *,
        kpi: str,
        direction: Direction = "up",
        top_k: int = 5,
    ) -> list[Recommendation]:
        if not kpi:
            raise ValueError("kpi required")
        if direction not in ("up", "down"):
            raise ValueError("direction must be up|down")
        if top_k < 1:
            raise ValueError("top_k must be ≥ 1")
        ranked: list[Recommendation] = []
        for interv in interventions:
            ranked.append(self._recommendation_for(
                interv, kpi=kpi, direction=direction,
            ))
        # Filter pure-noise recommendations (zero confidence) out
        # unless nothing else is available.
        confident = [r for r in ranked if r.confidence > 0]
        if confident:
            confident.sort(key=lambda r: -r.score)
            return confident[:top_k]
        ranked.sort(key=lambda r: -r.score)
        return ranked[:top_k]

    def best(
        self,
        interventions: Iterable[Intervention],
        *,
        kpi: str,
        direction: Direction = "up",
    ) -> Recommendation | None:
        top = self.recommend(
            interventions, kpi=kpi, direction=direction, top_k=1,
        )
        return top[0] if top else None
