"""
BehavioralDataEngine
Purpose: Analyze user events and sessions to extract behavioral patterns and segments
Input: ['user_events', 'session_data']
Output: ['behavioral_patterns', 'user_segments']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class BehavioralDataEngine(BaseEngine):
    engine_name = "behavioral_data"
    required_input_fields = ["user_events", "session_data"]
    required_output_fields = ["behavioral_patterns", "user_segments"]

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
                "You are a behavioral analytics expert. Examine user events and session data "
                "to understand how users interact with the platform.\n\n"
                "User Events: {user_events}\nSession Data: {session_data}\n\n"
                "Identify: common event sequences, drop-off points, engagement signals, "
                "session length distributions, and anomalous behavior patterns."
            ),
            "execute": (
                "Extract behavioral patterns and user segments from the event and session data.\n\n"
                "User Events: {user_events}\nSession Data: {session_data}\n\n"
                "Identify recurring behavior patterns and cluster users into segments. "
                "Return JSON: {{\"behavioral_patterns\": [{{"
                "\"pattern_name\": str, \"description\": str, \"frequency\": float, \"user_count\": int}}], "
                "\"user_segments\": [{{\"segment_name\": str, \"criteria\": str, \"size\": int, "
                "\"avg_engagement_score\": float}}]}}"
            ),
            "enhance": (
                "Enrich behavioral segments with persona narratives and actionable marketing hooks.\n\n"
                "User Events: {user_events}\nSession Data: {session_data}\n\n"
                "For each segment create: a persona name, motivation profile, likely purchase triggers, "
                "and recommended personalization approaches."
            ),
            "validate": (
                "Validate the behavioral patterns and segments for statistical significance.\n\n"
                "User Events: {user_events}\nSession Data: {session_data}\n\n"
                "Check: Are segments mutually exclusive and collectively exhaustive? "
                "Are pattern frequencies supported by the event data? Are segment sizes meaningful? "
                "Flag any patterns that may be noise."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _extract_patterns(events: list[dict], min_frequency: int = 3) -> list[dict]:
        """Extract recurring event sequences that appear at least min_frequency times."""
        from collections import Counter
        sequence_counts: Counter = Counter()
        for event in events:
            event_type = event.get("type", "unknown")
            sequence_counts[event_type] += 1
        return [
            {"pattern": k, "count": v}
            for k, v in sequence_counts.items()
            if v >= min_frequency
        ]

    @staticmethod
    def _calculate_engagement_score(session: dict) -> float:
        """Calculate an engagement score for a session based on depth and interactions."""
        page_views = session.get("page_views", 0)
        interactions = session.get("interactions", 0)
        duration_minutes = session.get("duration_seconds", 0) / 60
        raw_score = page_views * 0.3 + interactions * 0.5 + duration_minutes * 0.2
        return round(min(raw_score / 10.0, 1.0), 4)
