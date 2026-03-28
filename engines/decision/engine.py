"""
Decision Engine — Make data-driven decisions — multi-criteria evaluation, confidence scoring, option ranking
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class DecisionEngine(BaseEngine):
    engine_name = "decision"
    required_input_fields = ['options', 'evaluation_criteria']
    required_output_fields = ['decision', 'rationale']

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
        templates = {"analyze": """Evaluate decision: options available, criteria weights, data quality, risk per option, reversibility, time pressure.\nOptions: {options}\nCriteria: {evaluation_criteria}""", "execute": """Make decision: weighted scoring per option, sensitivity analysis, recommended choice with confidence level, contingency if wrong.\nAnalysis: {analysis}""", "enhance": """Enhance: second-order thinking, pre-mortem analysis, devil's advocate check.\nDecision: {execution}""", "validate": """Validate: all options considered, no bias detected, confidence calibrated.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _weighted_decision(options: list[dict], weights: dict[str, float]) -> list[dict]:
        for opt in options:
            score = sum(opt.get(k, 0) * w for k, w in weights.items())
            opt["weighted_score"] = round(score, 3)
        return sorted(options, key=lambda o: o.get("weighted_score", 0), reverse=True)

    @staticmethod
    def _decision_confidence(data_quality: float, option_gap: float) -> float:
        return round(min(1.0, data_quality * 0.6 + option_gap * 0.4), 3)
