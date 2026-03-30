"""
Governance Engine — Manage system governance — policies, decision authority, audit trails, human oversight
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class GovernanceEngine(BaseEngine):
    engine_name = "governance"
    required_input_fields = ['policy_data', 'governance_rules']
    required_output_fields = ['governance_report', 'policy_updates']

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
        templates = {"analyze": """Analyze governance: policy coverage, decision authority matrix, audit trail completeness, human oversight gaps, escalation paths.\nPolicies: {policy_data}\nRules: {governance_rules}""", "execute": """Generate governance report: policy compliance status, authority gap analysis, recommended policy updates, audit findings, oversight improvements.\nAnalysis: {analysis}""", "enhance": """Enhance: adaptive governance (rules that evolve with system capability), trust-building through transparency.\nReport: {execution}""", "validate": """Validate: all critical decisions have oversight, audit trail complete, escalation paths tested.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _policy_coverage(areas_covered: int, total_areas: int) -> float:
        if total_areas == 0: return 100.0
        return round(areas_covered / total_areas * 100, 2)

    @staticmethod
    def _authority_level(decision_type: str) -> int:
        levels = {"operational": 1, "tactical": 2, "strategic": 3, "existential": 4}
        return levels.get(decision_type, 2)
