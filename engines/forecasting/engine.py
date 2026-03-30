"""
Forecasting Engine — Forecast sales, revenue, trends using statistical and AI methods
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
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Domain analysis", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate structured output", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Creative enhancement", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Quality validation", required=True))
        self.flow.register_executor("validate", self._step_validate)

    def _step_analyze(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("analyze", data)
        r = self._model_router.execute("analyzer", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"analysis": r})

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("execute", data)
        r = self._model_router.execute("worker", prompt, context=data)
        return StepResult(step_name=step_name, model_used="qwen", status=EngineStatus.COMPLETED, output={"execution": r})

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("enhance", data)
        r = self._model_router.execute("creative", prompt, context=data)
        return StepResult(step_name=step_name, model_used="llama", status=EngineStatus.COMPLETED, output={"enhanced": r})

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("validate", data)
        r = self._model_router.execute("validator", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"validation": r})

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        templates = {"analyze": """Analyze historical data for forecasting:\n- Time series patterns\n- Trend direction and strength\n- Seasonality components\n- Outlier detection\n- External factor correlations\n- Data quality assessment\n- Appropriate model selection\n\nHistorical: {historical_data}\nParams: {forecast_params}""", "execute": """Generate forecasts:\n- Point forecast (30/60/90 day)\n- Confidence intervals (80%, 95%)\n- Best/worst/likely scenarios\n- Key assumptions listed\n- Accuracy estimate based on historical backtest\n- Risk factors that could invalidate forecast\n\nAnalysis: {analysis}""", "enhance": """Enhance with narrative:\n- What drives the forecast direction?\n- Leading indicators to watch\n- Early warning signals if forecast is wrong\n\nForecast: {execution}""", "validate": """Validate: intervals are reasonable, point forecast within intervals, assumptions are explicit, no overfitting signals.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _simple_moving_avg_forecast(values: list[float], periods: int = 7) -> float:
        if not values: return 0.0
        window = values[-periods:] if len(values) >= periods else values
        return round(sum(window) / len(window), 2)

    @staticmethod
    def _exponential_smoothing(values: list[float], alpha: float = 0.3) -> float:
        if not values: return 0.0
        result = values[0]
        for v in values[1:]:
            result = alpha * v + (1 - alpha) * result
        return round(result, 2)

    @staticmethod
    def _confidence_interval(forecast: float, std_dev: float, z: float = 1.96) -> tuple[float, float]:
        margin = z * std_dev
        return (round(forecast - margin, 2), round(forecast + margin, 2))

    @staticmethod
    def _mape(actuals: list[float], predictions: list[float]) -> float:
        if not actuals or not predictions: return 0.0
        errors = []
        for a, p in zip(actuals, predictions):
            if a != 0:
                errors.append(abs(a - p) / abs(a))
        return round(sum(errors) / max(len(errors), 1) * 100, 2)
