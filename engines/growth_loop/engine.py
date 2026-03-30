"""
GrowthLoop Engine — Implement growth feedback loops — acquisition, activation, retention, referral, revenue
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class GrowthLoopEngine(BaseEngine):
    engine_name = "growth_loop"
    required_input_fields = ['loop_data', 'metrics']
    required_output_fields = ['loop_analysis', 'optimization_actions']

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
        r = self._model_router.execute("analyzer", self._build_prompt("analyze", data), context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"analysis": r})

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        r = self._model_router.execute("worker", self._build_prompt("execute", data), context=data)
        return StepResult(step_name=step_name, model_used="qwen", status=EngineStatus.COMPLETED, output={"execution": r})

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        r = self._model_router.execute("creative", self._build_prompt("enhance", data), context=data)
        return StepResult(step_name=step_name, model_used="llama", status=EngineStatus.COMPLETED, output={"enhanced": r})

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        r = self._model_router.execute("validator", self._build_prompt("validate", data), context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"validation": r})

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        templates = {"analyze": """Analyze growth loops: AARRR funnel (acquisition, activation, retention, referral, revenue), loop velocity, leak points, amplification opportunities.\nLoop: {loop_data}\nMetrics: {metrics}""", "execute": """Generate loop optimization: per-stage improvements, loop acceleration tactics, leak plugging priorities, new loop identification.\nAnalysis: {analysis}""", "enhance": """Enhance: flywheel effects, cross-loop synergies, user-driven growth mechanics.\nOptimization: {execution}""", "validate": """Validate: loop mechanics are real (not theoretical), metrics are measurable.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    AARRR = ["acquisition", "activation", "retention", "referral", "revenue"]

    @staticmethod
    def _loop_velocity(cycle_time_days: float, k_factor: float) -> float:
        if cycle_time_days == 0: return 0.0
        return round(k_factor / cycle_time_days, 4)

    @staticmethod
    def _biggest_leak(stages: dict[str, float]) -> str:
        if not stages: return "unknown"
        return min(stages, key=stages.get)
