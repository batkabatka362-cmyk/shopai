"""
VideoMarketing Engine

Purpose: Create video marketing scripts and distribution plans
Input:   ['product_data', 'video_config']
Output:  ['video_scripts', 'distribution_plan']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class VideoMarketingEngine(BaseEngine):
    engine_name = "video_marketing"
    required_input_fields = ['product_data', 'video_config']
    required_output_fields = ['video_scripts', 'distribution_plan']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze product and video marketing opportunities",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate video scripts and distribution plan",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance scripts with creative storytelling elements",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate scripts and distribution strategy",
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
            "analyze": """You are a video marketing strategist. Analyze the product and video configuration for optimal video content.

Evaluate:
1. Product visual appeal and demo potential
2. Target audience video consumption habits
3. Platform-specific video requirements (YouTube, TikTok, Instagram)
4. Competitor video content analysis
5. Budget and production capability assessment

Product data: {product_data}
Video config: {video_config}

Return: video opportunity assessment, format recommendations, platform priorities, and production requirements.""",
            "execute": """Based on the analysis, generate video scripts and a distribution plan.

Analysis results: {analysis}
Product data: {product_data}
Video config: {video_config}

For each video provide:
- video_type (product demo, testimonial, tutorial, ad)
- script (hook, body, cta), duration_seconds
- platform, aspect_ratio, thumbnail_concept
- distribution_schedule, promotion_budget

Return as structured JSON with video_scripts and distribution_plan arrays.""",
            "enhance": """Enhance the video scripts with compelling storytelling and hooks.

For each script, add:
- Attention-grabbing first 3 seconds
- Emotional storytelling arc
- Pattern interrupt moments
- Strong call-to-action variations

Current output: {execution}""",
            "validate": """Validate the video scripts and distribution plan.

Check:
1. Scripts fit within platform time limits
2. Hooks are compelling in first 3 seconds
3. CTAs are clear and actionable
4. Distribution schedule avoids content fatigue
5. Budget allocation is realistic per platform

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _generate_script_outline(product_name: str, video_type: str, duration_seconds: int) -> dict:
        if duration_seconds <= 15:
            structure = {"hook": 3, "body": 8, "cta": 4}
        elif duration_seconds <= 60:
            structure = {"hook": 5, "body": 40, "cta": 15}
        else:
            structure = {"hook": 10, "body": duration_seconds - 25, "cta": 15}
        return {"product": product_name, "type": video_type, "duration": duration_seconds, "segment_timing": structure}

    @staticmethod
    def _optimize_for_platform(platform: str) -> dict:
        specs = {
            "youtube": {"aspect_ratio": "16:9", "max_duration": 600, "min_resolution": "1080p"},
            "tiktok": {"aspect_ratio": "9:16", "max_duration": 180, "min_resolution": "720p"},
            "instagram_reels": {"aspect_ratio": "9:16", "max_duration": 90, "min_resolution": "720p"},
            "instagram_feed": {"aspect_ratio": "1:1", "max_duration": 60, "min_resolution": "720p"},
            "facebook": {"aspect_ratio": "16:9", "max_duration": 240, "min_resolution": "720p"},
        }
        return specs.get(platform.lower(), specs["youtube"])
