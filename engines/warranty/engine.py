"""
Warranty Engine

Purpose: Design warranty programs and process warranty claims
Input:   ['product_data', 'warranty_config']
Output:  ['warranty_plans', 'claim_process']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class WarrantyEngine(BaseEngine):
    engine_name = "warranty"
    required_input_fields = ['product_data', 'warranty_config']
    required_output_fields = ['warranty_plans', 'claim_process']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze product reliability and warranty requirements",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate warranty plans and claim processes",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance warranty offerings with customer-friendly features",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate warranty terms and claim process compliance",
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
            "analyze": """You are a warranty program designer. Analyze product data and warranty requirements.

Evaluate:
1. Product failure rates and common defect types
2. Expected product lifespan by category
3. Competitor warranty offerings
4. Cost of warranty claims vs revenue from extended warranties
5. Legal requirements for warranty coverage

Product data: {product_data}
Warranty config: {warranty_config}

Return: risk assessment per product, warranty cost projections, competitive benchmarks, and program design recommendations.""",
            "execute": """Based on the analysis, generate warranty plans and claim process workflows.

Analysis results: {analysis}
Product data: {product_data}
Warranty config: {warranty_config}

For each product/category provide:
- warranty_type (standard, extended, premium)
- coverage_period, covered_defects, exclusions
- claim_steps, required_documentation
- replacement_vs_repair_policy, turnaround_time

Return as structured JSON with warranty_plans and claim_process arrays.""",
            "enhance": """Enhance the warranty program with customer-friendly features.

Add:
- No-questions-asked period
- Hassle-free claim digital flow
- Proactive warranty reminder notifications
- Extended warranty upsell suggestions

Current output: {execution}""",
            "validate": """Validate the warranty program for compliance and financial viability.

Check:
1. Warranty terms comply with consumer protection laws
2. Claim process is clear and reasonable
3. Cost projections are within acceptable margins
4. Coverage exclusions are clearly defined
5. Turnaround times are competitive

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _calculate_warranty_cost(product_price: float, failure_rate: float, avg_repair_cost: float) -> dict:
        expected_claims = failure_rate
        expected_cost = expected_claims * avg_repair_cost
        suggested_premium = expected_cost * 1.5
        margin = suggested_premium - expected_cost
        return {"expected_cost": round(expected_cost, 2), "suggested_premium": round(suggested_premium, 2), "margin": round(margin, 2), "break_even_rate": round(failure_rate * 1.5, 4)}

    @staticmethod
    def _evaluate_claim(purchase_date: str, warranty_months: int, issue_description: str) -> dict:
        from datetime import datetime, timedelta
        try:
            purchase = datetime.fromisoformat(purchase_date)
            expiry = purchase + timedelta(days=warranty_months * 30)
            within_warranty = datetime.now() <= expiry
            days_remaining = (expiry - datetime.now()).days
        except (ValueError, TypeError):
            within_warranty = False
            days_remaining = 0
        is_covered = within_warranty and not any(w in issue_description.lower() for w in ["misuse", "water damage", "dropped", "modified"])
        return {"within_warranty": within_warranty, "days_remaining": max(days_remaining, 0), "is_covered": is_covered}
