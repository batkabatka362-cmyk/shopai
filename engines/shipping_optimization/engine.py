"""
ShippingOptimization Engine

Purpose: Optimize shipping strategies, carrier selection, and cost reduction
Input:   ['order_data', 'carrier_options']
Output:  ['shipping_plan', 'cost_optimization']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ShippingOptimizationEngine(BaseEngine):
    engine_name = "shipping_optimization"
    required_input_fields = ['order_data', 'carrier_options']
    required_output_fields = ['shipping_plan', 'cost_optimization']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze order patterns and carrier capabilities",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate shipping plan and cost optimization strategy",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance with creative shipping experience ideas",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate shipping plan feasibility and cost accuracy",
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
            "analyze": """You are a shipping logistics expert. Analyze order data and carrier options to optimize shipping.

Evaluate:
1. Order volume patterns and geographic distribution
2. Package dimensions and weight distribution
3. Carrier service levels and reliability
4. Cost structures (flat rate, weight-based, zone-based)
5. Delivery time requirements and customer expectations

Order data: {order_data}
Carrier options: {carrier_options}

Return: shipping pattern analysis, carrier comparison, cost breakdown, and optimization opportunities.""",
            "execute": """Based on the analysis, generate an optimized shipping plan and cost reduction strategy.

Analysis results: {analysis}
Order data: {order_data}
Carrier options: {carrier_options}

For each order or order group provide:
- order_ids, selected_carrier, service_level
- estimated_cost, estimated_delivery_days
- packaging_recommendation, batch_shipping_opportunity

Return as structured JSON with shipping_plan and cost_optimization objects.""",
            "enhance": """Enhance the shipping plan with creative customer experience improvements.

Add:
- Branded packaging suggestions
- Shipping notification sequences
- Free shipping threshold optimization
- Eco-friendly shipping options

Current output: {execution}""",
            "validate": """Validate the shipping plan for feasibility and cost accuracy.

Check:
1. All orders have assigned carriers
2. Delivery estimates are realistic for service levels
3. Cost calculations include all fees and surcharges
4. No carrier service area gaps
5. Total savings projections are substantiated

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _calculate_shipping_cost(weight: float, zone: int, base_rate: float, per_lb_rate: float) -> float:
        zone_multiplier = 1.0 + (zone - 1) * 0.15
        cost = (base_rate + weight * per_lb_rate) * zone_multiplier
        return round(cost, 2)

    @staticmethod
    def _select_optimal_carrier(carriers: list[dict], weight: float, destination_zone: int, priority: str) -> dict:
        best = None
        best_score = float("inf")
        for carrier in carriers:
            cost = carrier.get("base_rate", 0) + weight * carrier.get("per_lb_rate", 0)
            speed = carrier.get("delivery_days", 7)
            score = cost * 0.6 + speed * 0.4 if priority == "cost" else cost * 0.3 + speed * 0.7
            if score < best_score:
                best_score = score
                best = carrier
        return best or {}
