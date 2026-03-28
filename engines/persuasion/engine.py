"""
Persuasion Engine — Optimize persuasion techniques — Cialdini principles, copy frameworks, influence architecture
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class PersuasionEngine(BaseEngine):
    engine_name = "persuasion"
    required_input_fields = ['content_data', 'audience_profile']
    required_output_fields = ['persuasion_elements', 'optimized_content']

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
        templates = {"analyze": """Analyze persuasion opportunity: audience resistance level, trust baseline, message receptivity, channel context, previous exposure.\nContent: {content_data}\nAudience: {audience_profile}""", "execute": """Generate persuasion framework: AIDA structure, Cialdini principle application (reciprocity, commitment, social proof, authority, liking, scarcity), objection handling, trust signals.\nAnalysis: {analysis}""", "enhance": """Enhance: power words, emotional escalation, curiosity gaps, open loops.\nFramework: {execution}""", "validate": """Validate: claims truthful, not manipulative, builds genuine trust.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    CIALDINI = ["reciprocity", "commitment", "social_proof", "authority", "liking", "scarcity"]
    COPY_FRAMEWORKS = ["AIDA", "PAS", "BAB", "FAB", "4Ps"]

    @staticmethod
    def _persuasion_score(trust: float, relevance: float, urgency: float) -> float:
        return round(trust * 0.4 + relevance * 0.35 + urgency * 0.25, 2)
