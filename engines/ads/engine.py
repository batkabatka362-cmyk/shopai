"""
Ads Engine — Create and optimize ad creatives, targeting, and bidding strategies
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AdsEngine(BaseEngine):
    engine_name = "ads"
    required_input_fields = ['ad_brief', 'target_audience']
    required_output_fields = ['ad_creatives', 'targeting_params']

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
        templates = {"analyze": """Analyze ad opportunity: platform, audience targeting, budget, competitor ads, best practices.\n\nBrief: {ad_brief}\nAudience: {target_audience}""", "execute": """Generate ad package: copy variants (5), headline variants (5), targeting setup, bid strategy, audience segments.\nAnalysis: {analysis}""", "enhance": """Enhance: psychological hooks, FOMO triggers, social proof elements, pattern interrupts.\nAds: {execution}""", "validate": """Validate: ad policies compliance, no misleading claims, targeting not too narrow/broad.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _cpm(cost: float, impressions: int) -> float:
        if impressions == 0: return 0.0
        return round(cost / impressions * 1000, 2)

    @staticmethod
    def _cpc(cost: float, clicks: int) -> float:
        if clicks == 0: return 0.0
        return round(cost / clicks, 2)

    @staticmethod
    def _ad_relevance_score(ctr: float, avg_ctr: float) -> float:
        if avg_ctr == 0: return 5.0
        return round(min(10, ctr / avg_ctr * 5), 2)
