"""
CrossSellEngine
Purpose: Recommend complementary products to cart items to increase basket size
Input: ['cart_items', 'customer_profile']
Output: ['cross_sell_recommendations', 'relevance_scores']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class CrossSellEngine(BaseEngine):
    engine_name = "cross_sell"
    required_input_fields = ["cart_items", "customer_profile"]
    required_output_fields = ["cross_sell_recommendations", "relevance_scores"]

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
                "You are a cross-sell and basket optimization expert. Analyze the cart contents and customer profile "
                "to identify what complementary products would naturally complete this purchase.\n\n"
                "Cart Items: {cart_items}\nCustomer Profile: {customer_profile}\n\n"
                "Assess: cart composition patterns, missing complementary items, customer preference history, "
                "price point comfort zone, and what makes the cart 'incomplete'. Return a cross-sell opportunity analysis."
            ),
            "execute": (
                "Generate ranked cross-sell recommendations for the current cart.\n\n"
                "Cart Items: {cart_items}\nCustomer Profile: {customer_profile}\n\n"
                "For each recommendation: compute relevance to specific cart items and customer fit. Return as JSON: "
                '{{"cross_sell_recommendations": [{{"product_id": str, "name": str, "price": float, '
                '"complements": list, "relevance_score": float, "reason": str}}], '
                '"relevance_scores": {{"top_recommendation": str, "avg_relevance": float, "expected_basket_lift": float}}}}'
            ),
            "enhance": (
                "Write compelling cross-sell copy that connects each recommendation to the cart context.\n\n"
                "Cart Items: {cart_items}\nCustomer Profile: {customer_profile}\n\n"
                "For each recommendation: craft a 'complete your purchase' message that references the specific cart items, "
                "highlights why this product pairs perfectly, and creates gentle urgency."
            ),
            "validate": (
                "Validate cross-sell recommendations for relevance and non-intrusiveness.\n\n"
                "Cart Items: {cart_items}\nCustomer Profile: {customer_profile}\n\n"
                "Check: Are recommendations genuinely complementary (not just random products)? "
                "Are prices appropriate for the cart context? Are recommendations diverse (not all same category)? "
                "Flag any recommendations that duplicate cart items or feel irrelevant."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_cross_sell_affinity(cart_item: dict[str, Any], candidate: dict[str, Any]) -> float:
        """Calculate cross-sell affinity between a cart item and a candidate product."""
        score = 0.0
        cart_cat = cart_item.get("category", "")
        cand_cat = candidate.get("category", "")
        if cart_cat and cand_cat and cart_cat != cand_cat:
            score += 0.25
        cart_tags = set(cart_item.get("tags", []))
        cand_tags = set(candidate.get("tags", []))
        if cart_tags and cand_tags:
            overlap = len(cart_tags & cand_tags) / len(cart_tags | cand_tags)
            score += 0.35 * overlap
        score += float(candidate.get("co_purchase_rate", 0)) * 0.4
        return round(min(score, 1.0), 4)

    @staticmethod
    def _rank_recommendations(candidates: list[dict[str, Any]], top_n: int = 5) -> list[dict[str, Any]]:
        """Return the top N cross-sell candidates sorted by relevance score."""
        sorted_candidates = sorted(candidates, key=lambda c: float(c.get("relevance_score", 0)), reverse=True)
        for i, candidate in enumerate(sorted_candidates[:top_n]):
            candidate["rank"] = i + 1
        return sorted_candidates[:top_n]
