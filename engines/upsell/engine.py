"""
UpsellEngine
Purpose: Recommend higher-value product alternatives to increase average order value
Input: ['current_product', 'customer_profile']
Output: ['upsell_recommendations', 'upsell_scores']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class UpsellEngine(BaseEngine):
    engine_name = "upsell"
    required_input_fields = ["current_product", "customer_profile"]
    required_output_fields = ["upsell_recommendations", "upsell_scores"]

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
                "You are an upsell strategy expert. Analyze the current product and customer profile "
                "to identify which premium alternatives or upgrades would genuinely serve this customer better.\n\n"
                "Current Product: {current_product}\nCustomer Profile: {customer_profile}\n\n"
                "Assess: customer spending capacity, purchase history patterns, product tier gaps, "
                "feature upgrade value, and how much price increase the customer would likely accept. "
                "Return an upsell opportunity assessment."
            ),
            "execute": (
                "Generate ranked upsell recommendations tailored to this customer and product.\n\n"
                "Current Product: {current_product}\nCustomer Profile: {customer_profile}\n\n"
                "For each upsell candidate: compute a relevance and conversion probability score. "
                "Return as JSON: "
                '{{"upsell_recommendations": [{{"product_id": str, "name": str, "price": float, '
                '"price_delta": float, "key_upgrades": list, "upsell_score": float}}], '
                '"upsell_scores": {{"top_recommendation": str, "avg_score": float, "expected_aov_lift": float}}}}'
            ),
            "enhance": (
                "Craft persuasive upsell messaging for each recommendation.\n\n"
                "Current Product: {current_product}\nCustomer Profile: {customer_profile}\n\n"
                "For each upsell: write a one-line value hook, highlight the 2-3 most compelling upgrade benefits, "
                "frame the price difference as an investment, and suggest the optimal moment and channel for the upsell."
            ),
            "validate": (
                "Validate upsell recommendations for relevance and commercial integrity.\n\n"
                "Current Product: {current_product}\nCustomer Profile: {customer_profile}\n\n"
                "Check: Are recommendations genuinely better than the current product for this customer? "
                "Are price increases within acceptable range for the customer's segment? "
                "Are upsell scores calibrated? Flag any recommendations that feel pushy or irrelevant."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_upsell_score(candidate: dict[str, Any], customer: dict[str, Any], current_price: float) -> float:
        """Score an upsell candidate based on price tolerance, feature delta, and customer segment."""
        candidate_price = float(candidate.get("price", 0))
        if candidate_price <= current_price:
            return 0.0
        price_delta_ratio = (candidate_price - current_price) / max(current_price, 1)
        price_tolerance = float(customer.get("price_tolerance", 0.3))
        price_score = max(0.0, 1.0 - (price_delta_ratio / max(price_tolerance, 0.01)))
        feature_score = float(candidate.get("feature_upgrade_score", 0.5))
        affinity_score = float(candidate.get("category_affinity", 0.5))
        return round((price_score * 0.4) + (feature_score * 0.35) + (affinity_score * 0.25), 4)

    @staticmethod
    def _filter_upsell_candidates(candidates: list[dict[str, Any]], current_price: float, max_premium_pct: float = 0.5) -> list[dict[str, Any]]:
        """Filter upsell candidates to those within acceptable price premium range."""
        max_price = current_price * (1 + max_premium_pct)
        return [c for c in candidates if current_price < float(c.get("price", 0)) <= max_price]
