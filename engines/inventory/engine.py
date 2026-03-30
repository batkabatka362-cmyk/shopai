"""
Inventory Engine

Purpose: Track stock levels, predict demand, and generate reorder recommendations
Input:   ['stock_data', 'sales_data']
Output:  ['stock_status', 'reorder_recommendations']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class InventoryEngine(BaseEngine):
    engine_name = "inventory"
    required_input_fields = ['stock_data', 'sales_data']
    required_output_fields = ['stock_status', 'reorder_recommendations']

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
            "analyze": """Analyze inventory status. For each SKU calculate:
- Current stock level vs avg daily sales
- Days of stock remaining
- Stock status: critical (<3d), low (<7d), healthy (<30d), overstocked (>30d)
- Sell-through rate
- Dead stock identification (no sales in 30+ days)

Stock: {stock_data}
Sales: {sales_data}""",
            "execute": """Generate reorder recommendations:
- Reorder point per SKU (lead_time + safety_stock buffer)
- Recommended order quantity
- Priority ranking (critical first)
- Estimated cost for reorder
- Bundle slow-movers with fast-movers suggestions

Analysis: {analysis}""",
            "enhance": """Add business insights:
- Cash flow impact of recommended orders
- Seasonal adjustment suggestions
- Supplier consolidation opportunities

Recommendations: {execution}""",
            "validate": """Validate: reorder points are positive, quantities make sense, no conflicting recommendations (e.g., reorder dead stock).

Output: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_days_of_stock(current_qty: int, avg_daily_sales: float) -> float:
        if avg_daily_sales <= 0:
            return float("inf")
        return round(current_qty / avg_daily_sales, 1)

    @staticmethod
    def _calculate_reorder_point(avg_daily_sales: float, lead_time_days: int, safety_stock_days: int = 7) -> int:
        return int(avg_daily_sales * (lead_time_days + safety_stock_days))

    @staticmethod
    def _classify_stock_status(days_remaining: float) -> str:
        if days_remaining <= 3:
            return "critical"
        elif days_remaining <= 7:
            return "low"
        elif days_remaining <= 30:
            return "healthy"
        else:
            return "overstocked"

    @staticmethod
    def _calculate_reorder_qty(avg_daily_sales: float, target_days: int = 30) -> int:
        return max(1, int(avg_daily_sales * target_days))

