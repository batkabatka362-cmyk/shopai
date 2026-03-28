"""
ProductSelection Engine

Purpose: Select winning products from candidates using market fit, margin, and trend scoring
Input:   ['products', 'criteria']
Output:  ['selected_products', 'rankings']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ProductSelectionEngine(BaseEngine):
    engine_name = "product_selection"
    required_input_fields = ['products', 'criteria']
    required_output_fields = ['selected_products', 'rankings']

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
            "analyze": """You are a product market analyst. Evaluate these product candidates for dropshipping/e-commerce viability.

For each product assess:
1. Market demand (search volume, trend direction)
2. Competition level (number of sellers, market saturation)
3. Profit margin potential (cost vs selling price)
4. Shipping feasibility (weight, size, fragility)
5. Legal/compliance risks

Products: {products}
Criteria: {criteria}

Return: score (0-10), decision (approve/reject), reason, and per-product breakdown.""",
            "execute": """Based on the analysis, select the top products and generate structured rankings.

Analysis results: {analysis}
Original products: {products}
Selection criteria: {criteria}

For each selected product provide:
- product_id, name, category
- market_score, margin_score, trend_score, total_score
- recommended_price_range
- target_audience
- key_selling_points (3-5 bullet points)

Return as structured JSON with selected_products and rankings arrays.""",
            "enhance": """Enhance the product selection output with compelling market positioning.

For each selected product, add:
- A hook sentence that captures attention
- Emotional benefit statement
- Unique selling proposition (USP)
- Suggested brand angle

Current selection: {execution}""",
            "validate": """Validate the product selection output for quality and consistency.

Check:
1. All selected products have complete scores
2. Rankings are properly ordered by total_score
3. No duplicate products
4. Margin scores are realistic (not negative, not >95%)
5. At least 1 product selected

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _calculate_margin_score(product: dict) -> float:
        cost = float(product.get("cost", 0))
        price = float(product.get("price", 0))
        if price == 0:
            return 0.0
        return round((price - cost) / price * 10, 2)

    @staticmethod
    def _calculate_trend_score(product: dict) -> float:
        search_volume = float(product.get("search_volume", 0))
        competition = float(product.get("competition", 1))
        if competition == 0:
            competition = 1
        return round(min(search_volume / competition, 10), 2)

    @staticmethod
    def _rank_products(products: list[dict], scores: dict[str, float]) -> list[dict]:
        for p in products:
            pid = p.get("id", p.get("name", ""))
            p["total_score"] = scores.get(pid, 0)
        return sorted(products, key=lambda x: x.get("total_score", 0), reverse=True)

