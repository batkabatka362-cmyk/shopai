"""
Pricing Engine — Set optimal product prices using cost-plus, competitor-based, and value-based strategies
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class PricingEngine(BaseEngine):
    engine_name = "pricing"
    required_input_fields = ['product_data', 'market_data']
    required_output_fields = ['recommended_prices', 'price_rationale']

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
        templates = {"analyze": """Analyze pricing context:\n- Cost structure (COGS, shipping, fees, platform cut)\n- Competitor price range\n- Customer willingness to pay\n- Price elasticity signals\n- Perceived value vs actual cost\n- Channel-specific pricing norms\n- Currency and market adjustments\n\nProduct: {product_data}\nMarket: {market_data}""", "execute": """Generate pricing recommendations:\n- Recommended price (optimal)\n- Price range (floor to ceiling)\n- Pricing strategy (cost-plus / competitive / value-based)\n- Margin analysis at recommended price\n- Volume sensitivity (how sales change with price)\n- Promotional price suggestions\n- Bundle pricing opportunities\n\nAnalysis: {analysis}""", "enhance": """Enhance with pricing psychology:\n- Charm pricing (.99 vs .00)\n- Anchoring strategy (show original price)\n- Decoy pricing (add option to make target look better)\n- Framing (per day vs per month)\n\nPricing: {execution}""", "validate": """Validate: prices cover costs with target margin, competitive within market, no pricing below cost.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _cost_plus_price(cost: float, target_margin: float) -> float:
        if target_margin >= 1: return 0.0
        return round(cost / (1 - target_margin), 2)

    @staticmethod
    def _margin_at_price(price: float, cost: float) -> float:
        if price == 0: return 0.0
        return round((price - cost) / price, 4)

    @staticmethod
    def _competitive_position(our_price: float, competitor_prices: list[float]) -> str:
        if not competitor_prices: return "unknown"
        avg = sum(competitor_prices) / len(competitor_prices)
        ratio = our_price / avg
        if ratio < 0.85: return "undercut"
        if ratio < 0.95: return "slightly_below"
        if ratio < 1.05: return "at_market"
        if ratio < 1.15: return "slightly_above"
        return "premium"

    @staticmethod
    def _charm_price(price: float) -> float:
        return round(int(price) - 0.01, 2) if price > 1 else price
