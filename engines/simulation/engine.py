"""
Simulation Engine — Simulate business scenarios — what-if analysis, Monte Carlo, sensitivity testing
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class SimulationEngine(BaseEngine):
    engine_name = "simulation"
    required_input_fields = ['scenario_params', 'variables']
    required_output_fields = ['simulation_results', 'projections']

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
        templates = {"analyze": """Define simulation: variables, ranges, distributions, correlations, scenarios to test, iterations needed.\nParams: {scenario_params}\nVariables: {variables}""", "execute": """Run simulation: base/best/worst cases, sensitivity analysis (which variables matter most), probability distribution of outcomes.\nAnalysis: {analysis}""", "enhance": """Enhance: black swan scenarios, tail risk analysis, opportunity under uncertainty.\nResults: {execution}""", "validate": """Validate: assumptions documented, results statistically meaningful, edge cases covered.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _scenario_outcome(base: float, multipliers: dict[str, float]) -> float:
        result = base
        for m in multipliers.values():
            result *= m
        return round(result, 2)

    @staticmethod
    def _sensitivity(base_result: float, varied_result: float, pct_change: float) -> float:
        if pct_change == 0: return 0.0
        result_change = (varied_result - base_result) / base_result * 100
        return round(result_change / pct_change, 3)

    @staticmethod
    def _expected_value(outcomes: list[dict]) -> float:
        return round(sum(o.get("value", 0) * o.get("probability", 0) for o in outcomes), 2)
