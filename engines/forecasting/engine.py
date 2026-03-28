"""
Forecasting Engine — Forecast sales, revenue, trends, and demand with confidence intervals
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ForecastingEngine(BaseEngine):
    engine_name = "forecasting"
    required_input_fields = ['historical_data', 'forecast_params']
    required_output_fields = ['forecast', 'confidence_intervals']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze historical patterns for forecasting", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate multi-horizon forecasts", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Add scenario narratives", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate forecast statistical soundness", required=True))
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
            "analyze": """Analyze historical data for forecasting:\n- Identify trend (up/down/flat)\n- Detect seasonality and cycles\n- Find outliers and their causes\n- Assess data quality and completeness\n\nHistorical: {historical_data}\nParams: {forecast_params}""",
            "execute": """Generate forecasts:\n- Short-term (7d), medium (30d), long-term (90d)\n- Point estimates with confidence intervals (80%, 95%)\n- Best/worst/most-likely scenarios\n- Key assumptions listed\n\nAnalysis: {analysis}""",
            "enhance": """Add strategic context: what could change the forecast, what signals to watch, what actions could improve the trajectory.\n\nForecast: {execution}""",
            "validate": """Validate: confidence intervals widen with horizon, historical fit is reasonable, scenarios are internally consistent, assumptions are stated.\n\nOutput: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\nData: " + str(data)

    @staticmethod
    def _simple_forecast(values: list[float], periods: int = 7) -> list[float]:
        if not values:
            return [0.0] * periods
        avg = sum(values[-7:]) / min(len(values), 7)
        trend = 0.0
        if len(values) >= 14:
            recent = sum(values[-7:]) / 7
            prior = sum(values[-14:-7]) / 7
            trend = (recent - prior) / prior if prior else 0
        return [round(avg * (1 + trend * i), 2) for i in range(periods)]

    @staticmethod
    def _confidence_band(point: float, confidence: float = 0.95) -> tuple[float, float]:
        margin = point * (1 - confidence)
        return (round(point - margin, 2), round(point + margin, 2))
