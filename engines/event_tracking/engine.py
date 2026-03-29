"""
EventTrackingEngine
Purpose: Process, classify, and aggregate raw events into structured tracking data
Input: ['events', 'tracking_rules']
Output: ['processed_events', 'event_stats']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class EventTrackingEngine(BaseEngine):
    engine_name = "event_tracking"
    required_input_fields = ["events", "tracking_rules"]
    required_output_fields = ["processed_events", "event_stats"]

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
                "You are an event analytics expert. Review the raw events and tracking rules "
                "to identify classification patterns, data quality issues, and aggregation opportunities.\n\n"
                "Events: {events}\nTracking Rules: {tracking_rules}\n\n"
                "Assess: event schema consistency, rule coverage gaps, high-frequency event types, "
                "and any malformed or duplicate events. Return a structured analysis."
            ),
            "execute": (
                "Process and classify the raw events according to the tracking rules.\n\n"
                "Events: {events}\nTracking Rules: {tracking_rules}\n\n"
                "For each event: apply the matching tracking rule, normalize the schema, "
                "and assign a category. Then compute aggregate stats. Return as JSON: "
                '{{"processed_events": [{{"id": str, "type": str, "category": str, "properties": dict}}], '
                '"event_stats": {{"total": int, "by_type": dict, "by_category": dict}}}}'
            ),
            "enhance": (
                "Enrich the processed events with contextual metadata and behavioral signals.\n\n"
                "Events: {events}\nTracking Rules: {tracking_rules}\n\n"
                "Add: session context, user journey stage, intent signals, and anomaly flags. "
                "Provide narrative summaries for high-value event clusters."
            ),
            "validate": (
                "Validate the processed events and stats for correctness and completeness.\n\n"
                "Events: {events}\nTracking Rules: {tracking_rules}\n\n"
                "Check: Do all events match a tracking rule? Are stats internally consistent? "
                "Are required fields present? Flag events that failed classification or have data quality issues."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _classify_event(event: dict[str, Any], rules: list[dict[str, Any]]) -> str:
        """Match an event against tracking rules and return its category."""
        event_type = event.get("type", "")
        for rule in rules:
            if rule.get("event_type") == event_type:
                return rule.get("category", "uncategorized")
            patterns = rule.get("patterns", [])
            if any(p in event_type for p in patterns):
                return rule.get("category", "uncategorized")
        return "uncategorized"

    @staticmethod
    def _aggregate_events(events: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate events into counts by type and category."""
        by_type: dict[str, int] = {}
        by_category: dict[str, int] = {}
        for event in events:
            etype = event.get("type", "unknown")
            ecat = event.get("category", "uncategorized")
            by_type[etype] = by_type.get(etype, 0) + 1
            by_category[ecat] = by_category.get(ecat, 0) + 1
        return {"total": len(events), "by_type": by_type, "by_category": by_category}
