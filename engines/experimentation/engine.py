"""
Experimentation Engine — Run experiments — A/B tests, multivariate tests, hypothesis validation
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ExperimentationEngine(BaseEngine):
    engine_name = "experimentation"
    required_input_fields = ['experiment_config', 'hypothesis']
    required_output_fields = ['experiment_results', 'statistical_analysis']

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
        templates = {"analyze": """Design experiment: hypothesis, variables, sample size, duration, success metrics, statistical significance requirements.\nConfig: {experiment_config}\nHypothesis: {hypothesis}""", "execute": """Generate experiment plan: control/variant design, traffic split, minimum detectable effect, run duration, stopping rules.\nAnalysis: {analysis}""", "enhance": """Enhance: multi-armed bandit optimization, sequential testing, experiment velocity.\nPlan: {execution}""", "validate": """Validate: sample size sufficient, no selection bias, p-value threshold defined.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _sample_size(baseline_rate: float, mde: float, power: float = 0.8, alpha: float = 0.05) -> int:
        import math
        z_alpha = 1.96
        z_beta = 0.84
        p = baseline_rate
        delta = mde
        n = ((z_alpha + z_beta) ** 2 * 2 * p * (1 - p)) / (delta ** 2)
        return int(math.ceil(n))

    @staticmethod
    def _is_significant(p_value: float, alpha: float = 0.05) -> bool:
        return p_value < alpha

    @staticmethod
    def _uplift(control: float, variant: float) -> float:
        if control == 0: return 0.0
        return round((variant - control) / control * 100, 2)
