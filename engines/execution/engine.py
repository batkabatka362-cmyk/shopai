"""
Execution Engine — Execute planned actions reliably — task dispatch, monitoring, retry, rollback
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ExecutionEngine(BaseEngine):
    engine_name = "execution"
    required_input_fields = ['action_plan', 'execution_params']
    required_output_fields = ['execution_results', 'status_report']

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
        templates = {"analyze": """Analyze execution readiness: prerequisites met, resources available, risk assessment, rollback plan, monitoring setup.\nPlan: {action_plan}\nParams: {execution_params}""", "execute": """Execute actions: dispatch tasks, monitor progress, handle failures (retry/skip/abort), collect results, generate status report.\nAnalysis: {analysis}""", "enhance": """Enhance: predictive failure avoidance, performance optimization mid-execution.\nResults: {execution}""", "validate": """Validate: all tasks accounted for, no orphaned state, results consistent.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _success_rate(completed: int, total: int) -> float:
        if total == 0: return 0.0
        return round(completed / total * 100, 2)

    @staticmethod
    def _should_retry(attempt: int, max_retries: int, error_type: str) -> bool:
        transient = {"timeout", "rate_limit", "network_error", "503"}
        return attempt < max_retries and error_type in transient
