"""
Catalog Engine

Purpose: Manage and optimize product catalog — categorization, hierarchy, and discoverability
Input:   ['catalog_data', 'categories']
Output:  ['optimized_catalog', 'recommendations']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class CatalogEngine(BaseEngine):
    engine_name = "catalog"
    required_input_fields = ['catalog_data', 'categories']
    required_output_fields = ['optimized_catalog', 'recommendations']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze input and assess viability",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate structured domain output",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance output with creative insights",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate output quality and consistency",
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
            "analyze": """Analyze catalog structure for optimization opportunities.

Check: category depth, product distribution per category, orphaned products, missing tags, SEO gaps, duplicate detection.

Catalog: {catalog_data}
Categories: {categories}""",
            "execute": """Generate optimized catalog structure.

- Reorganize categories for better navigation
- Assign uncategorized products
- Generate missing tags and metadata
- Create cross-sell/upsell mappings

Analysis: {analysis}""",
            "enhance": """Enhance catalog entries with SEO-optimized titles, descriptions, and tag suggestions.

Catalog: {execution}""",
            "validate": """Validate: no orphaned products, all categories populated, no duplicates, SEO fields complete.

Catalog: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _build_category_tree(categories: list[dict]) -> dict:
        tree: dict = {}
        for cat in categories:
            path = cat.get("path", "").split("/")
            node = tree
            for part in path:
                if part not in node:
                    node[part] = {}
                node = node[part]
        return tree

    @staticmethod
    def _detect_orphans(products: list[dict], categories: list[str]) -> list[dict]:
        cat_set = set(categories)
        return [p for p in products if p.get("category", "") not in cat_set]

    @staticmethod
    def _suggest_tags(product: dict) -> list[str]:
        title = product.get("title", "").lower()
        words = title.split()
        return [w for w in words if len(w) > 3][:5]

