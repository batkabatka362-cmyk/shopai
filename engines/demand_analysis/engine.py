"""
DemandAnalysis Engine — Analyze demand patterns — seasonality, velocity, geographic distribution, price elasticity
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
        templates = {"analyze": """Analyze demand patterns:\n- Volume trends over time\n- Seasonality detection (weekly, monthly, annual)\n- Geographic distribution of demand\n- Price sensitivity / elasticity indicators\n- Demand velocity (acceleration/deceleration)\n- Correlated demand (complementary products)\n- Leading indicators\n\nDemand data: {demand_data}\nTime range: {time_range}""", "execute": """Generate demand intelligence:\n- Demand forecast (next 30/60/90 days)\n- Seasonal multipliers by period\n- Price elasticity coefficient\n- Geographic heat map data\n- Stock-out risk per product\n- Demand clustering (which products move together)\n\nAnalysis: {analysis}""", "enhance": """Enhance with demand narratives:\n- Why is demand shifting?\n- Cultural/social drivers\n- Upcoming events that may spike demand\n\nForecast: {execution}""", "validate": """Validate: forecast within historical variance, seasonality patterns consistent, no impossible growth projections.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _moving_average(values: list[float], window: int = 7) -> list[float]:
        if len(values) < window: return values
        result = []
        for i in range(len(values) - window + 1):
            avg = sum(values[i:i+window]) / window
            result.append(round(avg, 2))
        return result

    @staticmethod
    def _seasonality_index(period_value: float, avg_value: float) -> float:
        if avg_value == 0: return 1.0
        return round(period_value / avg_value, 3)

    @staticmethod
    def _price_elasticity(pct_qty_change: float, pct_price_change: float) -> float:
        if pct_price_change == 0: return 0.0
        return round(pct_qty_change / pct_price_change, 3)

    @staticmethod
    def _demand_velocity(current: float, previous: float) -> str:
        if previous == 0: return "new"
        ratio = current / previous
        if ratio > 1.2: return "accelerating"
        if ratio > 0.95: return "stable"
        if ratio > 0.7: return "decelerating"
        return "declining"
