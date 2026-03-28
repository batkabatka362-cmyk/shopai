"""
Retention Engine — Retain customers and reduce churn through targeted interventions
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
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze churn patterns and risk segments", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate retention intervention plan", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with re-engagement messaging", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate retention impact estimates", required=True))
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
        templates = {"analyze": """Analyze: churn rate by cohort, churn predictors (recency, frequency, monetary), at-risk segments, exit survey themes.\nCustomers: {customer_data}\nSignals: {churn_signals}""", "execute": """Generate: risk scoring model, intervention triggers (email/discount/call), win-back sequences, loyalty incentives per segment.\nAnalysis: {analysis}""", "enhance": """Enhance: emotional win-back messaging, personalized offers, we-miss-you campaigns.\nPlan: {execution}""", "validate": """Validate: interventions cost less than customer LTV, no over-discounting, sequences don't conflict.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _churn_rate(lost: int, total: int) -> float:
        return round(lost / max(total, 1) * 100, 2)

    @staticmethod
    def _rfm_score(recency: int, frequency: int, monetary: float) -> dict:
        r = 5 if recency < 7 else 4 if recency < 14 else 3 if recency < 30 else 2 if recency < 60 else 1
        f = min(5, max(1, frequency))
        m = 5 if monetary > 500 else 4 if monetary > 200 else 3 if monetary > 100 else 2 if monetary > 50 else 1
        return {"R": r, "F": f, "M": m, "total": r + f + m}
