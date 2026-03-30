"""
ProductOptimizationEngine
Purpose: Identify optimization opportunities and generate action plans to improve product performance
Input: ['product_data', 'optimization_goals']
Output: ['optimized_product', 'optimization_actions']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ProductOptimizationEngine(BaseEngine):
    engine_name = "product_optimization"
    required_input_fields = ["product_data", "optimization_goals"]
    required_output_fields = ["optimized_product", "optimization_actions"]

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
                "You are a product optimization specialist. Review the product data and optimization goals "
                "to identify the highest-impact improvement opportunities across content, pricing, SEO, and conversion.\n\n"
                "Product Data: {product_data}\nOptimization Goals: {optimization_goals}\n\n"
                "Assess: content quality gaps, pricing position vs. competitors, search visibility, "
                "conversion rate vs. category benchmark, and image/media quality. Return a prioritized gap analysis."
            ),
            "execute": (
                "Generate an optimized product profile and a prioritized list of optimization actions.\n\n"
                "Product Data: {product_data}\nOptimization Goals: {optimization_goals}\n\n"
                "Produce the optimized product attributes and concrete actions. Return as JSON: "
                '{{"optimized_product": {{"title": str, "description": str, "price": float, "tags": list, "attributes": dict}}, '
                '"optimization_actions": [{{"action": str, "field": str, "current_value": str, "recommended_value": str, "expected_impact": str}}]}}'
            ),
            "enhance": (
                "Polish the optimized product with compelling copywriting and conversion-focused enhancements.\n\n"
                "Product Data: {product_data}\nOptimization Goals: {optimization_goals}\n\n"
                "Rewrite the title with power words and primary keywords, enhance the description with benefit-driven language, "
                "suggest A/B test variations for key elements, and add social proof angles."
            ),
            "validate": (
                "Validate the optimized product and action plan for quality and goal alignment.\n\n"
                "Product Data: {product_data}\nOptimization Goals: {optimization_goals}\n\n"
                "Check: Does the optimized product meet the stated goals? Are actions specific and measurable? "
                "Is the content accurate and compliant? Are there any regressions vs. the original? "
                "Confirm expected impact estimates are reasonable."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _score_optimization_opportunity(product: dict[str, Any], goal: str) -> float:
        """Score how much optimization opportunity exists for a product on a given goal dimension."""
        opportunity_signals: dict[str, list[str]] = {
            "conversion": ["low_conversion_rate", "poor_images", "weak_description"],
            "visibility": ["low_search_rank", "missing_keywords", "no_reviews"],
            "revenue": ["below_market_price", "high_return_rate", "low_margin"],
        }
        signals = opportunity_signals.get(goal, [])
        if not signals:
            return 0.5
        matched = sum(1 for s in signals if product.get(s, False))
        return round(matched / len(signals), 4)

    @staticmethod
    def _generate_optimization_plan(gaps: list[dict[str, Any]], budget: str = "medium") -> list[dict[str, Any]]:
        """Generate a phased optimization plan from identified gaps, respecting budget constraints."""
        effort_map = {"low": 1, "medium": 2, "high": 3}
        budget_limit = effort_map.get(budget, 2)
        actionable = [g for g in gaps if effort_map.get(g.get("effort", "medium"), 2) <= budget_limit]
        return sorted(actionable, key=lambda g: float(g.get("impact_score", 0)), reverse=True)
