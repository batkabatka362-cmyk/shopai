"""
Wishlist Engine

Purpose: Analyze wishlists to generate recommendations and price alerts
Input:   ['wishlist_data', 'user_profiles']
Output:  ['recommendations', 'notification_triggers']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class WishlistEngine(BaseEngine):
    engine_name = "wishlist"
    required_input_fields = ['wishlist_data', 'user_profiles']
    required_output_fields = ['recommendations', 'notification_triggers']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze wishlist patterns and user preferences",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate recommendations and notification triggers",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance recommendations with personalized messaging",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate recommendations relevance and trigger logic",
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
            "analyze": """You are a wishlist analytics expert. Analyze wishlist data and user profiles for conversion opportunities.

Evaluate:
1. Most wishlisted product categories and trends
2. Price sensitivity patterns (items added but not purchased)
3. Wishlist-to-purchase conversion rates
4. Seasonal wishlist activity patterns
5. Cross-user wishlist similarities for social proof

Wishlist data: {wishlist_data}
User profiles: {user_profiles}

Return: wishlist trends, conversion barriers, price sensitivity insights, and notification opportunity assessment.""",
            "execute": """Based on the analysis, generate product recommendations and notification triggers.

Analysis results: {analysis}
Wishlist data: {wishlist_data}
User profiles: {user_profiles}

For each user provide:
- user_id, recommended_products, recommendation_reason
- price_alert_thresholds, stock_alert_items
- notification_type, optimal_send_time
- conversion_probability

Return as structured JSON with recommendations and notification_triggers arrays.""",
            "enhance": """Enhance the recommendations with personalized and compelling messaging.

Add:
- Personalized recommendation explanations
- Social proof elements (X others wishlisted this)
- Limited-time offer suggestions
- Complementary product bundles

Current output: {execution}""",
            "validate": """Validate the recommendations and notification triggers.

Check:
1. Recommendations are relevant to user wishlist patterns
2. Price alert thresholds are reasonable
3. Notification frequency won't cause fatigue
4. All recommended products are in stock
5. Conversion probability estimates are calibrated

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _analyze_wishlist_patterns(wishlists: list[dict]) -> dict:
        category_counts: dict[str, int] = {}
        price_sum = 0.0
        total_items = 0
        for wl in wishlists:
            for item in wl.get("items", []):
                cat = item.get("category", "unknown")
                category_counts[cat] = category_counts.get(cat, 0) + 1
                price_sum += float(item.get("price", 0))
                total_items += 1
        avg_price = round(price_sum / total_items, 2) if total_items > 0 else 0
        top_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        return {"total_items": total_items, "avg_price": avg_price, "top_categories": dict(top_categories)}

    @staticmethod
    def _generate_price_alert(current_price: float, target_discount_pct: float) -> dict:
        target_price = current_price * (1 - target_discount_pct / 100)
        return {"current_price": current_price, "target_price": round(target_price, 2), "discount_needed": target_discount_pct, "alert_active": True}
