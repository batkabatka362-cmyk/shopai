"""
PriceElasticity Engine

Purpose: Analyze price elasticity of demand and determine optimal pricing
Input:   ['pricing_data', 'demand_data']
Output:  ['elasticity_coefficients', 'optimal_prices']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class PriceElasticityEngine(BaseEngine):
    engine_name = "price_elasticity"
    required_input_fields = ['pricing_data', 'demand_data']
    required_output_fields = ['elasticity_coefficients', 'optimal_prices']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze historical pricing and demand patterns",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Calculate elasticity coefficients and optimal prices",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance with creative pricing strategy suggestions",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate elasticity calculations and price recommendations",
            required=True,
        ))
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
            "analyze": """You are a pricing economist. Analyze historical pricing and demand data to understand price sensitivity.

Evaluate:
1. Price-demand correlation patterns
2. Seasonal and cyclical demand variations
3. Cross-price elasticity with competing products
4. Income elasticity factors
5. Price threshold and psychological pricing effects

Pricing data: {pricing_data}
Demand data: {demand_data}

Return: demand patterns, preliminary elasticity estimates, market segment analysis, and data quality assessment.""",
            "execute": """Based on the analysis, calculate elasticity coefficients and determine optimal prices.

Analysis results: {analysis}
Pricing data: {pricing_data}
Demand data: {demand_data}

For each product provide:
- product_id, current_price, elasticity_coefficient
- optimal_price, expected_demand_change
- revenue_impact, margin_impact
- confidence_interval

Return as structured JSON with elasticity_coefficients and optimal_prices arrays.""",
            "enhance": """Enhance the pricing analysis with creative pricing strategy recommendations.

Add:
- Bundle pricing opportunities
- Psychological pricing suggestions
- Dynamic pricing rules
- Promotional pricing calendar

Current output: {execution}""",
            "validate": """Validate the elasticity calculations and pricing recommendations.

Check:
1. Elasticity coefficients are within realistic ranges (-5 to 0 for normal goods)
2. Optimal prices maintain minimum margin thresholds
3. Revenue projections are mathematically consistent
4. Confidence intervals are properly calculated
5. No price recommendations below cost

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _calculate_elasticity(price_old: float, price_new: float, demand_old: float, demand_new: float) -> float:
        if price_old == 0 or demand_old == 0:
            return 0.0
        pct_demand_change = (demand_new - demand_old) / demand_old
        pct_price_change = (price_new - price_old) / price_old
        if pct_price_change == 0:
            return 0.0
        return round(pct_demand_change / pct_price_change, 4)

    @staticmethod
    def _find_optimal_price(current_price: float, elasticity: float, cost: float) -> float:
        if elasticity == 0 or elasticity == -1:
            return current_price
        optimal = cost * elasticity / (1 + elasticity)
        return round(max(optimal, cost * 1.1), 2)
