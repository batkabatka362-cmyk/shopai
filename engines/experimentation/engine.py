"""
Experimentation Engine — Run structured experiments and A/B tests with statistical rigor
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
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze experiment design", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Execute experiment analysis", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with learning narratives", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate statistical significance", required=True))
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
        templates = {"analyze": """Analyze: hypothesis clarity, sample size requirements, test duration, confounding variables, success metrics.\nConfig: {experiment_config}\nHypothesis: {hypothesis}""", "execute": """Run analysis: control vs variant, statistical significance (p-value), effect size, confidence interval, sample size adequacy.\nAnalysis: {analysis}""", "enhance": """Enhance: what we learned narrative, follow-up experiment ideas, broader implications.\nResults: {execution}""", "validate": """Validate: p-value threshold met, no peeking bias, sample size sufficient, external validity considered.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _min_sample_size(baseline_rate: float, min_effect: float, power: float = 0.8) -> int:
        import math
        z_alpha = 1.96
        z_beta = 0.84
        p1 = baseline_rate
        p2 = baseline_rate * (1 + min_effect)
        n = ((z_alpha + z_beta) ** 2 * (p1 * (1-p1) + p2 * (1-p2))) / max((p2 - p1) ** 2, 0.0001)
        return int(math.ceil(n))
