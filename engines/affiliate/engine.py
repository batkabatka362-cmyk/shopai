"""
Affiliate Engine

Purpose: Design affiliate programs with optimized commission structures
Input:   ['product_data', 'affiliate_network']
Output:  ['affiliate_program', 'commission_structure']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AffiliateEngine(BaseEngine):
    engine_name = "affiliate"
    required_input_fields = ['product_data', 'affiliate_network']
    required_output_fields = ['affiliate_program', 'commission_structure']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze product margins and affiliate network landscape",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate affiliate program and commission structure",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance program with creative incentive ideas",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate commission rates and program economics",
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
            "analyze": """You are an affiliate marketing analyst. Analyze product data and affiliate network to design an optimal program.

Evaluate:
1. Product margins and maximum sustainable commission rates
2. Affiliate network size and quality
3. Competitor affiliate program benchmarks
4. Cookie duration and attribution model options
5. Fraud risk and prevention measures

Product data: {product_data}
Affiliate network: {affiliate_network}

Return: margin analysis, recommended commission tiers, network assessment, and risk factors.""",
            "execute": """Based on the analysis, generate a complete affiliate program and commission structure.

Analysis results: {analysis}
Product data: {product_data}
Affiliate network: {affiliate_network}

Provide:
- program_terms, cookie_duration, attribution_model
- commission_tiers (by product category, volume, performance)
- bonus_structures, payment_schedule
- tracking_requirements, creative_assets_needed

Return as structured JSON with affiliate_program and commission_structure objects.""",
            "enhance": """Enhance the affiliate program with creative incentive and growth strategies.

Add:
- Tiered performance bonuses
- Seasonal promotion calendars
- Exclusive affiliate perks
- Gamification elements

Current output: {execution}""",
            "validate": """Validate the affiliate program economics and compliance.

Check:
1. Commission rates don't exceed product margins
2. Payment terms are clearly defined
3. Cookie durations are competitive
4. FTC disclosure requirements are addressed
5. Fraud prevention measures are in place

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _calculate_commission_rate(product_price: float, product_cost: float, target_margin: float) -> float:
        if product_price == 0:
            return 0.0
        available_margin = (product_price - product_cost) / product_price
        max_commission = max(available_margin - target_margin, 0)
        return round(max_commission * 100, 2)

    @staticmethod
    def _estimate_affiliate_revenue(affiliates: int, avg_monthly_sales: float, commission_rate: float) -> dict:
        gross_revenue = affiliates * avg_monthly_sales
        commission_cost = gross_revenue * (commission_rate / 100)
        net_revenue = gross_revenue - commission_cost
        return {"gross_revenue": round(gross_revenue, 2), "commission_cost": round(commission_cost, 2), "net_revenue": round(net_revenue, 2)}
