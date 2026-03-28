"""
DynamicPricing Engine — Adjust prices dynamically based on demand, competition, inventory, and time
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class DynamicPricingEngine(BaseEngine):
    engine_name = "dynamic_pricing"
    required_input_fields = ['current_prices', 'market_signals']
    required_output_fields = ['adjusted_prices', 'adjustment_reasons']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze real-time market signals for price adjustments", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Calculate dynamic price adjustments", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Add urgency/scarcity messaging", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate adjustments within bounds", required=True))
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
            "analyze": """Analyze signals for price adjustment:\n- Demand velocity (increasing/decreasing)\n- Competitor price changes\n- Inventory levels (overstocked/low)\n- Time factors (day of week, season)\n- Conversion rate trends\n\nCurrent: {current_prices}\nSignals: {market_signals}""",
            "execute": """Calculate adjustments:\n- Per product: new price, change %, reason\n- Rules: max +/- 20% per day, never below cost, never above 2x competitor avg\n- Priority: low-stock items first\n\nAnalysis: {analysis}""",
            "enhance": """Suggest urgency messaging for price changes: limited time, stock scarcity, trending now.\n\nAdjustments: {execution}""",
            "validate": """Validate: changes within bounds, no below-cost prices, no rapid oscillation, reasons documented.\n\nOutput: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\nData: " + str(data)

    @staticmethod
    def _calculate_adjustment(current: float, demand_signal: float, inventory_signal: float) -> float:
        adjustment = 0.0
        if demand_signal > 0.7:
            adjustment += 0.05
        elif demand_signal < 0.3:
            adjustment -= 0.05
        if inventory_signal < 0.2:
            adjustment += 0.08
        elif inventory_signal > 0.8:
            adjustment -= 0.08
        return round(max(-0.20, min(0.20, adjustment)), 3)

    @staticmethod
    def _apply_bounds(price: float, floor: float, ceiling: float) -> float:
        return round(max(floor, min(ceiling, price)), 2)
