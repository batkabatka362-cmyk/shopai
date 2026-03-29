"""
ProductLifecycleEngine
Purpose: Determine product lifecycle stage and generate stage-appropriate recommendations
Input: ['product_data', 'lifecycle_config']
Output: ['lifecycle_stage', 'lifecycle_recommendations']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ProductLifecycleEngine(BaseEngine):
    engine_name = "product_lifecycle"
    required_input_fields = ["product_data", "lifecycle_config"]
    required_output_fields = ["lifecycle_stage", "lifecycle_recommendations"]

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
                "You are a product lifecycle management expert. Review the product data and lifecycle configuration "
                "to classify this product's current stage (introduction, growth, maturity, or decline).\n\n"
                "Product Data: {product_data}\nLifecycle Config: {lifecycle_config}\n\n"
                "Assess: sales velocity trend, market penetration, competitive pressure, "
                "age since launch, and inventory turnover. Return a lifecycle stage assessment with supporting evidence."
            ),
            "execute": (
                "Determine the product lifecycle stage and generate tailored recommendations.\n\n"
                "Product Data: {product_data}\nLifecycle Config: {lifecycle_config}\n\n"
                "Classify the stage and provide specific recommendations for that stage. Return as JSON: "
                '{{"lifecycle_stage": {{"stage": str, "confidence": float, "stage_score": float, "days_in_stage": int}}, '
                '"lifecycle_recommendations": [{{"action": str, "rationale": str, "priority": str, "timeline": str}}]}}'
            ),
            "enhance": (
                "Enrich the lifecycle analysis with strategic narrative and transition planning.\n\n"
                "Product Data: {product_data}\nLifecycle Config: {lifecycle_config}\n\n"
                "Add: predicted time to next stage transition, early warning signals to monitor, "
                "competitive benchmarking context, and a staged action plan for the next 90 days."
            ),
            "validate": (
                "Validate the lifecycle stage classification and recommendations for accuracy.\n\n"
                "Product Data: {product_data}\nLifecycle Config: {lifecycle_config}\n\n"
                "Check: Is the stage classification supported by the data? Are the thresholds in the config applied correctly? "
                "Do recommendations match the classified stage? Flag any misclassifications or contradictory signals."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _determine_lifecycle_stage(sales_trend: float, market_share: float, age_days: int) -> str:
        """Classify a product's lifecycle stage based on sales trend, market share, and age."""
        if age_days < 90 and sales_trend > 0:
            return "introduction"
        if sales_trend > 0.05 and market_share < 0.4:
            return "growth"
        if -0.05 <= sales_trend <= 0.05 and market_share >= 0.3:
            return "maturity"
        if sales_trend < -0.05:
            return "decline"
        return "maturity"

    @staticmethod
    def _calculate_stage_score(product: dict[str, Any], stage: str) -> float:
        """Score how strongly a product fits its classified lifecycle stage (0-1)."""
        stage_signals: dict[str, list[str]] = {
            "introduction": ["low_reviews", "rising_views", "new_listing"],
            "growth": ["rising_sales", "expanding_reviews", "increasing_search_rank"],
            "maturity": ["stable_sales", "high_review_count", "strong_conversion"],
            "decline": ["falling_sales", "decreasing_views", "excess_inventory"],
        }
        signals = stage_signals.get(stage, [])
        if not signals:
            return 0.5
        matched = sum(1 for s in signals if product.get(s, False))
        return round(matched / len(signals), 4)
