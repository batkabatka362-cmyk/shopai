"""
BundleEngine
Purpose: Identify high-affinity product bundles and estimate bundle value to increase AOV
Input: ['products', 'bundle_criteria']
Output: ['bundle_recommendations', 'bundle_scores']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class BundleEngine(BaseEngine):
    engine_name = "bundle"
    required_input_fields = ["products", "bundle_criteria"]
    required_output_fields = ["bundle_recommendations", "bundle_scores"]

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
                "You are a merchandising and bundling strategist. Analyze the product catalog and bundle criteria "
                "to identify which products have high co-purchase affinity and would form compelling bundles.\n\n"
                "Products: {products}\nBundle Criteria: {bundle_criteria}\n\n"
                "Assess: co-purchase signals, complementary use cases, price point compatibility, "
                "inventory availability, and bundle margin potential. Return a bundling opportunity assessment."
            ),
            "execute": (
                "Generate specific bundle recommendations with scoring based on the criteria.\n\n"
                "Products: {products}\nBundle Criteria: {bundle_criteria}\n\n"
                "Create concrete bundle combinations with rationale and value estimates. Return as JSON: "
                '{{"bundle_recommendations": [{{"bundle_id": str, "products": list, "bundle_price": float, '
                '"savings_pct": float, "use_case": str, "affinity_score": float}}], '
                '"bundle_scores": {{"top_bundle": str, "avg_affinity": float, "projected_aov_lift": float}}}}'
            ),
            "enhance": (
                "Enrich bundle recommendations with compelling names, stories, and marketing angles.\n\n"
                "Products: {products}\nBundle Criteria: {bundle_criteria}\n\n"
                "For each bundle: create a memorable name, write a value proposition sentence, "
                "suggest seasonal or occasion-based positioning, and recommend display placements."
            ),
            "validate": (
                "Validate bundle recommendations for feasibility and value proposition strength.\n\n"
                "Products: {products}\nBundle Criteria: {bundle_criteria}\n\n"
                "Check: Are bundled products actually complementary? Is the bundle price attractive vs. individual prices? "
                "Is margin maintained? Are all products available? Flag any bundles with weak rationale or poor economics."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_bundle_affinity(product_a: dict[str, Any], product_b: dict[str, Any]) -> float:
        """Calculate co-purchase affinity score between two products (0-1)."""
        score = 0.0
        if product_a.get("category") == product_b.get("category"):
            score += 0.3
        price_a = float(product_a.get("price", 0))
        price_b = float(product_b.get("price", 0))
        if price_a > 0 and price_b > 0:
            ratio = min(price_a, price_b) / max(price_a, price_b)
            score += 0.2 * ratio
        tags_a = set(product_a.get("tags", []))
        tags_b = set(product_b.get("tags", []))
        if tags_a and tags_b:
            overlap = len(tags_a & tags_b) / len(tags_a | tags_b)
            score += 0.3 * overlap
        score += float(product_a.get("co_purchase_score", 0)) * 0.2
        return round(min(score, 1.0), 4)

    @staticmethod
    def _estimate_bundle_value(products: list[dict[str, Any]], discount_pct: float = 0.1) -> dict[str, float]:
        """Estimate the bundle price and customer savings vs. purchasing individually."""
        individual_total = sum(float(p.get("price", 0)) for p in products)
        bundle_price = individual_total * (1 - discount_pct)
        savings = individual_total - bundle_price
        return {
            "individual_total": round(individual_total, 2),
            "bundle_price": round(bundle_price, 2),
            "savings": round(savings, 2),
            "savings_pct": round(discount_pct, 4),
        }
