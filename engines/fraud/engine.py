"""
Fraud Engine — Detect and prevent fraud — transaction scoring, pattern detection, rule-based blocking
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class FraudEngine(BaseEngine):
    engine_name = "fraud"
    required_input_fields = ['transaction_data', 'risk_signals']
    required_output_fields = ['fraud_assessment', 'blocked_actions']

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
        templates = {"analyze": """Analyze fraud indicators: transaction velocity, amount anomalies, geographic mismatches, device fingerprinting, behavioral patterns, chargeback history.\nTransactions: {transaction_data}\nSignals: {risk_signals}""", "execute": """Generate fraud assessment: risk score per transaction, flagged transactions, blocking recommendations, false positive estimation.\nAnalysis: {analysis}""", "enhance": """Enhance: adaptive fraud rules, emerging fraud pattern detection.\nAssessment: {execution}""", "validate": """Validate: false positive rate acceptable, legitimate transactions not blocked, coverage complete.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _fraud_score(velocity: float, amount_deviation: float, geo_mismatch: bool) -> float:
        score = velocity * 3 + amount_deviation * 4 + (3 if geo_mismatch else 0)
        return round(min(10, score), 2)

    @staticmethod
    def _should_block(fraud_score: float, threshold: float = 7.0) -> bool:
        return fraud_score >= threshold

    @staticmethod
    def _false_positive_rate(blocked_legit: int, total_blocked: int) -> float:
        if total_blocked == 0: return 0.0
        return round(blocked_legit / total_blocked * 100, 2)
