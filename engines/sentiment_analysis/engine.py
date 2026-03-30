"""
SentimentAnalysis Engine

Purpose: Analyze text sentiment and extract key phrases from customer feedback
Input:   ['text_data', 'analysis_config']
Output:  ['sentiment_scores', 'sentiment_summary']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class SentimentAnalysisEngine(BaseEngine):
    engine_name = "sentiment_analysis"
    required_input_fields = ['text_data', 'analysis_config']
    required_output_fields = ['sentiment_scores', 'sentiment_summary']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze text data for sentiment patterns",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Calculate sentiment scores and generate summary",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance analysis with contextual insights",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate sentiment classifications and consistency",
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
            "analyze": """You are a sentiment analysis expert. Analyze the provided text data for emotional tone and sentiment patterns.

Evaluate:
1. Overall sentiment distribution (positive, negative, neutral)
2. Emotion detection (joy, anger, sadness, surprise, fear)
3. Aspect-based sentiment (product quality, service, price, etc.)
4. Sarcasm and irony detection
5. Language and cultural context considerations

Text data: {text_data}
Analysis config: {analysis_config}

Return: preliminary sentiment distribution, key themes, language quality assessment, and analysis approach.""",
            "execute": """Based on the analysis, calculate detailed sentiment scores and generate a comprehensive summary.

Analysis results: {analysis}
Text data: {text_data}
Analysis config: {analysis_config}

For each text entry provide:
- text_id, sentiment_label, sentiment_score (-1.0 to 1.0)
- confidence, detected_emotions
- key_phrases, aspect_sentiments

Return as structured JSON with sentiment_scores and sentiment_summary objects.""",
            "enhance": """Enhance the sentiment analysis with actionable business insights.

Add:
- Trend analysis over time
- Competitor sentiment comparison suggestions
- Priority action items based on negative sentiment
- Positive sentiment amplification opportunities

Current output: {execution}""",
            "validate": """Validate the sentiment analysis results for accuracy and consistency.

Check:
1. Sentiment scores are within valid range (-1.0 to 1.0)
2. Labels match score ranges (positive > 0.2, negative < -0.2)
3. Confidence scores are reasonable
4. Key phrases are relevant to the text
5. No contradictory classifications

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _classify_sentiment(score: float) -> str:
        if score > 0.2:
            return "positive"
        elif score < -0.2:
            return "negative"
        return "neutral"

    @staticmethod
    def _extract_key_phrases(text: str, max_phrases: int = 5) -> list[str]:
        words = text.lower().split()
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "can", "shall", "to", "of", "in", "for", "on", "with", "at", "by", "from", "it", "this", "that", "and", "or", "but", "not", "no", "so", "if", "as"}
        filtered = [w.strip(".,!?;:") for w in words if w.strip(".,!?;:") not in stop_words and len(w) > 2]
        freq: dict[str, int] = {}
        for w in filtered:
            freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:max_phrases]]
