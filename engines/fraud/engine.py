"""
Fraud Engine — Detect and prevent fraudulent orders, chargebacks, and abuse
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
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze transaction risk patterns", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate fraud detection rules", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with adaptive detection", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate false positive rate", required=True))
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
        templates = {"analyze": """Analyze: order velocity, payment patterns, shipping/billing mismatch, device fingerprints, behavioral signals.\nTransactions: {transaction_data}\nSignals: {risk_signals}""", "execute": """Generate: risk score per transaction, block/review/approve decision, rule recommendations, chargeback prediction.\nAnalysis: {analysis}""", "enhance": """Enhance: adaptive rules that learn from confirmed fraud, reduce false positives over time.\nAssessment: {execution}""", "validate": """Validate: false positive rate <5%, critical fraud caught, legitimate customers not blocked.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _fraud_score(signals: dict) -> float:
        score = 0.0
        if signals.get("billing_shipping_mismatch"): score += 3
        if signals.get("high_velocity"): score += 2
        if signals.get("new_account"): score += 1
        if signals.get("vpn_detected"): score += 1
        if signals.get("multiple_failed_payments"): score += 2
        return min(10.0, score)

    @staticmethod
    def _risk_decision(score: float) -> str:
        if score >= 7: return "block"
        if score >= 4: return "review"
        return "approve"
