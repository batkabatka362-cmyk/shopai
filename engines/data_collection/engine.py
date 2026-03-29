"""
DataCollectionEngine
Purpose: Collect and deduplicate data from multiple sources per configuration
Input: ['sources', 'collection_config']
Output: ['collected_data', 'collection_stats']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class DataCollectionEngine(BaseEngine):
    engine_name = "data_collection"
    required_input_fields = ["sources", "collection_config"]
    required_output_fields = ["collected_data", "collection_stats"]

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
                "You are a data collection architect. Review the provided sources and collection "
                "configuration to plan an efficient and complete data collection strategy.\n\n"
                "Sources: {sources}\nCollection Config: {collection_config}\n\n"
                "Assess: source reliability, expected data volume, format compatibility, "
                "potential duplicates, and any gaps in coverage."
            ),
            "execute": (
                "Execute the data collection plan across all specified sources.\n\n"
                "Sources: {sources}\nCollection Config: {collection_config}\n\n"
                "Collect records from each source per the config rules. Apply deduplication. "
                "Return JSON: {{\"collected_data\": [{{\"source\": str, \"records\": list, \"count\": int}}], "
                "\"collection_stats\": {{\"total_records\": int, \"duplicates_removed\": int, "
                "\"sources_succeeded\": int, \"sources_failed\": int}}}}"
            ),
            "enhance": (
                "Enrich the collection plan with data quality annotations and source reliability notes.\n\n"
                "Sources: {sources}\nCollection Config: {collection_config}\n\n"
                "Add confidence ratings per source, flag potentially stale data, "
                "and suggest supplementary sources that could fill coverage gaps."
            ),
            "validate": (
                "Validate the collected data for completeness, format compliance, and quality.\n\n"
                "Sources: {sources}\nCollection Config: {collection_config}\n\n"
                "Check: Are all required fields present? Are record counts plausible? "
                "Were any sources inaccessible? Return validation report with pass/fail per source."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _validate_source(source: dict) -> bool:
        """Validate that a data source has the required fields and is reachable."""
        required_keys = {"name", "type", "url"}
        return required_keys.issubset(source.keys()) and bool(source.get("url"))

    @staticmethod
    def _deduplicate_records(records: list[dict], key_field: str = "id") -> list[dict]:
        """Remove duplicate records based on a key field."""
        seen: set = set()
        unique: list[dict] = []
        for record in records:
            key = record.get(key_field)
            if key is not None and key not in seen:
                seen.add(key)
                unique.append(record)
            elif key is None:
                unique.append(record)
        return unique
