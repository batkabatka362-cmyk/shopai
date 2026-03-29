"""
FeedbackProcessingEngine
Purpose: Extract themes, prioritize feedback, and generate actionable insights from raw feedback
Input: ['raw_feedback', 'processing_rules']
Output: ['processed_feedback', 'actionable_insights']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class FeedbackProcessingEngine(BaseEngine):
    engine_name = "feedback_processing"
    required_input_fields = ["raw_feedback", "processing_rules"]
    required_output_fields = ["processed_feedback", "actionable_insights"]

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
                "You are a feedback intelligence analyst. Review the raw feedback corpus and processing rules "
                "to identify the dominant themes, recurring complaints, and high-impact signals.\n\n"
                "Raw Feedback: {raw_feedback}\nProcessing Rules: {processing_rules}\n\n"
                "Assess: theme frequency, sentiment distribution, rule applicability, "
                "and which feedback items have the highest priority for action. Return a structured analysis."
            ),
            "execute": (
                "Apply processing rules to transform raw feedback into structured insights.\n\n"
                "Raw Feedback: {raw_feedback}\nProcessing Rules: {processing_rules}\n\n"
                "For each feedback item: apply relevant rules, extract key themes, assign priority score. "
                "Then generate top actionable insights. Return as JSON: "
                '{{"processed_feedback": [{{"id": str, "themes": list, "priority": float, "tags": list}}], '
                '"actionable_insights": [{{"insight": str, "impact": str, "priority": str, "evidence_count": int}}]}}'
            ),
            "enhance": (
                "Transform the processed feedback into compelling, executive-ready insights.\n\n"
                "Raw Feedback: {raw_feedback}\nProcessing Rules: {processing_rules}\n\n"
                "For each actionable insight: write a clear problem statement, quantify business impact, "
                "suggest owner teams, and propose specific next steps. Make insights persuasive and prioritized."
            ),
            "validate": (
                "Validate that the processed feedback and insights are accurate and representative.\n\n"
                "Raw Feedback: {raw_feedback}\nProcessing Rules: {processing_rules}\n\n"
                "Check: Are processing rules correctly applied? Are themes accurately extracted? "
                "Are priority scores justified? Do insights trace back to actual feedback evidence? "
                "Flag any over-generalizations or unsupported conclusions."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _extract_themes(feedback_items: list[dict[str, Any]], min_frequency: int = 2) -> list[dict[str, Any]]:
        """Extract recurring themes from a list of feedback items."""
        theme_counts: dict[str, int] = {}
        theme_examples: dict[str, list[str]] = {}
        for item in feedback_items:
            for theme in item.get("themes", []):
                theme_counts[theme] = theme_counts.get(theme, 0) + 1
                if theme not in theme_examples:
                    theme_examples[theme] = []
                if len(theme_examples[theme]) < 3:
                    theme_examples[theme].append(item.get("content", "")[:100])
        return [
            {"theme": t, "frequency": c, "examples": theme_examples.get(t, [])}
            for t, c in sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
            if c >= min_frequency
        ]

    @staticmethod
    def _prioritize_feedback(feedback_items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
        """Sort feedback by priority score based on sentiment magnitude and rule weights."""
        weight_map = rules.get("priority_weights", {"sentiment": 0.4, "recency": 0.3, "frequency": 0.3})
        for item in feedback_items:
            sentiment_score = abs(float(item.get("sentiment", 0.0)))
            recency_score = float(item.get("recency_score", 0.5))
            frequency_score = float(item.get("frequency_score", 0.5))
            item["priority"] = (
                sentiment_score * weight_map.get("sentiment", 0.4)
                + recency_score * weight_map.get("recency", 0.3)
                + frequency_score * weight_map.get("frequency", 0.3)
            )
        return sorted(feedback_items, key=lambda x: x.get("priority", 0.0), reverse=True)
