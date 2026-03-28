"""
Monetization Engine — Optimize revenue streams: upsells, bundles, subscriptions, cross-sells
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class MonetizationEngine(BaseEngine):
    engine_name = "monetization"
    required_input_fields = ['revenue_data', 'channel_data']
    required_output_fields = ['monetization_plan', 'revenue_projections']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze current revenue mix and monetization gaps", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate monetization optimization plan", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Add compelling offer narratives", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate revenue projections", required=True))
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
            "analyze": """Analyze revenue streams:\n- Revenue by channel/product\n- Average order value (AOV)\n- Customer lifetime value (LTV)\n- Upsell/cross-sell conversion rates\n- Subscription potential\n- Bundle performance\n\nRevenue: {revenue_data}\nChannels: {channel_data}""",
            "execute": """Generate monetization plan:\n- Upsell opportunities with expected lift\n- Bundle recommendations (products + pricing)\n- Cross-sell mapping\n- Subscription model design\n- Revenue projections per initiative\n\nAnalysis: {analysis}""",
            "enhance": """Craft compelling offer copy for each monetization initiative: upsell hooks, bundle value propositions, subscription benefits.\n\nPlan: {execution}""",
            "validate": """Validate: projections are conservative, initiatives don't cannibalize each other, AOV impact is realistic.\n\nOutput: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\nData: " + str(data)

    @staticmethod
    def _calculate_aov(total_revenue: float, total_orders: int) -> float:
        return round(total_revenue / max(total_orders, 1), 2)

    @staticmethod
    def _ltv_estimate(aov: float, purchase_frequency: float, retention_months: int) -> float:
        return round(aov * purchase_frequency * retention_months, 2)

    @staticmethod
    def _bundle_discount(items: list[float], discount_pct: float = 0.15) -> float:
        total = sum(items)
        return round(total * (1 - discount_pct), 2)
