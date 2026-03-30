"""
ProductValidation Engine

Purpose: Validate product viability before listing — checks legal, supply, demand, and profitability
Input:   ['product_data', 'market_data']
Output:  ['validation_result', 'viability_score']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ProductValidationEngine(BaseEngine):
    engine_name = "product_validation"
    required_input_fields = ['product_data', 'market_data']
    required_output_fields = ['validation_result', 'viability_score']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze input and assess viability",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate structured domain output",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance output with creative insights",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate output quality and consistency",
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
            "analyze": """Validate this product for e-commerce viability.

Run these checks:
1. Legal compliance (restricted categories, age restrictions, certifications needed)
2. Trademark risk (brand name conflicts, patent issues)
3. Supply reliability (supplier track record, lead times, MOQ)
4. Demand confirmation (search trends, social proof, competitor sales)
5. Margin viability (cost + shipping + fees vs selling price, target >30%)
6. Shipping feasibility (weight, dimensions, fragility, customs)
7. Return risk (category return rates, defect likelihood)
8. Seasonality risk (is demand seasonal? timing considerations)

Product: {product_data}
Market context: {market_data}""",
            "execute": """Based on the validation analysis, produce a structured validation report.

For each check: status (pass/warn/fail), score (0-10), specific notes.
Calculate overall viability_score (0-10).
Provide go/no-go recommendation with conditions.

Analysis: {analysis}""",
            "enhance": """Enhance the validation report with actionable recommendations.

For each "warn" or "fail" check, suggest:
- Specific mitigation steps
- Alternative approaches
- Risk-reward tradeoff

Report: {execution}""",
            "validate": """Final validation of the report:
1. All 8 checks have status, score, and notes
2. Viability score calculated correctly
3. Go/no-go recommendation is consistent with scores
4. No contradictions (e.g., "fail" on legal but "go" recommendation)

Report: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    VALIDATION_CHECKS = [
        "legal_compliance", "trademark_risk", "supply_reliability",
        "demand_confirmation", "margin_viability", "shipping_feasibility",
        "return_risk", "seasonality_risk",
    ]

    @classmethod
    def _run_checks(cls, product: dict, market: dict) -> dict[str, dict]:
        results = {}
        for check in cls.VALIDATION_CHECKS:
            results[check] = {"status": "pending", "score": 0, "notes": ""}
        # Basic auto-checks
        price = float(product.get("price", 0))
        cost = float(product.get("cost", 0))
        if price > 0 and cost > 0:
            margin = (price - cost) / price
            results["margin_viability"] = {
                "status": "pass" if margin > 0.3 else "warn" if margin > 0.15 else "fail",
                "score": round(margin * 10, 2),
                "notes": f"Margin: {margin:.1%}",
            }
        return results

    @staticmethod
    def _calculate_viability(checks: dict) -> float:
        scores = [c.get("score", 0) for c in checks.values()]
        return round(sum(scores) / len(scores), 2) if scores else 0

