"""
Innovation Engine — Drive innovation — idea generation, feasibility assessment, MVP design
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class InnovationEngine(BaseEngine):
    engine_name = "innovation"
    required_input_fields = ['innovation_data', 'market_gaps']
    required_output_fields = ['innovation_proposals', 'feasibility_scores']

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
        templates = {"analyze": """Analyze innovation landscape: unmet needs, technology trends, market gaps, customer pain points, competitive white spaces.\nData: {innovation_data}\nGaps: {market_gaps}""", "execute": """Generate innovation proposals: ideas ranked by potential, feasibility assessment, MVP requirements, resource estimates, go-to-market strategy.\nAnalysis: {analysis}""", "enhance": """Enhance: 10x thinking, cross-industry inspiration, moonshot potential.\nProposals: {execution}""", "validate": """Validate: ideas are novel and feasible, market need is validated, resources are realistic.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _innovation_score(novelty: float, feasibility: float, market_size: float) -> float:
        return round(novelty * 0.3 + feasibility * 0.4 + market_size * 0.3, 2)

    @staticmethod
    def _mvp_scope(features: list[dict]) -> list[dict]:
        return sorted(features, key=lambda f: f.get("impact", 0) / max(f.get("effort", 1), 1), reverse=True)[:5]
