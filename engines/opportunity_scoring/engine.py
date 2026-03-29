"""
OpportunityScoringEngine
Purpose: Score and rank detected opportunities using multi-criteria evaluation
Input: ['opportunities', 'scoring_criteria']
Output: ['scored_opportunities', 'rankings']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class OpportunityScoringEngine(BaseEngine):
    engine_name = "opportunity_scoring"
    required_input_fields = ["opportunities", "scoring_criteria"]
    required_output_fields = ["scored_opportunities", "rankings"]

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze input", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate output", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance output", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate output", required=True))
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
            "analyze": (
                "You are an opportunity scoring strategist. Evaluate the provided opportunities "
                "against the scoring criteria to understand their relative merit.\n\n"
                "Opportunities: {opportunities}\nScoring Criteria: {scoring_criteria}\n\n"
                "Assess how well each opportunity maps to the criteria dimensions. "
                "Identify any criteria gaps or opportunities that dominate multiple dimensions."
            ),
            "execute": (
                "Score each opportunity against the scoring criteria and produce a ranked list.\n\n"
                "Opportunities: {opportunities}\nScoring Criteria: {scoring_criteria}\n\n"
                "Apply each criterion with its specified weight. Produce a composite score per opportunity. "
                "Return JSON: {{\"scored_opportunities\": [{{"
                "\"id\": str, \"title\": str, \"scores\": {{}}, \"composite_score\": float}}], "
                "\"rankings\": [{{\"rank\": int, \"id\": str, \"composite_score\": float}}]}}"
            ),
            "enhance": (
                "Add qualitative commentary to the scored opportunities explaining the score rationale.\n\n"
                "Opportunities: {opportunities}\nScoring Criteria: {scoring_criteria}\n\n"
                "For top-ranked opportunities, add a strategic rationale for why they score highly. "
                "For low-ranked, explain what would need to change to improve their standing."
            ),
            "validate": (
                "Validate the scoring results for consistency and alignment with the criteria.\n\n"
                "Opportunities: {opportunities}\nScoring Criteria: {scoring_criteria}\n\n"
                "Check: Are weights applied correctly? Are scores within valid ranges? "
                "Do rankings reflect the composite scores? Flag any inconsistencies."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_opportunity_score(criteria_scores: dict[str, float], weights: dict[str, float]) -> float:
        """Calculate a weighted composite score for an opportunity."""
        total_weight = sum(weights.values()) or 1.0
        weighted_sum = sum(criteria_scores.get(k, 0) * w for k, w in weights.items())
        return round(weighted_sum / total_weight, 4)

    @staticmethod
    def _rank_opportunities(scored: list[dict]) -> list[dict]:
        """Sort opportunities by composite_score descending and assign rank positions."""
        sorted_opps = sorted(scored, key=lambda x: x.get("composite_score", 0), reverse=True)
        for i, opp in enumerate(sorted_opps):
            opp["rank"] = i + 1
        return sorted_opps
