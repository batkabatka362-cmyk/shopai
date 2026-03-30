"""
Virality Engine — Engineer viral growth mechanics — sharing loops, network effects, referral coefficients
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ViralityEngine(BaseEngine):
    engine_name = "virality"
    required_input_fields = ['content_data', 'network_data']
    required_output_fields = ['viral_strategy', 'growth_projections']

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
        templates = {"analyze": """Analyze viral potential: shareability, emotional triggers, network density, platform mechanics, K-factor estimation.\n\nContent: {content_data}\nNetwork: {network_data}""", "execute": """Generate viral strategy: sharing mechanics, incentive design, content format, seeding strategy, K-factor targets.\nAnalysis: {analysis}""", "enhance": """Enhance: emotional triggers (awe, humor, outrage), identity signaling, FOMO loops.\nStrategy: {execution}""", "validate": """Validate: K-factor assumptions realistic, no spammy tactics, sustainable growth.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _k_factor(invites_per_user: float, conversion_rate: float) -> float:
        return round(invites_per_user * conversion_rate, 3)

    @staticmethod
    def _is_viral(k_factor: float) -> bool:
        return k_factor > 1.0

    @staticmethod
    def _viral_cycle_time(days_to_invite: float, days_to_convert: float) -> float:
        return round(days_to_invite + days_to_convert, 1)
