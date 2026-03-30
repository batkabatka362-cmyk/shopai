"""
Strategy Engine — Develop business strategies — competitive positioning, growth vectors, resource allocation
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class StrategyEngine(BaseEngine):
    engine_name = "strategy"
    required_input_fields = ['market_data', 'business_goals']
    required_output_fields = ['strategy', 'action_items']

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
        templates = {"analyze": """Analyze strategic landscape: SWOT, Porter's Five Forces, competitive position, core competencies, market trends, resource constraints.\nMarket: {market_data}\nGoals: {business_goals}""", "execute": """Generate strategy: strategic options (3), evaluation per option, recommended strategy, action plan, resource requirements, KPIs.\nAnalysis: {analysis}""", "enhance": """Enhance: non-obvious strategic moves, first-mover opportunities, defensive moats.\nStrategy: {execution}""", "validate": """Validate: strategy is differentiated, executable with current resources, metrics defined.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _swot(strengths: list, weaknesses: list, opportunities: list, threats: list) -> dict:
        return {"strengths": len(strengths), "weaknesses": len(weaknesses), "opportunities": len(opportunities), "threats": len(threats), "balance": round((len(strengths) + len(opportunities)) / max(len(weaknesses) + len(threats), 1), 2)}

    @staticmethod
    def _strategic_fit(option: dict, goals: dict) -> float:
        matches = sum(1 for k in goals if k in option)
        return round(matches / max(len(goals), 1), 2)
