"""
AutonomousDecision Engine — Self-directed decision making — evaluates options and decides without human input within authorized scope
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AutonomousDecisionEngine(BaseEngine):
    engine_name = "autonomous_decision"
    required_input_fields = ['decision_context', 'authority_scope']
    required_output_fields = ['decision', 'confidence_level']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Evaluate decision context and authority", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Make autonomous decision", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with strategic foresight", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate decision within authority", required=True))
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
        templates = {"analyze": """Evaluate autonomous decision opportunity:\n- Decision type and complexity\n- Available data quality and completeness\n- Historical accuracy for similar decisions\n- Authority scope (what am I allowed to decide?)\n- Reversibility of decision\n- Time pressure\n- Confidence threshold met?\n\nContext: {decision_context}\nScope: {authority_scope}""", "execute": """Make decision:\n- Selected option with rationale\n- Confidence level (0-1)\n- Expected outcome with probability\n- Fallback if outcome doesn't materialize\n- Monitoring triggers (when to re-evaluate)\n- If confidence < threshold: escalate to human\n\nAnalysis: {analysis}""", "enhance": """Enhance: second-order effects analysis, what competitors would decide, contrarian check (why might this be wrong?).\n\nDecision: {execution}""", "validate": """Validate: decision within authority scope, confidence honestly assessed, reversibility plan exists, monitoring in place.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    DECISION_TYPES = {
        "pricing": {"authority_min": 2, "max_impact_usd": 1000},
        "inventory": {"authority_min": 2, "max_impact_usd": 5000},
        "campaign": {"authority_min": 3, "max_impact_usd": 500},
        "content": {"authority_min": 1, "max_impact_usd": 100},
        "strategy": {"authority_min": 4, "max_impact_usd": 10000},
    }

    @classmethod
    def _can_decide(cls, decision_type: str, authority_level: int) -> bool:
        spec = cls.DECISION_TYPES.get(decision_type, {})
        return authority_level >= spec.get("authority_min", 5)

    @staticmethod
    def _confidence_gate(confidence: float, threshold: float = 0.7) -> str:
        if confidence >= threshold:
            return "decide"
        elif confidence >= threshold * 0.7:
            return "decide_with_monitoring"
        return "escalate_to_human"
