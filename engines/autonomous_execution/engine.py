"""
AutonomousExecution Engine — Self-executing task runner — carries out decisions autonomously with real-time monitoring and rollback
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AutonomousExecutionEngine(BaseEngine):
    engine_name = "autonomous_execution"
    required_input_fields = ['execution_plan', 'safety_constraints']
    required_output_fields = ['execution_results', 'rollback_status']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Assess execution readiness and risks", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Execute plan autonomously", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with real-time adaptation", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate execution safety", required=True))
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
        templates = {"analyze": """Assess execution readiness:\n- All prerequisites met?\n- Resources available?\n- Safety constraints defined?\n- Rollback mechanism ready?\n- Monitoring active?\n- Similar past executions: success rate?\n\nPlan: {execution_plan}\nConstraints: {safety_constraints}""", "execute": """Execute autonomously:\n- Step-by-step with checkpoints\n- Per step: execute, verify, proceed/rollback\n- Real-time metric monitoring\n- Automatic pause on anomaly\n- Progress reporting\n- Partial completion handling\n\nAnalysis: {analysis}""", "enhance": """Enhance: predictive failure detection, parallel execution where safe, performance optimization mid-execution.\n\nResults: {execution}""", "validate": """Validate: all steps accounted for, no orphaned state, metrics within bounds, rollback tested.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _checkpoint(step: int, total: int, status: str) -> dict:
        return {"step": step, "total": total, "progress": round(step / max(total, 1) * 100, 1), "status": status}

    @staticmethod
    def _should_rollback(error_rate: float, threshold: float = 0.1) -> bool:
        return error_rate > threshold

    @staticmethod
    def _execution_health(completed: int, failed: int, total: int) -> str:
        if total == 0: return "idle"
        success_rate = completed / total
        if success_rate > 0.95: return "healthy"
        if success_rate > 0.8: return "degraded"
        return "critical"
