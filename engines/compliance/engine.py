"""
Compliance Engine — Ensure regulatory and policy compliance — GDPR, tax, advertising standards, platform rules
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ComplianceEngine(BaseEngine):
    engine_name = "compliance"
    required_input_fields = ['compliance_data', 'regulations']
    required_output_fields = ['compliance_report', 'violations']

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
        templates = {"analyze": """Audit compliance: GDPR/privacy, advertising standards, platform policies (Shopify TOS), tax obligations, product regulations, accessibility.\nData: {compliance_data}\nRegs: {regulations}""", "execute": """Generate compliance report: status per regulation, violations found, remediation steps, priority timeline, risk of non-compliance.\nAnalysis: {analysis}""", "enhance": """Enhance: proactive compliance (ahead of upcoming regulations), competitive advantage through trust.\nReport: {execution}""", "validate": """Validate: all regulations checked, violations have remediation, no false compliance claims.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    REGULATION_TYPES = ["gdpr", "ccpa", "tax", "advertising_standards", "platform_tos", "product_safety", "accessibility"]

    @staticmethod
    def _compliance_score(passed: int, total: int) -> float:
        if total == 0: return 100.0
        return round(passed / total * 100, 2)

    @staticmethod
    def _violation_severity(violations: list[dict]) -> dict[str, int]:
        sev = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for v in violations:
            s = v.get("severity", "low")
            sev[s] = sev.get(s, 0) + 1
        return sev
