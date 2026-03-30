"""
SearchOptimization Engine

Purpose: Optimize site search relevance and improve product discoverability
Input:   ['search_data', 'catalog_data']
Output:  ['search_improvements', 'relevance_scores']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class SearchOptimizationEngine(BaseEngine):
    engine_name = "search_optimization"
    required_input_fields = ['search_data', 'catalog_data']
    required_output_fields = ['search_improvements', 'relevance_scores']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze search patterns and catalog coverage",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate search improvements and relevance scoring",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance with creative search experience improvements",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate search improvements and relevance accuracy",
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
            "analyze": """You are a search optimization expert. Analyze search data and catalog coverage for improvement opportunities.

Evaluate:
1. Top search queries and their result quality
2. Zero-result searches and coverage gaps
3. Search-to-purchase conversion rates
4. Synonym and typo handling effectiveness
5. Faceted search and filter utilization

Search data: {search_data}
Catalog data: {catalog_data}

Return: search quality assessment, gap analysis, query pattern insights, and improvement priorities.""",
            "execute": """Based on the analysis, generate search improvements and relevance scores.

Analysis results: {analysis}
Search data: {search_data}
Catalog data: {catalog_data}

Provide:
- synonym_mappings, typo_corrections
- boost_rules (product, category, attribute)
- zero_result_solutions, redirect_rules
- relevance_tuning_parameters

Return as structured JSON with search_improvements and relevance_scores arrays.""",
            "enhance": """Enhance the search optimization with creative discovery features.

Add:
- Autocomplete suggestion improvements
- Trending searches widget
- Visual search suggestions
- Personalized search ranking ideas

Current output: {execution}""",
            "validate": """Validate the search improvements for quality and impact.

Check:
1. Synonym mappings are accurate and bidirectional
2. Boost rules don't over-promote low-quality products
3. Zero-result solutions are relevant
4. Redirect rules don't create loops
5. Relevance scores are properly normalized

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _analyze_search_patterns(queries: list[dict]) -> dict:
        total = len(queries)
        zero_results = sum(1 for q in queries if q.get("results_count", 0) == 0)
        avg_results = sum(q.get("results_count", 0) for q in queries) / max(total, 1)
        converted = sum(1 for q in queries if q.get("converted", False))
        return {
            "total_queries": total,
            "zero_result_rate": round(zero_results / max(total, 1) * 100, 2),
            "avg_results_per_query": round(avg_results, 1),
            "search_conversion_rate": round(converted / max(total, 1) * 100, 2),
        }

    @staticmethod
    def _optimize_synonyms(query: str, existing_synonyms: dict[str, list[str]]) -> list[str]:
        suggestions = []
        query_lower = query.lower().strip()
        for term, syns in existing_synonyms.items():
            if query_lower in syns or term == query_lower:
                suggestions.extend(syns)
                if term not in suggestions:
                    suggestions.append(term)
        return list(set(s for s in suggestions if s != query_lower))
