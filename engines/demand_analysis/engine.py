"""
DemandAnalysis Engine — Analyze demand patterns, signals, and predict future demand
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class DemandAnalysisEngine(BaseEngine):
    engine_name = "demand_analysis"
    required_input_fields = ['demand_data', 'time_range']
    required_output_fields = ['demand_forecast', 'patterns']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze demand signals and historical patterns", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate demand forecast with confidence intervals", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Add narrative context to demand patterns", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate forecast accuracy metrics", required=True))
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
            "analyze": """Analyze demand patterns:\n- Historical sales velocity\n- Search trend data (Google Trends, social mentions)\n- Seasonal patterns\n- Geographic demand distribution\n- Price elasticity signals\n\nDemand data: {demand_data}\nTime range: {time_range}""",
            "execute": """Generate demand forecast:\n- Daily/weekly/monthly projections\n- Confidence intervals (low/mid/high)\n- Seasonal adjustment factors\n- Demand drivers ranked by impact\n- Anomaly flags\n\nAnalysis: {analysis}""",
            "enhance": """Add context: why demand is shifting, what external factors matter, emerging demand signals that aren't obvious from data alone.\n\nForecast: {execution}""",
            "validate": """Validate: forecasts are within reasonable bounds, confidence intervals widen appropriately, seasonal patterns are consistent with historical data.\n\nOutput: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\nData: " + str(data)

    @staticmethod
    def _moving_average(values: list[float], window: int = 7) -> list[float]:
        if len(values) < window:
            return values
        return [round(sum(values[i:i+window]) / window, 2) for i in range(len(values) - window + 1)]

    @staticmethod
    def _detect_seasonality(monthly_data: list[float]) -> dict[str, Any]:
        if len(monthly_data) < 12:
            return {"seasonal": False}
        avg = sum(monthly_data) / len(monthly_data)
        peaks = [i+1 for i, v in enumerate(monthly_data) if v > avg * 1.3]
        return {"seasonal": len(peaks) > 0, "peak_months": peaks, "avg": round(avg, 2)}
