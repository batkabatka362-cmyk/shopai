"""
GiftCard Engine

Purpose: Design gift card programs and promotional strategies
Input:   ['store_data', 'campaign_config']
Output:  ['gift_card_program', 'promotion_plan']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class GiftCardEngine(BaseEngine):
    engine_name = "gift_card"
    required_input_fields = ['store_data', 'campaign_config']
    required_output_fields = ['gift_card_program', 'promotion_plan']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze store data and gift card program viability",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate gift card program and promotion plan",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance with creative gift card designs and campaigns",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate program economics and legal compliance",
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
            "analyze": """You are a gift card program strategist. Analyze store data and campaign configuration.

Evaluate:
1. Average order value and product price distribution
2. Seasonal gifting patterns and peak periods
3. Competitor gift card offerings
4. Digital vs physical card preferences
5. Breakage rate estimates and revenue impact

Store data: {store_data}
Campaign config: {campaign_config}

Return: program viability, denomination recommendations, seasonal calendar, and revenue projections.""",
            "execute": """Based on the analysis, generate a gift card program and promotion plan.

Analysis results: {analysis}
Store data: {store_data}
Campaign config: {campaign_config}

Provide:
- denominations, custom_amount_options
- card_types (digital, physical, e-gift)
- expiration_policy, terms_and_conditions
- promotion_calendar, bundle_offers
- distribution_channels

Return as structured JSON with gift_card_program and promotion_plan objects.""",
            "enhance": """Enhance the gift card program with creative design and marketing ideas.

Add:
- Themed card designs for holidays/occasions
- Gift card + product bundle suggestions
- Corporate bulk purchase program
- Referral-based gift card rewards

Current output: {execution}""",
            "validate": """Validate the gift card program for compliance and economics.

Check:
1. Expiration policies comply with local laws (CARD Act)
2. Denominations align with average order value
3. Breakage revenue projections are realistic
4. Terms and conditions are clear and fair
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
    def _calculate_breakage_rate(total_issued: float, total_redeemed: float) -> float:
        if total_issued == 0:
            return 0.0
        return round((total_issued - total_redeemed) / total_issued * 100, 2)

    @staticmethod
    def _optimize_denominations(avg_order_value: float, price_range: tuple[float, float]) -> list[float]:
        denominations = []
        base = round(avg_order_value * 0.5, -1) or 10
        denominations.append(max(base, price_range[0]))
        denominations.append(round(avg_order_value, -1) or 25)
        denominations.append(round(avg_order_value * 1.5, -1) or 50)
        denominations.append(round(avg_order_value * 2.5, -1) or 100)
        return sorted(set(d for d in denominations if d >= 5))
