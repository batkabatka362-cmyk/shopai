"""
Subscription Engine

Purpose: Design subscription plans and optimize tier pricing for recurring revenue
Input:   ['product_catalog', 'pricing_tiers']
Output:  ['subscription_plans', 'pricing_recommendations']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class SubscriptionEngine(BaseEngine):
    engine_name = "subscription"
    required_input_fields = ['product_catalog', 'pricing_tiers']
    required_output_fields = ['subscription_plans', 'pricing_recommendations']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze product catalog and pricing tier viability",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate subscription plans and pricing recommendations",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance plans with creative value propositions",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate subscription economics and plan structure",
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
            "analyze": """You are a subscription business strategist. Analyze the product catalog and pricing tiers for subscription potential.

Evaluate:
1. Product suitability for recurring delivery
2. Customer purchase frequency patterns
3. Competitor subscription offerings
4. Price sensitivity for subscription vs one-time purchase
5. Churn risk factors by product category

Product catalog: {product_catalog}
Pricing tiers: {pricing_tiers}

Return: subscription viability scores, recommended products, pricing benchmarks, and risk assessment.""",
            "execute": """Based on the analysis, generate subscription plans and pricing recommendations.

Analysis results: {analysis}
Product catalog: {product_catalog}
Pricing tiers: {pricing_tiers}

For each subscription plan provide:
- plan_name, tier, included_products
- monthly_price, annual_price, savings_percentage
- billing_frequency, commitment_period
- features, upgrade_path

Return as structured JSON with subscription_plans and pricing_recommendations arrays.""",
            "enhance": """Enhance the subscription plans with compelling value propositions.

Add:
- Exclusive subscriber benefits
- Loyalty rewards integration
- Referral incentives
- Surprise and delight elements

Current output: {execution}""",
            "validate": """Validate the subscription plan economics and structure.

Check:
1. Monthly prices are sustainable (cover costs + margin)
2. Annual discounts are between 10-25%
3. Tier progression offers clear value increases
4. No cannibalization between tiers
5. LTV projections are realistic

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _calculate_ltv(monthly_price: float, avg_subscription_months: float, gross_margin: float) -> float:
        return round(monthly_price * avg_subscription_months * gross_margin, 2)

    @staticmethod
    def _optimize_tier_pricing(costs: list[float], target_margins: list[float], competitor_prices: list[float]) -> list[float]:
        optimized = []
        for i, cost in enumerate(costs):
            margin = target_margins[i] if i < len(target_margins) else 0.3
            floor_price = cost / (1 - margin) if margin < 1 else cost * 2
            ceiling = competitor_prices[i] if i < len(competitor_prices) else floor_price * 1.5
            optimal = min(max(floor_price, cost * 1.2), ceiling)
            optimized.append(round(optimal, 2))
        return optimized
