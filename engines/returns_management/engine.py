"""
ReturnsManagement Engine

Purpose: Process return requests and optimize return policies
Input:   ['return_requests', 'policy_config']
Output:  ['return_decisions', 'process_actions']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ReturnsManagementEngine(BaseEngine):
    engine_name = "returns_management"
    required_input_fields = ['return_requests', 'policy_config']
    required_output_fields = ['return_decisions', 'process_actions']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze return requests against policy rules",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate return decisions and process actions",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance with customer retention offers for returners",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate return decisions comply with policy",
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
            "analyze": """You are a returns management specialist. Analyze return requests against the configured return policy.

Evaluate:
1. Return eligibility (timeframe, condition, receipt)
2. Return reason categorization (defective, wrong item, changed mind, etc.)
3. Fraud risk indicators
4. Customer history and loyalty tier
5. Cost analysis (shipping, restocking, refurbishment)

Return requests: {return_requests}
Policy config: {policy_config}

Return: eligibility assessment, risk flags, cost projections, and policy compliance check.""",
            "execute": """Based on the analysis, generate return decisions and process actions.

Analysis results: {analysis}
Return requests: {return_requests}
Policy config: {policy_config}

For each return request provide:
- request_id, decision (approve/deny/partial), reason
- refund_amount, refund_method
- return_shipping_label, restocking_fee
- process_steps, estimated_completion

Return as structured JSON with return_decisions and process_actions arrays.""",
            "enhance": """Enhance the returns process with customer retention strategies.

For each return, add:
- Exchange suggestions as alternatives
- Store credit bonus incentives
- Follow-up satisfaction survey
- Win-back campaign trigger

Current output: {execution}""",
            "validate": """Validate return decisions for policy compliance and consistency.

Check:
1. All decisions comply with stated return policy
2. Refund amounts are correctly calculated
3. Fraud flags are properly handled
4. Customer communications are clear and empathetic
5. Process steps are complete and actionable

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _evaluate_return_eligibility(purchase_date: str, return_window_days: int, item_condition: str) -> dict:
        from datetime import datetime, timedelta
        try:
            purchase = datetime.fromisoformat(purchase_date)
            deadline = purchase + timedelta(days=return_window_days)
            within_window = datetime.now() <= deadline
        except (ValueError, TypeError):
            within_window = False
        condition_eligible = item_condition.lower() in ("new", "unopened", "defective", "damaged_in_shipping")
        eligible = within_window and condition_eligible
        return {"eligible": eligible, "within_window": within_window, "condition_acceptable": condition_eligible}

    @staticmethod
    def _calculate_return_cost(item_price: float, restocking_pct: float, shipping_cost: float) -> dict:
        restocking_fee = item_price * (restocking_pct / 100)
        total_cost = restocking_fee + shipping_cost
        refund_amount = item_price - restocking_fee
        return {"restocking_fee": round(restocking_fee, 2), "shipping_cost": round(shipping_cost, 2), "total_cost": round(total_cost, 2), "refund_amount": round(refund_amount, 2)}
