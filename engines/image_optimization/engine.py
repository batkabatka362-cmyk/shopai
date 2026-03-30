"""
ImageOptimization Engine

Purpose: Analyze and optimize product images with alt text generation
Input:   ['image_data', 'optimization_config']
Output:  ['optimization_plan', 'alt_text_suggestions']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ImageOptimizationEngine(BaseEngine):
    engine_name = "image_optimization"
    required_input_fields = ['image_data', 'optimization_config']
    required_output_fields = ['optimization_plan', 'alt_text_suggestions']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze image quality and optimization opportunities",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate optimization plan and alt text suggestions",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance with creative image presentation ideas",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate optimization plan and accessibility compliance",
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
            "analyze": """You are an image optimization specialist. Analyze product images for quality and optimization potential.

Evaluate:
1. Image resolution and dimensions
2. File size and format efficiency
3. Background quality and consistency
4. Color accuracy and lighting
5. Mobile responsiveness and loading speed impact

Image data: {image_data}
Optimization config: {optimization_config}

Return: quality assessment per image, optimization priorities, format recommendations, and performance impact estimates.""",
            "execute": """Based on the analysis, generate an optimization plan and alt text suggestions.

Analysis results: {analysis}
Image data: {image_data}
Optimization config: {optimization_config}

For each image provide:
- image_id, current_format, recommended_format
- current_size, target_size, compression_level
- resize_dimensions, crop_suggestions
- alt_text, title_text, caption

Return as structured JSON with optimization_plan and alt_text_suggestions arrays.""",
            "enhance": """Enhance the image optimization plan with creative presentation ideas.

Add:
- Lifestyle image suggestions
- 360-degree view recommendations
- Zoom and detail shot suggestions
- A/B test image variant ideas

Current output: {execution}""",
            "validate": """Validate the image optimization plan for quality and accessibility.

Check:
1. Alt text is descriptive and under 125 characters
2. Compression levels won't degrade visual quality
3. All images meet minimum resolution requirements
4. Format recommendations are browser-compatible
5. WCAG accessibility standards are met

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _analyze_image_quality(width: int, height: int, file_size_kb: float, format_type: str) -> dict:
        min_dimension = min(width, height)
        quality = "high" if min_dimension >= 1000 else "medium" if min_dimension >= 500 else "low"
        pixels = width * height
        bytes_per_pixel = (file_size_kb * 1024) / max(pixels, 1)
        oversized = bytes_per_pixel > 3.0
        return {"quality": quality, "resolution": f"{width}x{height}", "bytes_per_pixel": round(bytes_per_pixel, 2), "oversized": oversized, "format": format_type}

    @staticmethod
    def _generate_alt_text(product_name: str, color: str, category: str) -> str:
        parts = [product_name]
        if color:
            parts.append(f"in {color}")
        if category:
            parts.append(f"- {category}")
        alt_text = " ".join(parts)
        return alt_text[:125] if len(alt_text) > 125 else alt_text
