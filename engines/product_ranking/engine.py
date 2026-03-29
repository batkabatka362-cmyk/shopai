"""
ProductRankingEngine
Purpose: Rank products using configurable criteria to surface best-performing items
Input: ['products', 'ranking_criteria']
Output: ['ranked_products', 'ranking_scores']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ProductRankingEngine(BaseEngine):
    engine_name = "product_ranking"
    required_input_fields = ["products", "ranking_criteria"]
    required_output_fields = ["ranked_products", "ranking_scores"]

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
                "You are a product merchandising expert. Review the product catalog and ranking criteria "
                "to understand how products should be evaluated and what signals are most predictive of success.\n\n"
                "Products: {products}\nRanking Criteria: {ranking_criteria}\n\n"
                "Assess: criteria weights, data completeness per product, potential ranking conflicts, "
                "and which metrics are most correlated with customer value. Return a ranking strategy."
            ),
            "execute": (
                "Apply the ranking criteria to score and rank all products.\n\n"
                "Products: {products}\nRanking Criteria: {ranking_criteria}\n\n"
                "For each product: compute a composite rank score from the criteria weights. "
                "Return the products in ranked order with scores. Return as JSON: "
                '{{"ranked_products": [{{"id": str, "name": str, "rank": int, "score": float}}], '
                '"ranking_scores": {{"top_product": str, "score_distribution": dict, "criteria_breakdown": dict}}}}'
            ),
            "enhance": (
                "Enrich the ranked product list with merchandising insights and display recommendations.\n\n"
                "Products: {products}\nRanking Criteria: {ranking_criteria}\n\n"
                "For top-ranked products: add positioning rationale, suggested placement context (homepage, category, search), "
                "and highlight what makes each product stand out. Flag products that rank high on one criterion but low on others."
            ),
            "validate": (
                "Validate the product rankings for correctness and business alignment.\n\n"
                "Products: {products}\nRanking Criteria: {ranking_criteria}\n\n"
                "Check: Are scores correctly computed from the criteria? Are rankings consistent with business intuition? "
                "Are any products incorrectly penalized or boosted? Flag anomalies or ties that need tiebreaker rules."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_rank_score(product: dict[str, Any], criteria: dict[str, float]) -> float:
        """Compute a weighted composite rank score for a product from criteria weights."""
        score = 0.0
        total_weight = sum(criteria.values())
        if total_weight == 0:
            return 0.0
        for field, weight in criteria.items():
            value = float(product.get(field, 0.0))
            score += (weight / total_weight) * value
        return round(score, 4)

    @staticmethod
    def _apply_ranking_rules(products: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply boost/bury rules to adjust product rank scores before final ordering."""
        for rule in rules:
            condition_field = rule.get("field")
            condition_value = rule.get("value")
            boost = float(rule.get("boost", 0.0))
            for product in products:
                if product.get(condition_field) == condition_value:
                    product["score"] = round(float(product.get("score", 0.0)) + boost, 4)
        return sorted(products, key=lambda p: p.get("score", 0.0), reverse=True)
