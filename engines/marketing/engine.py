"""
Marketing Engine — Plan comprehensive multi-channel marketing strategies
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class MarketingEngine(BaseEngine):
    engine_name = "marketing"
    required_input_fields = ['market_data', 'budget']
    required_output_fields = ['marketing_plan', 'channel_allocation']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze market opportunity and budget constraints", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate marketing strategy and channel plan", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with creative campaign angles", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate budget allocation and ROI projections", required=True))
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
        templates = {"analyze": """Analyze: target audience, channels available, competitor spend, seasonality, budget constraints.\nMarket: {market_data}\nBudget: {budget}""", "execute": """Generate plan: channel mix (paid/organic/email/social), budget per channel, KPIs, timeline, expected ROAS.\nAnalysis: {analysis}""", "enhance": """Enhance: creative campaign themes, viral hooks, guerrilla tactics.\nPlan: {execution}""", "validate": """Validate: budget sums correctly, ROAS targets realistic, channels appropriate for audience.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _calculate_roas(revenue: float, ad_spend: float) -> float:
        return round(revenue / max(ad_spend, 0.01), 2)

    @staticmethod
    def _budget_split(total: float, channels: dict[str, float]) -> dict[str, float]:
        weight_sum = sum(channels.values()) or 1
        return {ch: round(total * w / weight_sum, 2) for ch, w in channels.items()}
