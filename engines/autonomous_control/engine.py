"""
AutonomousControl Engine — Self-governing control system — manages autonomous operations with safety boundaries and human override
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AutonomousControlEngine(BaseEngine):
    engine_name = "autonomous_control"
    required_input_fields = ['system_state', 'control_params']
    required_output_fields = ['control_actions', 'safety_status']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Assess system state and safety boundaries", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate control actions within boundaries", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with adaptive control strategies", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate safety compliance", required=True))
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
        templates = {"analyze": """Assess autonomous control readiness:\n- System health (all engines operational?)\n- Safety boundaries defined and enforced\n- Human override availability\n- Current autonomy level (1-5)\n- Active constraints and guardrails\n- Risk exposure within tolerance?\n\nState: {system_state}\nParams: {control_params}""", "execute": """Generate control actions:\n- Engine activation/deactivation decisions\n- Resource reallocation\n- Priority adjustments\n- Escalation triggers (when to alert human)\n- Autonomy level recommendation (increase/maintain/decrease)\n- Dead-man switch status\n\nAnalysis: {analysis}""", "enhance": """Enhance: predictive control (anticipate issues before they occur), graceful degradation paths, self-healing triggers.\n\nActions: {execution}""", "validate": """Validate: no actions exceed safety boundaries, human override preserved, rollback possible for every action, audit trail complete.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    AUTONOMY_LEVELS = {
        1: "human_controlled",     # Human makes all decisions
        2: "human_assisted",       # System suggests, human approves
        3: "semi_autonomous",      # System acts, human monitors
        4: "supervised_autonomous", # System acts, human can override
        5: "fully_autonomous",     # System self-governs within boundaries
    }

    SAFETY_BOUNDARIES = ["max_spend_per_hour", "max_price_change_pct", "max_concurrent_campaigns", "min_margin_threshold"]

    @classmethod
    def _check_boundaries(cls, action: dict, boundaries: dict) -> list[str]:
        violations = []
        for boundary in cls.SAFETY_BOUNDARIES:
            limit = boundaries.get(boundary)
            value = action.get(boundary)
            if limit is not None and value is not None and value > limit:
                violations.append(f"{boundary}: {value} exceeds {limit}")
        return violations

    @staticmethod
    def _should_escalate(risk_score: float, autonomy_level: int) -> bool:
        thresholds = {1: 0.1, 2: 0.3, 3: 0.5, 4: 0.7, 5: 0.9}
        return risk_score > thresholds.get(autonomy_level, 0.5)
