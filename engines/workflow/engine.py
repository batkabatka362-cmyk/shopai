"""
Workflow Engine — Manage business workflows — process design, bottleneck detection, optimization
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class WorkflowEngine(BaseEngine):
    engine_name = "workflow"
    required_input_fields = ['workflow_data', 'optimization_goals']
    required_output_fields = ['optimized_workflow', 'efficiency_metrics']

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
        templates = {"analyze": """Analyze workflow: step sequence, time per step, bottlenecks, handoff points, error/rework rates, parallel opportunities.\nWorkflow: {workflow_data}\nGoals: {optimization_goals}""", "execute": """Generate optimized workflow: reordered steps, eliminated redundancies, parallelized where possible, SLAs per step, escalation rules.\nAnalysis: {analysis}""", "enhance": """Enhance: zero-friction workflow design, proactive alerts, self-routing.\nWorkflow: {execution}""", "validate": """Validate: all steps accounted for, no orphaned branches, SLAs achievable.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _throughput(completed: int, time_hours: float) -> float:
        if time_hours == 0: return 0.0
        return round(completed / time_hours, 2)

    @staticmethod
    def _cycle_time(steps: list[dict]) -> float:
        return round(sum(s.get("duration_min", 0) for s in steps), 2)

    @staticmethod
    def _bottleneck(steps: list[dict]) -> str:
        if not steps: return "none"
        slowest = max(steps, key=lambda s: s.get("duration_min", 0))
        return slowest.get("name", "unknown")
