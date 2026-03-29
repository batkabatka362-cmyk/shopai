"""
StockPredictionEngine
Purpose: Forecast future stock requirements and generate reorder recommendations to prevent stockouts
Input: ['sales_history', 'demand_signals']
Output: ['stock_predictions', 'reorder_recommendations']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class StockPredictionEngine(BaseEngine):
    engine_name = "stock_prediction"
    required_input_fields = ["sales_history", "demand_signals"]
    required_output_fields = ["stock_predictions", "reorder_recommendations"]

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
                "You are an inventory planning and demand forecasting expert. Analyze the sales history and demand signals "
                "to understand demand patterns, seasonality, and forecast confidence.\n\n"
                "Sales History: {sales_history}\nDemand Signals: {demand_signals}\n\n"
                "Assess: sales velocity trends, seasonal patterns, demand signal reliability, "
                "supply lead times, stockout risk, and overstock risk. Return a demand pattern assessment."
            ),
            "execute": (
                "Generate stock predictions and reorder recommendations based on demand forecasting.\n\n"
                "Sales History: {sales_history}\nDemand Signals: {demand_signals}\n\n"
                "Forecast demand by period and calculate reorder points and quantities. Return as JSON: "
                '{{"stock_predictions": [{{"sku": str, "period": str, "predicted_demand": int, "confidence": float, "current_stock": int, "days_of_stock": float}}], '
                '"reorder_recommendations": [{{"sku": str, "reorder_point": int, "reorder_quantity": int, "urgency": str, "estimated_stockout_date": str}}]}}'
            ),
            "enhance": (
                "Enrich the stock predictions with risk narratives and procurement optimization advice.\n\n"
                "Sales History: {sales_history}\nDemand Signals: {demand_signals}\n\n"
                "For each SKU: explain the demand drivers behind the forecast, quantify the financial risk of stockout, "
                "suggest safety stock levels, and recommend supplier timing windows. "
                "Highlight any products with unusually high demand uncertainty."
            ),
            "validate": (
                "Validate the stock predictions and reorder recommendations for accuracy and feasibility.\n\n"
                "Sales History: {sales_history}\nDemand Signals: {demand_signals}\n\n"
                "Check: Are demand forecasts consistent with historical patterns? Are reorder quantities financially viable? "
                "Are urgency classifications appropriate? Are there any SKUs with insufficient history for reliable forecasting? "
                "Flag overconfident predictions or unrealistic reorder timelines."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_reorder_point(avg_daily_sales: float, lead_time_days: int, safety_stock_days: int = 7) -> int:
        """Calculate the reorder point as the stock level at which a new order should be placed."""
        return max(0, round((avg_daily_sales * lead_time_days) + (avg_daily_sales * safety_stock_days)))

    @staticmethod
    def _estimate_demand_forecast(sales_history: list[float], periods_ahead: int = 4, smoothing: float = 0.3) -> list[float]:
        """Estimate future demand using exponential smoothing on historical sales data."""
        if not sales_history:
            return [0.0] * periods_ahead
        smoothed = sales_history[0]
        for value in sales_history[1:]:
            smoothed = smoothing * value + (1 - smoothing) * smoothed
        trend = 0.0
        if len(sales_history) >= 2:
            recent_avg = sum(sales_history[-4:]) / len(sales_history[-4:])
            older_avg = sum(sales_history[:4]) / len(sales_history[:4])
            if older_avg > 0:
                trend = (recent_avg - older_avg) / (len(sales_history) * older_avg)
        forecasts = []
        current = smoothed
        for i in range(periods_ahead):
            current = current * (1 + trend)
            forecasts.append(round(max(current, 0.0), 2))
        return forecasts
