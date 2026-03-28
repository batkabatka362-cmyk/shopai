"""
Pricing Engine — Set optimal product prices using cost-plus, competition, and value-based strategies
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
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze cost structure and market price landscape", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Calculate optimal prices per strategy", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Add pricing psychology insights", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate price feasibility and margins", required=True))
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
            "analyze": """Analyze pricing inputs:\n- Product cost (COGS + shipping + platform fees)\n- Competitor price range\n- Perceived value indicators\n- Price sensitivity of target audience\n- Volume-price relationship\n\nProduct: {product_data}\nMarket: {market_data}""",
            "execute": """Calculate recommended prices using 3 strategies:\n1. Cost-plus: cost * (1 + target_margin)\n2. Competitive: position vs competitor avg\n3. Value-based: perceived value pricing\n\nOutput: price per strategy, recommended price, margin %, break-even volume.\n\nAnalysis: {analysis}""",
            "enhance": """Add pricing psychology: charm pricing (.99), anchoring strategies, bundle pricing suggestions, perceived value framing.\n\nPrices: {execution}""",
            "validate": """Validate: margins > 20%, prices within market range, no below-cost pricing, rationale is consistent.\n\nOutput: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\nData: " + str(data)

    @staticmethod
    def _cost_plus_price(cost: float, target_margin: float = 0.4) -> float:
        return round(cost / (1 - target_margin), 2)

    @staticmethod
    def _competitive_price(competitor_prices: list[float], position: str = "competitive") -> float:
        if not competitor_prices:
            return 0.0
        avg = sum(competitor_prices) / len(competitor_prices)
        multipliers = {"budget": 0.85, "competitive": 0.97, "premium": 1.2}
        return round(avg * multipliers.get(position, 1.0), 2)

    @staticmethod
    def _charm_price(price: float) -> float:
        return float(int(price)) - 0.01 if price > 1 else price
