"""
ProductDescription Engine

Purpose: Generate compelling product descriptions and SEO-optimized metadata
Input:   ['product_data', 'brand_voice']
Output:  ['descriptions', 'seo_metadata']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ProductDescriptionEngine(BaseEngine):
    engine_name = "product_description"
    required_input_fields = ['product_data', 'brand_voice']
    required_output_fields = ['descriptions', 'seo_metadata']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze product features and brand voice guidelines",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate product descriptions and SEO metadata",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance descriptions with persuasive storytelling",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate descriptions for accuracy and SEO quality",
            required=True,
        ))
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
        templates = {
            "analyze": """You are a product copywriting expert. Analyze the product data and brand voice to plan compelling descriptions.

Evaluate:
1. Key product features and benefits
2. Target audience pain points and desires
3. Brand voice tone and style guidelines
4. Competitive product positioning
5. SEO keyword opportunities

Product data: {product_data}
Brand voice: {brand_voice}

Return: feature-benefit mapping, audience insights, keyword targets, and content structure recommendations.""",
            "execute": """Based on the analysis, generate product descriptions and SEO metadata.

Analysis results: {analysis}
Product data: {product_data}
Brand voice: {brand_voice}

For each product provide:
- product_id, short_description, long_description
- bullet_points (5-7), feature_highlights
- meta_title, meta_description, keywords
- schema_markup_data

Return as structured JSON with descriptions and seo_metadata arrays.""",
            "enhance": """Enhance the product descriptions with persuasive storytelling and emotional appeal.

For each description, add:
- Sensory language and vivid imagery
- Social proof suggestions
- Urgency and scarcity elements
- Lifestyle benefit framing

Current output: {execution}""",
            "validate": """Validate the product descriptions for accuracy and SEO quality.

Check:
1. Descriptions match product specifications
2. Meta titles are under 60 characters
3. Meta descriptions are 150-160 characters
4. Primary keywords appear in title and first paragraph
5. No exaggerated or unsubstantiated claims

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _generate_bullet_points(features: list[str], max_points: int = 7) -> list[str]:
        bullets = []
        for feature in features[:max_points]:
            if not feature[0].isupper():
                feature = feature[0].upper() + feature[1:]
            if not feature.endswith((".", "!", "?")):
                feature = feature + "."
            bullets.append(feature)
        return bullets

    @staticmethod
    def _optimize_for_seo(text: str, primary_keyword: str, secondary_keywords: list[str]) -> dict:
        text_lower = text.lower()
        primary_count = text_lower.count(primary_keyword.lower())
        word_count = len(text.split())
        density = round(primary_count / max(word_count, 1) * 100, 2) if word_count > 0 else 0
        missing_secondary = [kw for kw in secondary_keywords if kw.lower() not in text_lower]
        return {"primary_keyword_count": primary_count, "keyword_density": density, "missing_keywords": missing_secondary, "word_count": word_count, "seo_score": min(10, primary_count * 2 + (len(secondary_keywords) - len(missing_secondary)) * 1.5)}
