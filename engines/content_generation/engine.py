"""
ContentGeneration Engine — Generate SEO-optimized product titles, descriptions, and marketing copy
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ContentGenerationEngine(BaseEngine):
    engine_name = "content_generation"
    required_input_fields = ['product_data', 'content_type']
    required_output_fields = ['generated_content', 'content_metadata']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze product for content generation", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate optimized content", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with persuasive copywriting", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate SEO and content quality", required=True))
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
        templates = {"analyze": """Analyze product for content needs: key features, benefits, target audience, keywords, tone.\nProduct: {product_data}\nContent type: {content_type}""", "execute": """Generate content: title (60 chars), description (155 chars meta + full), bullet points (5), keywords (10).\nAnalysis: {analysis}""", "enhance": """Enhance with emotional triggers, power words, storytelling elements, urgency.\nContent: {execution}""", "validate": """Validate: SEO length limits, keyword density (1-3%), no duplicate content, readability score.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    CONTENT_TYPES = ["product_title", "product_description", "meta_description", "bullet_points", "ad_copy", "email_subject", "social_post"]

    @staticmethod
    def _keyword_density(text: str, keyword: str) -> float:
        words = text.lower().split()
        if not words:
            return 0.0
        count = sum(1 for w in words if keyword.lower() in w)
        return round(count / len(words) * 100, 2)

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        return text[:max_len-3] + "..." if len(text) > max_len else text
