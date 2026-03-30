"""
Growth Engine — Drive business growth — identify levers, design experiments, compound advantages
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class GrowthEngine(BaseEngine):
    engine_name = "growth"
    required_input_fields = ['growth_data', 'growth_targets']
    required_output_fields = ['growth_plan', 'projected_growth']

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
        templates = {"analyze": """Analyze growth: current trajectory, growth rate, acquisition channels, activation rate, retention, referral, revenue per user.\nData: {growth_data}\nTargets: {growth_targets}""", "execute": """Generate growth plan: top 3 growth levers, experiment designs, resource requirements, 30/60/90 day milestones, projected impact.\nAnalysis: {analysis}""", "enhance": """Enhance: non-linear growth opportunities, compounding loops, viral mechanics.\nPlan: {execution}""", "validate": """Validate: projections are grounded, experiments are measurable, resources allocated.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _growth_rate(current: float, previous: float) -> float:
        if previous == 0: return 0.0
        return round((current - previous) / previous * 100, 2)

    @staticmethod
    def _compound_growth(base: float, rate: float, periods: int) -> float:
        return round(base * (1 + rate / 100) ** periods, 2)

    @staticmethod
    def _north_star_metric(users: int, activation_rate: float, frequency: float) -> float:
        return round(users * activation_rate * frequency, 2)
