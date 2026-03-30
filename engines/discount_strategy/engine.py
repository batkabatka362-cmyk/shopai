"""
DiscountStrategyEngine
Purpose: Design optimal discount strategies that balance revenue impact with conversion uplift
Input: ['product_data', 'discount_goals']
Output: ['discount_plan', 'expected_impact']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class DiscountStrategyEngine(BaseEngine):
    engine_name = "discount_strategy"
    required_input_fields = ["product_data", "discount_goals"]
    required_output_fields = ["discount_plan", "expected_impact"]

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze input", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate output", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance output", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate output", required=True))
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
            "analyze": (
                "You are a pricing and promotions strategist. Review the product data and discount goals "
                "to determine the optimal discount approach without destroying margin or brand equity.\n\n"
                "Product Data: {product_data}\nDiscount Goals: {discount_goals}\n\n"
                "Assess: current margin headroom, price elasticity signals, competitive price position, "
                "inventory levels, and goal feasibility. Return a discount strategy assessment."
            ),
            "execute": (
                "Design a specific discount plan with projected financial impact.\n\n"
                "Product Data: {product_data}\nDiscount Goals: {discount_goals}\n\n"
                "Specify the discount type, amount, duration, eligibility, and mechanics. "
                "Project revenue and conversion impact. Return as JSON: "
                '{{"discount_plan": {{"type": str, "amount": float, "unit": str, "duration_days": int, "conditions": list, "mechanics": str}}, '
                '"expected_impact": {{"revenue_change_pct": float, "conversion_lift_pct": float, "margin_impact": float, "units_sold_delta": int}}}}'
            ),
            "enhance": (
                "Enrich the discount plan with creative promotional angles and urgency mechanics.\n\n"
                "Product Data: {product_data}\nDiscount Goals: {discount_goals}\n\n"
                "Add: promotional messaging, scarcity/urgency triggers, recommended channels for promotion, "
                "segment-specific variants (e.g., loyalty members vs. new customers), and A/B test recommendations."
            ),
            "validate": (
                "Validate the discount plan for financial soundness and goal alignment.\n\n"
                "Product Data: {product_data}\nDiscount Goals: {discount_goals}\n\n"
                "Check: Does the discount maintain positive margin? Are impact projections realistic? "
                "Does the plan meet the stated goals? Are there compliance or MAP policy concerns? "
                "Flag any financially risky discount levels."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_optimal_discount(cost: float, price: float, target_margin: float, max_discount_pct: float = 0.4) -> float:
        """Calculate the maximum discount percentage that maintains the target margin floor."""
        if price <= 0:
            return 0.0
        current_margin = (price - cost) / price
        if current_margin <= target_margin:
            return 0.0
        max_price_reduction = price * (current_margin - target_margin)
        optimal_discount_pct = min(max_price_reduction / price, max_discount_pct)
        return round(optimal_discount_pct, 4)

    @staticmethod
    def _estimate_revenue_impact(base_units: int, base_price: float, discount_pct: float, elasticity: float = -1.5) -> dict[str, float]:
        """Estimate revenue impact of a discount using price elasticity of demand."""
        price_change_pct = -discount_pct
        volume_change_pct = elasticity * price_change_pct
        new_units = base_units * (1 + volume_change_pct)
        new_price = base_price * (1 - discount_pct)
        base_revenue = base_units * base_price
        new_revenue = new_units * new_price
        return {
            "base_revenue": round(base_revenue, 2),
            "new_revenue": round(new_revenue, 2),
            "revenue_delta": round(new_revenue - base_revenue, 2),
            "revenue_change_pct": round((new_revenue - base_revenue) / base_revenue, 4) if base_revenue else 0.0,
            "new_units": round(new_units, 1),
        }
