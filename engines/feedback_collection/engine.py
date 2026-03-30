"""
FeedbackCollectionEngine
Purpose: Collect, analyze sentiment, and categorize customer feedback from multiple sources
Input: ['feedback_sources', 'collection_criteria']
Output: ['collected_feedback', 'sentiment_summary']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class FeedbackCollectionEngine(BaseEngine):
    engine_name = "feedback_collection"
    required_input_fields = ["feedback_sources", "collection_criteria"]
    required_output_fields = ["collected_feedback", "sentiment_summary"]

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
                "You are a customer feedback analyst. Review the feedback sources and collection criteria "
                "to determine the best strategy for gathering meaningful, actionable customer feedback.\n\n"
                "Feedback Sources: {feedback_sources}\nCollection Criteria: {collection_criteria}\n\n"
                "Assess: source reliability, coverage gaps, sampling bias risks, "
                "and which criteria will yield the most actionable insights. Return a collection strategy."
            ),
            "execute": (
                "Collect and perform initial sentiment analysis on feedback from the specified sources.\n\n"
                "Feedback Sources: {feedback_sources}\nCollection Criteria: {collection_criteria}\n\n"
                "For each piece of feedback: extract content, assign sentiment score (-1 to 1), "
                "and assign a category. Summarize overall sentiment. Return as JSON: "
                '{{"collected_feedback": [{{"id": str, "source": str, "content": str, "sentiment": float, "category": str}}], '
                '"sentiment_summary": {{"avg_sentiment": float, "positive_pct": float, "negative_pct": float, "neutral_pct": float}}}}'
            ),
            "enhance": (
                "Enrich the collected feedback with deeper sentiment nuance and thematic groupings.\n\n"
                "Feedback Sources: {feedback_sources}\nCollection Criteria: {collection_criteria}\n\n"
                "Add: emotional tone labels, topic clusters, urgency flags for critical feedback, "
                "and a narrative summary of the most important themes. Make findings compelling for stakeholders."
            ),
            "validate": (
                "Validate the collected feedback and sentiment analysis for quality and representativeness.\n\n"
                "Feedback Sources: {feedback_sources}\nCollection Criteria: {collection_criteria}\n\n"
                "Check: Does the sample meet the collection criteria? Are sentiment scores reasonable? "
                "Is there sufficient coverage across sources? Flag any bias, spam, or low-quality entries."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _analyze_sentiment(text: str) -> float:
        """Return a basic sentiment score for a feedback string (-1.0 negative to 1.0 positive)."""
        positive_words = {"great", "excellent", "love", "amazing", "good", "perfect", "best", "fantastic", "happy"}
        negative_words = {"bad", "terrible", "awful", "hate", "worst", "horrible", "poor", "broken", "disappointing"}
        words = set(text.lower().split())
        pos_count = len(words & positive_words)
        neg_count = len(words & negative_words)
        total = pos_count + neg_count
        if total == 0:
            return 0.0
        return round((pos_count - neg_count) / total, 4)

    @staticmethod
    def _categorize_feedback(text: str, categories: list[str]) -> str:
        """Categorize feedback text into one of the provided categories based on keyword matching."""
        text_lower = text.lower()
        category_keywords: dict[str, list[str]] = {
            "product": ["product", "item", "quality", "feature", "design"],
            "shipping": ["shipping", "delivery", "package", "arrived", "transit"],
            "support": ["support", "help", "service", "agent", "response"],
            "pricing": ["price", "cost", "expensive", "cheap", "value", "discount"],
        }
        scores: dict[str, int] = {}
        for cat in categories:
            keywords = category_keywords.get(cat, [cat])
            scores[cat] = sum(1 for kw in keywords if kw in text_lower)
        if not scores or max(scores.values()) == 0:
            return "general"
        return max(scores, key=lambda k: scores[k])
