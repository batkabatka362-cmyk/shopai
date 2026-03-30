"""
TagManagement Engine

Purpose: Generate and manage product tags and taxonomy structures
Input:   ['product_data', 'taxonomy_config']
Output:  ['tag_assignments', 'taxonomy_updates']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class TagManagementEngine(BaseEngine):
    engine_name = "tag_management"
    required_input_fields = ['product_data', 'taxonomy_config']
    required_output_fields = ['tag_assignments', 'taxonomy_updates']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze product data and existing taxonomy structure",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate tag assignments and taxonomy updates",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance with creative tag suggestions for discoverability",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate tag consistency and taxonomy integrity",
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
            "analyze": """You are a product taxonomy specialist. Analyze product data and existing taxonomy for tagging opportunities.

Evaluate:
1. Current tag coverage and consistency
2. Missing tag categories and gaps
3. Tag naming conventions and standardization
4. Taxonomy depth and breadth appropriateness
5. Cross-category tagging opportunities

Product data: {product_data}
Taxonomy config: {taxonomy_config}

Return: taxonomy health assessment, gap analysis, standardization recommendations, and tagging strategy.""",
            "execute": """Based on the analysis, generate tag assignments and taxonomy updates.

Analysis results: {analysis}
Product data: {product_data}
Taxonomy config: {taxonomy_config}

For each product provide:
- product_id, primary_tags, secondary_tags
- category_path, attribute_tags
- search_tags, trending_tags

For taxonomy updates provide:
- new_categories, merged_categories
- renamed_tags, deprecated_tags

Return as structured JSON with tag_assignments and taxonomy_updates arrays.""",
            "enhance": """Enhance the tagging with creative discovery and SEO tags.

Add:
- Lifestyle and occasion tags
- Trending search term tags
- Cross-sell affinity tags
- Seasonal and event-based tags

Current output: {execution}""",
            "validate": """Validate the tag assignments and taxonomy changes.

Check:
1. All products have required primary tags
2. No orphan tags without products
3. Taxonomy hierarchy is consistent (no circular references)
4. Tag naming follows conventions
5. No duplicate or near-duplicate tags

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _generate_tags(product_name: str, description: str, category: str) -> list[str]:
        tags = []
        if category:
            tags.append(category.lower().replace(" ", "-"))
        words = (product_name + " " + description).lower().split()
        stop_words = {"the", "a", "an", "is", "are", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "from", "it", "this", "that"}
        meaningful = [w.strip(".,!?;:()") for w in words if w.strip(".,!?;:()") not in stop_words and len(w) > 2]
        freq: dict[str, int] = {}
        for w in meaningful:
            freq[w] = freq.get(w, 0) + 1
        top_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]
        tags.extend([w for w, _ in top_words if w not in tags])
        return tags[:15]

    @staticmethod
    def _validate_taxonomy(taxonomy: dict, max_depth: int = 5) -> dict:
        issues = []

        def check_depth(node: dict, current_depth: int, path: str) -> None:
            if current_depth > max_depth:
                issues.append(f"Exceeds max depth at {path}")
            for key, value in node.items():
                if isinstance(value, dict):
                    check_depth(value, current_depth + 1, f"{path}/{key}")

        check_depth(taxonomy, 0, "root")
        return {"valid": len(issues) == 0, "issues": issues, "depth_checked": max_depth}
