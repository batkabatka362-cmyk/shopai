"""
Scheduling Engine — Schedule tasks optimally — resource allocation, conflict resolution, priority queuing
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class SchedulingEngine(BaseEngine):
    engine_name = "scheduling"
    required_input_fields = ['tasks', 'constraints']
    required_output_fields = ['schedule', 'resource_allocation']

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
        templates = {"analyze": """Analyze scheduling: task priorities, durations, dependencies, resource availability, deadlines, conflicts.\nTasks: {tasks}\nConstraints: {constraints}""", "execute": """Generate schedule: task ordering, resource assignment, conflict resolutions, buffer time, critical path identification.\nAnalysis: {analysis}""", "enhance": """Enhance: adaptive scheduling, just-in-time task release.\nSchedule: {execution}""", "validate": """Validate: no resource conflicts, deadlines met, dependencies respected.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _critical_path(tasks: list[dict]) -> list[str]:
        return [t.get("name", "") for t in sorted(tasks, key=lambda t: t.get("slack", 0))]

    @staticmethod
    def _utilization(busy_hours: float, available_hours: float) -> float:
        if available_hours == 0: return 0.0
        return round(busy_hours / available_hours * 100, 2)
