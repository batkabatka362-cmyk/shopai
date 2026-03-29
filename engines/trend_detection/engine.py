"""
TrendDetectionEngine
Purpose: Detect and analyze market trends from time-series data
Input: ['market_data', 'time_range']
Output: ['trends', 'trend_scores']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class TrendDetectionEngine(BaseEngine):
    engine_name = "trend_detection"
    required_input_fields = ["market_data", "time_range"]
    required_output_fields = ["trends", "trend_scores"]

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
                "You are a market trend analyst. Examine the following market data over the specified time range "
                "and identify emerging patterns, momentum shifts, and notable signals.\n\n"
                "Market Data: {market_data}\nTime Range: {time_range}\n\n"
                "Analyze: velocity of change, directional bias, seasonality, and outlier signals. "
                "Return a structured assessment of what trends are forming."
            ),
            "execute": (
                "Based on the trend analysis, extract and label the top trends from the market data.\n\n"
                "Market Data: {market_data}\nTime Range: {time_range}\n\n"
                "For each identified trend provide: name, description, supporting data points, "
                "direction (rising/falling/stable), and a confidence score 0-1. "
                "Return as a JSON list of trend objects with fields: "
                '{{\"name\": str, \"description\": str, \"direction\": str, \"confidence\": float, \"data_points\": list}}'
            ),
            "enhance": (
                "Enrich the detected trends with narrative context and business implications.\n\n"
                "Market Data: {market_data}\nTime Range: {time_range}\n\n"
                "For each trend, add: why it matters, who it affects, and what opportunities it signals. "
                "Make the trend descriptions actionable and compelling for business decision-makers."
            ),
            "validate": (
                "Validate the identified trends for statistical soundness and business relevance.\n\n"
                "Market Data: {market_data}\nTime Range: {time_range}\n\n"
                "Check: Are trends supported by sufficient data points? Are confidence scores calibrated? "
                "Are there contradicting signals? Flag any trends that appear spurious or over-fitted. "
                "Return validation status and any corrections needed."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_trend_velocity(data_points: list[float], window: int = 5) -> float:
        """Calculate the rate of change (velocity) of a trend over the given window."""
        if len(data_points) < 2:
            return 0.0
        recent = data_points[-window:] if len(data_points) >= window else data_points
        if len(recent) < 2:
            return 0.0
        return (recent[-1] - recent[0]) / len(recent)

    @staticmethod
    def _detect_trend_direction(data_points: list[float], threshold: float = 0.05) -> str:
        """Detect the direction of a trend: rising, falling, or stable."""
        if len(data_points) < 2:
            return "stable"
        velocity = (data_points[-1] - data_points[0]) / max(abs(data_points[0]), 1e-9)
        if velocity > threshold:
            return "rising"
        elif velocity < -threshold:
            return "falling"
        return "stable"
