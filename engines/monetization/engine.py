"""
Monetization Engine — Optimize revenue streams — identify new monetization opportunities, maximize LTV per channel
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
        templates = {"analyze": """Analyze monetization landscape:\n- Revenue by channel/stream breakdown\n- Revenue per customer (ARPU)\n- Customer lifetime value by segment\n- Monetization rate (visitors to revenue)\n- Undermonetized segments\n- Cross-sell/upsell penetration\n- Recurring vs one-time revenue mix\n\nRevenue: {revenue_data}\nChannels: {channel_data}""", "execute": """Generate monetization plan:\n- New revenue stream opportunities\n- Upsell/cross-sell strategies with projected lift\n- Subscription/recurring revenue opportunities\n- Premium tier design\n- Bundle strategies\n- Channel optimization (shift spend to highest ROI)\n- 30/60/90 day revenue targets\n\nAnalysis: {analysis}""", "enhance": """Enhance: creative monetization angles, value-add services, digital product opportunities, partnership revenue.\n\nPlan: {execution}""", "validate": """Validate: revenue projections are conservative, costs included, no double-counting across channels.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _arpu(total_revenue: float, total_customers: int) -> float:
        if total_customers == 0: return 0.0
        return round(total_revenue / total_customers, 2)

    @staticmethod
    def _ltv(arpu: float, avg_lifespan_months: float) -> float:
        return round(arpu * avg_lifespan_months, 2)

    @staticmethod
    def _monetization_rate(revenue: float, visitors: int) -> float:
        if visitors == 0: return 0.0
        return round(revenue / visitors, 4)

    @staticmethod
    def _revenue_mix(streams: dict[str, float]) -> dict[str, float]:
        total = sum(streams.values())
        if total == 0: return {}
        return {k: round(v / total * 100, 2) for k, v in streams.items()}
