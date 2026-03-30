"""
SelfImprovement Engine — System self-improvement — detect weaknesses, generate improvements, validate upgrades
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class SelfImprovementEngine(BaseEngine):
    engine_name = "self_improvement"
    required_input_fields = ['system_metrics', 'performance_gaps']
    required_output_fields = ['improvement_actions', 'expected_gains']

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
        templates = {"analyze": """Analyze system performance: per-engine accuracy, latency, user satisfaction, error rates, performance gaps vs targets.\nMetrics: {system_metrics}\nGaps: {performance_gaps}""", "execute": """Generate improvement plan: weakest components, root causes, improvement actions, expected gains, implementation priority, A/B test design.\nAnalysis: {analysis}""", "enhance": """Enhance: compound improvement strategies, one improvement that cascades across engines.\nPlan: {execution}""", "validate": """Validate: improvements don't break existing functionality, gains are measurable, rollback plan exists.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _improvement_priority(gap: float, impact: float, effort: float) -> float:
        if effort == 0: return 0.0
        return round(gap * impact / effort, 3)

    @staticmethod
    def _regression_check(before: dict[str, float], after: dict[str, float]) -> list[str]:
        regressions = []
        for key in before:
            if key in after and after[key] < before[key] * 0.95:
                regressions.append(key)
        return regressions
