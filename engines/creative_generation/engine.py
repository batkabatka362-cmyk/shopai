"""
CreativeGeneration Engine — Generate creative assets — ad creatives, banner designs, video scripts, visual concepts
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class CreativeGenerationEngine(BaseEngine):
    engine_name = "creative_generation"
    required_input_fields = ['brief', 'brand_guidelines']
    required_output_fields = ['creative_assets', 'variations']

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
        templates = {"analyze": """Analyze creative brief:\n- Campaign objective\n- Target audience demographics and psychographics\n- Brand identity (colors, fonts, tone)\n- Platform requirements (sizes, formats)\n- Competitor creative benchmarks\n- Previous top-performing creatives\n- Message hierarchy (primary, secondary, CTA)\n\nBrief: {brief}\nGuidelines: {brand_guidelines}""", "execute": """Generate creative concepts:\n- 3 distinct creative directions\n- Per direction: headline, body, CTA, visual description\n- Ad copy variations (3-5 per direction)\n- Platform-specific adaptations\n- A/B test recommendations\n- Color palette and mood\n\nAnalysis: {analysis}""", "enhance": """Enhance creatives with:\n- Emotional resonance\n- Pattern interrupts (stop the scroll)\n- Cultural relevance\n- Humor where appropriate\n\nCreatives: {execution}""", "validate": """Validate: brand guidelines followed, all platforms covered, no trademark/copyright issues, CTAs clear.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    PLATFORMS = ["facebook", "instagram", "tiktok", "google", "youtube", "pinterest", "email"]
    AD_SIZES = {"facebook": "1200x628", "instagram": "1080x1080", "story": "1080x1920", "banner": "728x90"}

    @staticmethod
    def _creative_score(clarity: float, emotion: float, relevance: float) -> float:
        return round(clarity * 0.3 + emotion * 0.4 + relevance * 0.3, 2)
