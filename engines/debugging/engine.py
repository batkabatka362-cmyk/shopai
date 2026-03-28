"""
Debugging Engine — Debug and diagnose system issues — root cause analysis, error tracing, fix recommendations
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class DebuggingEngine(BaseEngine):
    engine_name = "debugging"
    required_input_fields = ['error_data', 'system_logs']
    required_output_fields = ['diagnosis', 'fix_recommendations']

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
        templates = {"analyze": """Analyze errors: error patterns, frequency, affected components, stack traces, correlated events, timeline reconstruction.\nErrors: {error_data}\nLogs: {system_logs}""", "execute": """Generate diagnosis: root cause (proven or hypothesized), impact assessment, fix recommendations ranked by effort/impact, prevention measures.\nAnalysis: {analysis}""", "enhance": """Enhance: similar past incidents and resolutions, systemic pattern detection.\nDiagnosis: {execution}""", "validate": """Validate: root cause is evidence-based, fixes address cause not symptoms, prevention is actionable.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _error_frequency(errors: list[dict], window_hours: int = 24) -> dict[str, int]:
        freq: dict[str, int] = {}
        for e in errors:
            key = e.get("type", "unknown")
            freq[key] = freq.get(key, 0) + 1
        return freq

    @staticmethod
    def _impact_score(affected_users: int, total_users: int, severity: str) -> float:
        sev_mult = {"critical": 3, "high": 2, "medium": 1, "low": 0.5}
        pct = affected_users / max(total_users, 1)
        return round(pct * sev_mult.get(severity, 1) * 10, 2)
