"""
Funnel Engine — Design and optimize conversion funnels — awareness to purchase stages
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class FunnelEngine(BaseEngine):
    engine_name = "funnel"
    required_input_fields = ['funnel_data', 'conversion_goals']
    required_output_fields = ['funnel_design', 'optimization_plan']

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
        templates = {"analyze": """Analyze funnel: stage-by-stage drop-off rates, bottleneck identification, comparison to benchmarks.\n\nFunnel: {funnel_data}\nGoals: {conversion_goals}""", "execute": """Generate funnel optimization: per-stage improvements, A/B test priorities, messaging per stage, retargeting strategy.\nAnalysis: {analysis}""", "enhance": """Enhance: micro-commitments, value ladder, trust building sequence.\nPlan: {execution}""", "validate": """Validate: improvement projections are realistic, stages properly sequenced.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _drop_off_rate(stage_in: int, stage_out: int) -> float:
        if stage_in == 0: return 0.0
        return round((1 - stage_out / stage_in) * 100, 2)

    @staticmethod
    def _funnel_efficiency(top: int, bottom: int) -> float:
        if top == 0: return 0.0
        return round(bottom / top * 100, 2)

    @staticmethod
    def _bottleneck_stage(stages: list[dict]) -> str:
        worst = max(stages, key=lambda s: s.get("drop_off", 0), default={})
        return worst.get("name", "unknown")
