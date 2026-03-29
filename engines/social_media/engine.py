"""
SocialMedia Engine

Purpose: Create and schedule social media content optimized for each platform
Input:   ['content_brief', 'platform_targets']
Output:  ['social_posts', 'posting_schedule']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class SocialMediaEngine(BaseEngine):
    engine_name = "social_media"
    required_input_fields = ['content_brief', 'platform_targets']
    required_output_fields = ['social_posts', 'posting_schedule']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze content brief and platform requirements",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate platform-specific social media posts",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance posts with creative hooks and viral elements",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate posts meet platform guidelines and quality standards",
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
            "analyze": """You are a social media strategist. Analyze the content brief and target platforms.

Evaluate:
1. Content-platform fit for each target platform
2. Audience behavior patterns per platform
3. Optimal content formats (image, video, carousel, story)
4. Hashtag and keyword opportunities
5. Competitive landscape on each platform

Content brief: {content_brief}
Platform targets: {platform_targets}

Return: platform suitability scores, content format recommendations, and timing insights.""",
            "execute": """Based on the analysis, generate social media posts for each platform.

Analysis results: {analysis}
Content brief: {content_brief}
Platform targets: {platform_targets}

For each post provide:
- platform, post_type, content_text
- hashtags, mentions, media_suggestions
- optimal_post_time, engagement_prediction

Return as structured JSON with social_posts and posting_schedule arrays.""",
            "enhance": """Enhance the social media posts with viral and engaging elements.

For each post, add:
- Hook opening line
- Engagement prompt (question or CTA)
- Trending audio/format suggestions
- Cross-platform repurposing tips

Current output: {execution}""",
            "validate": """Validate the social media posts for quality and compliance.

Check:
1. Character limits per platform are respected
2. Hashtag counts are within best practices
3. No prohibited content or language
4. CTAs are clear and actionable
5. Posting schedule avoids conflicts

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _optimize_for_platform(content: str, platform: str) -> str:
        limits = {"twitter": 280, "instagram": 2200, "facebook": 63206, "tiktok": 4000, "linkedin": 3000}
        max_len = limits.get(platform.lower(), 2200)
        return content[:max_len]

    @staticmethod
    def _calculate_engagement_score(likes: int, comments: int, shares: int, impressions: int) -> float:
        if impressions == 0:
            return 0.0
        return round((likes + comments * 2 + shares * 3) / impressions * 100, 2)
