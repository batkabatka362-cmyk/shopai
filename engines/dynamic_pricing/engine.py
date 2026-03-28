"""
DynamicPricing Engine — Adjust prices dynamically based on demand, competition, inventory, and time signals
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
        templates = {"analyze": """Analyze dynamic pricing signals:\n- Current demand velocity vs normal\n- Competitor price changes (last 24h/7d)\n- Inventory level (days of stock)\n- Time-based factors (day of week, hour, season)\n- Cart abandonment rate at current price\n- Conversion rate trends\n- External events (holidays, trends)\n\nPrices: {current_prices}\nSignals: {market_signals}""", "execute": """Generate price adjustments:\n- Per-product: new price, change %, reason\n- Priority: which changes have highest impact\n- Timing: when to apply (immediate vs scheduled)\n- Duration: temporary vs permanent\n- Floor/ceiling enforcement\n- Projected revenue impact\n\nAnalysis: {analysis}""", "enhance": """Enhance with urgency optimization:\n- Scarcity signals (low stock = price up?)\n- Demand surge pricing rules\n- Time-decay discounts for aging inventory\n\nAdjustments: {execution}""", "validate": """Validate: no price below floor, no excessive change (>20% in 24h), changes are reversible.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _price_change_pct(old: float, new: float) -> float:
        if old == 0: return 0.0
        return round((new - old) / old * 100, 2)

    @staticmethod
    def _demand_multiplier(current_demand: float, avg_demand: float) -> float:
        if avg_demand == 0: return 1.0
        return round(current_demand / avg_demand, 3)

    @staticmethod
    def _should_adjust(multiplier: float, threshold: float = 0.15) -> bool:
        return abs(multiplier - 1.0) > threshold

    @staticmethod
    def _inventory_urgency(days_of_stock: float) -> float:
        if days_of_stock <= 3: return 0.0
        if days_of_stock <= 7: return -0.05
        if days_of_stock > 60: return 0.10
        return 0.0
