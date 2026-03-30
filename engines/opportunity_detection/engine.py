"""
OpportunityDetectionEngine
Purpose: Detect business opportunities from market signals and business context
Input: ['market_signals', 'business_context']
Output: ['opportunities', 'opportunity_scores']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class OpportunityDetectionEngine(BaseEngine):
    engine_name = "opportunity_detection"
    required_input_fields = ["market_signals", "business_context"]
    required_output_fields = ["opportunities", "opportunity_scores"]

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
                "You are a business opportunity analyst. Review the market signals and business context "
                "to identify gaps, unmet needs, and exploitable market positions.\n\n"
                "Market Signals: {market_signals}\nBusiness Context: {business_context}\n\n"
                "Assess the strength of each signal, the competitive landscape, and the feasibility "
                "of capitalizing on detected patterns."
            ),
            "execute": (
                "Identify and describe specific business opportunities from the market signals.\n\n"
                "Market Signals: {market_signals}\nBusiness Context: {business_context}\n\n"
                "For each opportunity provide: title, description, market size estimate, "
                "entry difficulty, and a viability score 0-1. Return as JSON: "
                '{{\"opportunities\": [{{"title\": str, \"description\": str, \"market_size\": str, '
                '\"entry_difficulty\": str, \"viability_score\": float}}]}}'
            ),
            "enhance": (
                "Enrich each detected opportunity with strategic framing and first-mover advantages.\n\n"
                "Market Signals: {market_signals}\nBusiness Context: {business_context}\n\n"
                "Add competitive moat analysis, timing urgency, and recommended first steps "
                "for each opportunity. Make each description compelling for strategic planning."
            ),
            "validate": (
                "Validate that identified opportunities are grounded in the provided signals.\n\n"
                "Market Signals: {market_signals}\nBusiness Context: {business_context}\n\n"
                "Check: Are opportunities supported by specific signals? Are viability scores realistic? "
                "Are there risks or blockers not yet captured? Return validation status and flags."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _score_opportunity(signal_strength: float, market_size: float, competition: float) -> float:
        """Score an opportunity based on signal strength, market size, and competition level."""
        competition_factor = max(0.0, 1.0 - competition)
        return round(signal_strength * 0.4 + market_size * 0.4 + competition_factor * 0.2, 4)

    @staticmethod
    def _filter_viable_opportunities(opportunities: list[dict], min_score: float = 0.5) -> list[dict]:
        """Filter opportunities to those meeting a minimum viability score."""
        return [o for o in opportunities if o.get("viability_score", 0) >= min_score]
