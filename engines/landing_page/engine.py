"""
LandingPageEngine
Purpose: Generate high-converting landing page content optimized for campaigns and products
Input: ['product_data', 'campaign_context']
Output: ['landing_page_content', 'optimization_suggestions']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class LandingPageEngine(BaseEngine):
    engine_name = "landing_page"
    required_input_fields = ["product_data", "campaign_context"]
    required_output_fields = ["landing_page_content", "optimization_suggestions"]

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
                "You are a conversion rate optimization and landing page expert. Review the product data and campaign context "
                "to understand what this landing page needs to achieve and what the target audience expects.\n\n"
                "Product Data: {product_data}\nCampaign Context: {campaign_context}\n\n"
                "Assess: primary conversion goal, target audience pain points, key value propositions to highlight, "
                "trust signals needed, and content hierarchy for maximum impact. Return a page strategy brief."
            ),
            "execute": (
                "Generate complete landing page content structured for high conversion.\n\n"
                "Product Data: {product_data}\nCampaign Context: {campaign_context}\n\n"
                "Create all content sections with persuasive copy. Return as JSON: "
                '{{"landing_page_content": {{"headline": str, "subheadline": str, "hero_copy": str, '
                '"benefit_bullets": list, "social_proof": str, "cta_primary": str, "cta_secondary": str, "faq": list}}, '
                '"optimization_suggestions": [{{"element": str, "suggestion": str, "expected_impact": str}}]}}'
            ),
            "enhance": (
                "Polish the landing page with power copywriting, emotional hooks, and conversion psychology.\n\n"
                "Product Data: {product_data}\nCampaign Context: {campaign_context}\n\n"
                "Rewrite the headline using the most compelling angle, strengthen benefit bullets with specificity, "
                "add urgency and scarcity elements, improve the CTA with action-oriented language, "
                "and suggest 3 A/B test headline variants."
            ),
            "validate": (
                "Validate the landing page content for conversion effectiveness and brand compliance.\n\n"
                "Product Data: {product_data}\nCampaign Context: {campaign_context}\n\n"
                "Check: Does the headline match the campaign ad message? Are claims accurate and substantiated? "
                "Is the CTA clear and singular? Is the content free of jargon? "
                "Does the page address the primary objection? Flag any conversion-killing elements."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_conversion_score(page_elements: dict[str, Any]) -> float:
        """Score landing page conversion potential based on presence of key CRO elements."""
        cro_elements = {
            "headline": 0.15,
            "hero_image": 0.10,
            "benefit_bullets": 0.15,
            "social_proof": 0.15,
            "cta_primary": 0.20,
            "trust_badges": 0.10,
            "urgency_element": 0.10,
            "mobile_optimized": 0.05,
        }
        score = 0.0
        for element, weight in cro_elements.items():
            if page_elements.get(element):
                score += weight
        return round(score, 4)

    @staticmethod
    def _generate_headline_variants(product_name: str, key_benefit: str, target_audience: str) -> list[str]:
        """Generate A/B test headline variants using different copywriting frameworks."""
        return [
            f"The {product_name} That {key_benefit}",
            f"Finally: A {product_name} Built for {target_audience}",
            f"Get {key_benefit} — Guaranteed or Your Money Back",
            f"Why {target_audience} Choose {product_name} Over Everything Else",
            f"Transform Your Results with {product_name}",
        ]
