"""
Risk Engine — Assess and mitigate business risks — financial, operational, market, compliance
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class RiskEngine(BaseEngine):
    engine_name = "risk"
    required_input_fields = ['risk_data', 'risk_factors']
    required_output_fields = ['risk_assessment', 'mitigation_plan']

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
        templates = {"analyze": """Analyze risks: probability and impact per risk, risk categories (financial, operational, market, legal), interdependencies, historical incidents.\nData: {risk_data}\nFactors: {risk_factors}""", "execute": """Generate risk assessment: risk matrix (probability x impact), top 10 risks ranked, mitigation strategies, contingency plans, monitoring KPIs.\nAnalysis: {analysis}""", "enhance": """Enhance: black swan scenarios, cascading failure analysis, anti-fragility opportunities.\nAssessment: {execution}""", "validate": """Validate: risks are specific and actionable, mitigations have owners.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _risk_score(probability: float, impact: float) -> float:
        return round(probability * impact, 2)

    @staticmethod
    def _risk_level(score: float) -> str:
        if score > 7: return "critical"
        if score > 4: return "high"
        if score > 2: return "medium"
        return "low"

    @staticmethod
    def _expected_loss(probability: float, loss_amount: float) -> float:
        return round(probability * loss_amount, 2)
