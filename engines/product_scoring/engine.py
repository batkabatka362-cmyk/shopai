"""
ProductScoring Engine

Purpose: Score products on multiple weighted criteria: demand, margin, competition, trend, risk
Input:   ['product_data', 'scoring_criteria']
Output:  ['scores', 'rankings']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ProductScoringEngine(BaseEngine):
    engine_name = "product_scoring"
    required_input_fields = ['product_data', 'scoring_criteria']
    required_output_fields = ['scores', 'rankings']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze input and assess viability",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate structured domain output",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance output with creative insights",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate output quality and consistency",
            required=True,
        ))
        self.flow.register_executor("validate", self._step_validate)

    def _step_analyze(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("analyze", data)
        result = self._model_router.execute("analyzer", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"analysis": result})

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("execute", data)
        result = self._model_router.execute("worker", prompt, context=data)
        return StepResult(step_name=step_name, model_used="qwen", status=EngineStatus.COMPLETED, output={"execution": result})

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("enhance", data)
        result = self._model_router.execute("creative", prompt, context=data)
        return StepResult(step_name=step_name, model_used="llama", status=EngineStatus.COMPLETED, output={"enhanced": result})

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("validate", data)
        result = self._model_router.execute("validator", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"validation": result})

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        templates = {
            "analyze": """Score these products across 8 dimensions: demand, margin, competition, trend, risk, shipping, seasonality, uniqueness.

Product data: {product_data}
Scoring criteria & weights: {scoring_criteria}

For each product, provide a 0-10 score per dimension with reasoning.""",
            "execute": """Calculate weighted total scores and generate rankings.

Analysis scores: {analysis}
Weights: {scoring_criteria}

Output: sorted rankings with per-dimension scores, weighted totals, and tier classification (A/B/C/D).""",
            "enhance": """Add competitive insights to each scored product.

For top-tier products: suggest differentiation strategies.
For low-tier products: explain what would need to change to improve the score.

Scores: {execution}""",
            "validate": """Validate scoring output:
1. All dimensions scored (0-10 range)
2. Weights sum to 1.0
3. Rankings sorted correctly
4. No scoring anomalies (e.g., high demand + zero competition should flag)

Output: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    SCORING_DIMENSIONS = [
        "demand", "margin", "competition", "trend",
        "risk", "shipping", "seasonality", "uniqueness",
    ]

    DEFAULT_WEIGHTS = {
        "demand": 0.20, "margin": 0.20, "competition": 0.15,
        "trend": 0.15, "risk": 0.10, "shipping": 0.08,
        "seasonality": 0.06, "uniqueness": 0.06,
    }

    @classmethod
    def _weighted_score(cls, dimension_scores: dict[str, float], weights: dict[str, float] | None = None) -> float:
        w = weights or cls.DEFAULT_WEIGHTS
        total = sum(dimension_scores.get(d, 0) * w.get(d, 0) for d in cls.SCORING_DIMENSIONS)
        return round(total, 3)

    @staticmethod
    def _normalize_scores(scores: list[float]) -> list[float]:
        if not scores:
            return []
        max_s = max(scores) or 1
        return [round(s / max_s * 10, 2) for s in scores]

