"""
Retention Engine — Retain customers and reduce churn — cohort analysis, win-back, lifecycle management
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class RetentionEngine(BaseEngine):
    engine_name = "retention"
    required_input_fields = ['customer_data', 'churn_signals']
    required_output_fields = ['retention_plan', 'risk_segments']

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
        templates = {"analyze": """Analyze retention: cohort retention curves, churn rate by segment, early warning signals, NPS/CSAT trends, churn reasons.\n\nCustomers: {customer_data}\nSignals: {churn_signals}""", "execute": """Generate retention plan: at-risk segment interventions, loyalty triggers, reactivation sequences, win-back offers, lifecycle emails.\nAnalysis: {analysis}""", "enhance": """Enhance: emotional connection strategies, surprise and delight moments, community belonging.\nPlan: {execution}""", "validate": """Validate: churn prediction model accuracy, intervention costs vs customer value.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _churn_rate(lost: int, total: int) -> float:
        if total == 0: return 0.0
        return round(lost / total * 100, 2)

    @staticmethod
    def _retention_rate(retained: int, initial: int) -> float:
        if initial == 0: return 0.0
        return round(retained / initial * 100, 2)

    @staticmethod
    def _cohort_retention(cohort_start: int, cohort_active: int) -> float:
        if cohort_start == 0: return 0.0
        return round(cohort_active / cohort_start * 100, 2)
