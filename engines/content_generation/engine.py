"""
ContentGeneration Engine — Generate product descriptions, blog posts, email copy, and marketing content
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
        templates = {"analyze": """Analyze content requirements:\n- Product attributes and unique features\n- Target audience persona\n- Content type: {content_type}\n- Brand voice and tone guidelines\n- SEO keywords to target\n- Competitor content benchmarks\n- Platform requirements (length, format)\n\nProduct: {product_data}""", "execute": """Generate content:\n- Primary content piece\n- 3 headline variants\n- Meta description (SEO)\n- Key selling points (bullet format)\n- Call-to-action options\n- Image alt text suggestions\n- Social media snippets (3 platforms)\n\nAnalysis: {analysis}""", "enhance": """Enhance content with:\n- Emotional hooks\n- Storytelling elements\n- Sensory language\n- Power words\n- Social proof integration points\n\nContent: {execution}""", "validate": """Validate: no factual errors, brand voice consistent, SEO keywords present, all platforms covered, word counts within limits.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    CONTENT_TYPES = ["product_description", "blog_post", "email", "social_media", "ad_copy", "landing_page", "faq"]

    @staticmethod
    def _word_count(text: str) -> int:
        return len(text.split())

    @staticmethod
    def _readability_score(text: str) -> float:
        words = text.split()
        sentences = text.count(".") + text.count("!") + text.count("?")
        if sentences == 0: sentences = 1
        avg_words = len(words) / sentences
        return round(max(0, min(10, 10 - (avg_words - 15) * 0.5)), 2)

    @staticmethod
    def _keyword_density(text: str, keyword: str) -> float:
        words = text.lower().split()
        if not words: return 0.0
        count = words.count(keyword.lower())
        return round(count / len(words) * 100, 2)
