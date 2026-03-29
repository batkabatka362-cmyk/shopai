"""
DataEnrichmentEngine
Purpose: Enrich raw data records with additional context and derived attributes
Input: ['raw_data', 'enrichment_config']
Output: ['enriched_data', 'enrichment_stats']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class DataEnrichmentEngine(BaseEngine):
    engine_name = "data_enrichment"
    required_input_fields = ["raw_data", "enrichment_config"]
    required_output_fields = ["enriched_data", "enrichment_stats"]

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze input", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate output", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance output", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate output", required=True))
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
            "analyze": (
                "You are a data enrichment specialist. Review the raw data and enrichment configuration "
                "to plan which fields can be derived, inferred, or appended from external context.\n\n"
                "Raw Data: {raw_data}\nEnrichment Config: {enrichment_config}\n\n"
                "Identify: missing fields, normalization opportunities, derived attribute possibilities, "
                "and external data that could augment each record."
            ),
            "execute": (
                "Enrich each record in the raw data per the enrichment configuration.\n\n"
                "Raw Data: {raw_data}\nEnrichment Config: {enrichment_config}\n\n"
                "Apply all configured enrichment rules. For each record add derived fields, "
                "normalize values, and append contextual attributes. "
                "Return JSON: {{\"enriched_data\": [enriched_records], "
                "\"enrichment_stats\": {{\"records_enriched\": int, \"fields_added\": int, "
                "\"enrichment_rate\": float}}}}"
            ),
            "enhance": (
                "Add semantic enrichment to records — infer categories, tags, and quality scores.\n\n"
                "Raw Data: {raw_data}\nEnrichment Config: {enrichment_config}\n\n"
                "Suggest additional derived fields that would add analytical value: "
                "sentiment tags, category labels, quality tiers, and relevance scores."
            ),
            "validate": (
                "Validate the enriched records for correctness and completeness.\n\n"
                "Raw Data: {raw_data}\nEnrichment Config: {enrichment_config}\n\n"
                "Check: Are all required enrichment fields populated? Are derived values sensible? "
                "Are any records worse after enrichment? Return per-field validation summary."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _enrich_record(record: dict, enrichment_rules: list[dict]) -> dict:
        """Apply enrichment rules to a single record and return the enriched version."""
        enriched = dict(record)
        for rule in enrichment_rules:
            field = rule.get("field")
            default = rule.get("default")
            if field and field not in enriched:
                enriched[field] = default
        return enriched

    @staticmethod
    def _calculate_enrichment_score(original: dict, enriched: dict) -> float:
        """Calculate what fraction of total possible fields were populated after enrichment."""
        total_fields = len(enriched)
        if total_fields == 0:
            return 0.0
        populated = sum(1 for v in enriched.values() if v is not None and v != "")
        return round(populated / total_fields, 4)
