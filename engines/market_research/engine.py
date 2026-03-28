"""
MarketResearch Engine — Research market opportunities, trends, and gaps
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
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze market landscape and identify patterns", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate market insights and opportunity map", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with strategic narratives", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate market data consistency", required=True))
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
            "analyze": """Analyze the market landscape for the target segment.\n\nAssess: market size (TAM/SAM/SOM), growth rate, key trends, customer pain points, underserved niches, regulatory environment, barriers to entry.\n\nMarket data: {market_data}\nTarget: {target_segment}""",
            "execute": """Generate structured market insights:\n- Top 5 opportunities ranked by potential\n- Market gaps with estimated demand\n- Entry strategy recommendations\n- Risk factors per opportunity\n\nAnalysis: {analysis}""",
            "enhance": """Enhance with compelling market narrative: why NOW is the time, what the winning angle is, how to position against incumbents.\n\nInsights: {execution}""",
            "validate": """Validate: market size numbers are realistic, growth rates sourced, no contradictory insights, opportunities ranked consistently.\n\nOutput: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\nData: " + str(data)

    @staticmethod
    def _estimate_tam(population: int, conversion_rate: float, avg_order_value: float) -> float:
        return round(population * conversion_rate * avg_order_value, 2)

    @staticmethod
    def _market_growth_rate(current: float, previous: float) -> float:
        if previous == 0:
            return 0.0
        return round((current - previous) / previous * 100, 2)
