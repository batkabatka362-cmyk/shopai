"""
PaymentOptimization Engine

Purpose: Optimize payment flows, reduce fees, and improve conversion rates
Input:   ['payment_data', 'gateway_options']
Output:  ['payment_flow', 'optimization_actions']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class PaymentOptimizationEngine(BaseEngine):
    engine_name = "payment_optimization"
    required_input_fields = ['payment_data', 'gateway_options']
    required_output_fields = ['payment_flow', 'optimization_actions']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze payment patterns and gateway performance",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate optimized payment flow and actions",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance with creative payment experience improvements",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate payment flow security and compliance",
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
            "analyze": """You are a payment optimization specialist. Analyze payment data and gateway options to improve conversion.

Evaluate:
1. Payment method distribution and success rates
2. Decline rates and reasons by gateway
3. Fee structures across gateways
4. Geographic payment preferences
5. Fraud rates and chargeback patterns

Payment data: {payment_data}
Gateway options: {gateway_options}

Return: payment performance analysis, fee comparison, decline pattern insights, and optimization opportunities.""",
            "execute": """Based on the analysis, generate an optimized payment flow and action plan.

Analysis results: {analysis}
Payment data: {payment_data}
Gateway options: {gateway_options}

Provide:
- primary_gateway, fallback_gateway, routing_rules
- payment_methods_to_add, methods_to_remove
- fee_reduction_actions, estimated_savings
- decline_recovery_strategies

Return as structured JSON with payment_flow and optimization_actions objects.""",
            "enhance": """Enhance the payment flow with creative conversion improvements.

Add:
- One-click checkout optimization
- Payment plan / BNPL suggestions
- Trust signal improvements
- Localized payment method recommendations

Current output: {execution}""",
            "validate": """Validate the payment optimization plan for security and compliance.

Check:
1. PCI DSS compliance is maintained
2. All gateways support required currencies
3. Fallback routing logic is sound
4. Fee calculations are accurate
5. Fraud prevention measures are adequate

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _calculate_conversion_rate(successful: int, attempted: int) -> float:
        if attempted == 0:
            return 0.0
        return round(successful / attempted * 100, 2)

    @staticmethod
    def _minimize_fees(transaction_amount: float, gateways: list[dict]) -> dict:
        best = None
        lowest_fee = float("inf")
        for gw in gateways:
            fee = gw.get("fixed_fee", 0) + transaction_amount * gw.get("percentage_fee", 0) / 100
            if fee < lowest_fee:
                lowest_fee = fee
                best = gw
        return {"gateway": best.get("name", "") if best else "", "fee": round(lowest_fee, 2), "savings_vs_avg": 0.0}
