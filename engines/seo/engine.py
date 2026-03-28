"""
Seo Engine — Optimize search engine visibility through technical, content, and authority strategies
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
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze SEO landscape and technical health", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate SEO optimization plan", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with content angle suggestions", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate SEO recommendations", required=True))
        self.flow.register_executor("validate", self._step_validate)

    def _step_analyze(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("analyze", data)
        result = self._model_router.execute("analyzer", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"analysis": result})

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("execute", data)
        result = self._model_router.execute("worker", prompt, context=data)
        return StepResult(step_name=step_name, model_used="qwen", status=EngineStatus.COMPLETED, output={"execution": result})

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("enhance", data)
        result = self._model_router.execute("creative", prompt, context=data)
        return StepResult(step_name=step_name, model_used="llama", status=EngineStatus.COMPLETED, output={"enhanced": result})

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("validate", data)
        result = self._model_router.execute("validator", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"validation": result})

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        templates = {"analyze": """Analyze: domain authority, technical issues (speed, mobile, crawlability), content gaps, keyword opportunities, backlink profile.\nSite: {site_data}\nKeywords: {keywords}""", "execute": """Generate: priority keyword list (volume, difficulty, intent), on-page optimizations, content calendar, technical fixes, link building targets.\nAnalysis: {analysis}""", "enhance": """Enhance: content angles that attract natural links, FAQ schema opportunities, featured snippet targets.\nSEO plan: {execution}""", "validate": """Validate: keywords are relevant, difficulty is achievable, recommendations prioritized by impact.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _keyword_difficulty_tier(difficulty: int) -> str:
        if difficulty < 30:
            return "easy"
        elif difficulty < 60:
            return "medium"
        return "hard"

    @staticmethod
    def _search_intent(keyword: str) -> str:
        buy_signals = ["buy", "price", "cheap", "best", "review", "discount", "deal"]
        info_signals = ["how", "what", "why", "guide", "tutorial"]
        kw = keyword.lower()
        if any(s in kw for s in buy_signals):
            return "transactional"
        if any(s in kw for s in info_signals):
            return "informational"
        return "navigational"
