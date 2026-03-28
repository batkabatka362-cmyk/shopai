"""
Seo Engine — Optimize search engine visibility — keywords, on-page, technical SEO, content strategy
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class SeoEngine(BaseEngine):
    engine_name = "seo"
    required_input_fields = ['site_data', 'keywords']
    required_output_fields = ['seo_recommendations', 'keyword_strategy']

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
        templates = {"analyze": """SEO audit: technical (speed, mobile, crawlability), on-page (titles, meta, headers, content), off-page (backlinks, authority), keyword gaps.\n\nSite: {site_data}\nKeywords: {keywords}""", "execute": """Generate SEO plan: priority fixes, keyword targeting, content calendar, link building strategy, technical improvements.\nAnalysis: {analysis}""", "enhance": """Enhance: content angles that attract natural backlinks, featured snippet opportunities, semantic SEO.\nPlan: {execution}""", "validate": """Validate: keywords have volume, technical fixes are actionable, timeline realistic.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _keyword_difficulty(competition: float, domain_authority: float) -> str:
        diff = competition - domain_authority / 100
        if diff > 0.5: return "very_hard"
        if diff > 0.2: return "hard"
        if diff > -0.1: return "medium"
        return "easy"

    @staticmethod
    def _search_opportunity(volume: int, difficulty: float, ctr_estimate: float) -> float:
        return round(volume * (1 - difficulty) * ctr_estimate, 2)
