"""
Ux Engine — Optimize user experience — usability, accessibility, performance, user satisfaction
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class UxEngine(BaseEngine):
    engine_name = "ux"
    required_input_fields = ['ux_data', 'user_feedback']
    required_output_fields = ['ux_recommendations', 'design_changes']

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
        templates = {"analyze": """Analyze UX: page load times, mobile responsiveness, navigation clarity, accessibility compliance, user feedback themes, heatmap insights, error rates.\nUX data: {ux_data}\nFeedback: {user_feedback}""", "execute": """Generate UX improvements: prioritized fixes, A/B test designs, accessibility upgrades, performance targets, information architecture changes.\nAnalysis: {analysis}""", "enhance": """Enhance: delight moments, micro-interactions, emotional design, brand personality in UI.\nImprovements: {execution}""", "validate": """Validate: improvements are measurable, accessibility standards met, no regression.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _page_speed_score(load_time_ms: float) -> float:
        if load_time_ms <= 1000: return 10.0
        if load_time_ms >= 5000: return 0.0
        return round(10 - (load_time_ms - 1000) / 400, 2)

    @staticmethod
    def _ux_score(usability: float, accessibility: float, performance: float, satisfaction: float) -> float:
        return round(usability * 0.3 + accessibility * 0.2 + performance * 0.2 + satisfaction * 0.3, 2)
