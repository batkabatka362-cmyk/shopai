"""
Marketing Engine — Plan comprehensive marketing strategies — channel mix, budget, messaging
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
        templates = {"analyze": """Analyze marketing landscape: channels, audience, competitors, budget constraints, past performance, brand awareness.\n\nMarket: {market_data}\nBudget: {budget}""", "execute": """Generate marketing plan: channel allocation, messaging framework, campaign calendar, KPI targets, budget split.\nAnalysis: {analysis}""", "enhance": """Enhance: creative angles, guerrilla tactics, viral hooks.\nPlan: {execution}""", "validate": """Validate: budget sums correctly, channels appropriate for audience, KPIs measurable.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _roas(revenue: float, ad_spend: float) -> float:
        if ad_spend == 0: return 0.0
        return round(revenue / ad_spend, 2)

    @staticmethod
    def _cac(total_spend: float, new_customers: int) -> float:
        if new_customers == 0: return 0.0
        return round(total_spend / new_customers, 2)

    @staticmethod
    def _channel_efficiency(channels: dict[str, dict]) -> dict[str, float]:
        return {name: round(ch.get("revenue", 0) / max(ch.get("spend", 1), 1), 2) for name, ch in channels.items()}
