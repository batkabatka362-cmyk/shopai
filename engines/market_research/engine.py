"""
MarketResearch Engine — Research market opportunities — TAM/SAM/SOM analysis, trend detection, gap identification
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class MarketResearchEngine(BaseEngine):
    engine_name = "market_research"
    required_input_fields = ['market_data', 'target_segment']
    required_output_fields = ['insights', 'opportunities']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Domain analysis", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate structured output", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Creative enhancement", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Quality validation", required=True))
        self.flow.register_executor("validate", self._step_validate)

    def _step_analyze(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("analyze", data)
        r = self._model_router.execute("analyzer", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"analysis": r})

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("execute", data)
        r = self._model_router.execute("worker", prompt, context=data)
        return StepResult(step_name=step_name, model_used="qwen", status=EngineStatus.COMPLETED, output={"execution": r})

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("enhance", data)
        r = self._model_router.execute("creative", prompt, context=data)
        return StepResult(step_name=step_name, model_used="llama", status=EngineStatus.COMPLETED, output={"enhanced": r})

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("validate", data)
        r = self._model_router.execute("validator", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"validation": r})

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        templates = {"analyze": """Analyze market landscape:\n- Total Addressable Market (TAM) estimation\n- Serviceable market (SAM/SOM)\n- Growth rate and trajectory\n- Key trends (rising, declining, emerging)\n- Underserved segments\n- Entry barriers\n- Regulatory landscape\n\nMarket: {market_data}\nSegment: {target_segment}""", "execute": """Generate structured market research report:\n- Market size with sources\n- Top 5 opportunities ranked by potential\n- Competitive intensity map\n- Customer persona profiles\n- Channel analysis (where customers buy)\n- Pricing landscape\n- Timing recommendations\n\nAnalysis: {analysis}""", "enhance": """Enhance with narrative insights:\n- Market story (where is this market heading?)\n- Non-obvious opportunities others miss\n- Contrarian angles\n\nReport: {execution}""", "validate": """Validate: market sizes are realistic, opportunities are actionable, no contradictory data.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _estimate_tam(population: int, avg_spend: float, frequency: float) -> float:
        return round(population * avg_spend * frequency, 2)

    @staticmethod
    def _market_growth_rate(current: float, previous: float) -> float:
        if previous == 0: return 0.0
        return round((current - previous) / previous * 100, 2)

    @staticmethod
    def _concentration_ratio(top_n_share: float) -> str:
        if top_n_share > 0.8: return "highly_concentrated"
        if top_n_share > 0.5: return "moderately_concentrated"
        return "fragmented"
