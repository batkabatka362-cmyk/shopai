"""
ReviewManagement Engine

Purpose: Analyze product reviews and generate appropriate response drafts
Input:   ['reviews', 'response_config']
Output:  ['review_analysis', 'response_drafts']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ReviewManagementEngine(BaseEngine):
    engine_name = "review_management"
    required_input_fields = ['reviews', 'response_config']
    required_output_fields = ['review_analysis', 'response_drafts']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze reviews for sentiment and common themes",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate review analysis and response drafts",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance responses with empathetic and brand-aligned tone",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate response appropriateness and brand consistency",
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
            "analyze": """You are a review management specialist. Analyze the reviews to identify patterns and prioritize responses.

Evaluate:
1. Sentiment distribution across reviews
2. Common complaint themes and praise points
3. Review urgency and response priority
4. Fake review indicators
5. Product improvement opportunities from feedback

Reviews: {reviews}
Response config: {response_config}

Return: review categorization, priority queue, theme analysis, and response strategy recommendations.""",
            "execute": """Based on the analysis, generate detailed review analysis and response drafts.

Analysis results: {analysis}
Reviews: {reviews}
Response config: {response_config}

For each review provide:
- review_id, rating, sentiment, category, priority
- key_issues, praise_points
- response_draft, response_tone, escalation_needed

Return as structured JSON with review_analysis and response_drafts arrays.""",
            "enhance": """Enhance the review responses with empathetic and brand-appropriate language.

For each response, improve:
- Emotional acknowledgment
- Personalization elements
- Solution-oriented language
- Brand voice consistency

Current output: {execution}""",
            "validate": """Validate the review responses for quality and appropriateness.

Check:
1. All reviews have corresponding responses
2. Negative reviews are handled with empathy
3. No defensive or argumentative language
4. Escalation flags are set for critical issues
5. Response length is appropriate per platform

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _categorize_review(rating: int, text: str) -> str:
        if rating <= 2:
            return "critical" if any(w in text.lower() for w in ["broken", "scam", "fraud", "dangerous", "lawsuit"]) else "negative"
        elif rating == 3:
            return "mixed"
        elif rating == 4:
            return "positive"
        return "excellent"

    @staticmethod
    def _generate_response_template(category: str, brand_name: str) -> str:
        templates = {
            "critical": f"Dear valued customer, we at {brand_name} are deeply concerned about your experience. We take this matter very seriously and would like to resolve this immediately. Please contact our support team directly so we can make this right.",
            "negative": f"Thank you for your feedback. We at {brand_name} are sorry to hear about your experience and would love the opportunity to address your concerns. Please reach out to our team so we can help.",
            "mixed": f"Thank you for sharing your thoughts! We at {brand_name} appreciate your honest feedback and are always working to improve. We'd love to hear more about how we can earn that 5-star experience.",
            "positive": f"Thank you so much for your kind words! We at {brand_name} are thrilled you had a great experience. We look forward to serving you again!",
            "excellent": f"Wow, thank you for the amazing review! The {brand_name} team is so grateful for your support. You made our day!",
        }
        return templates.get(category, templates["mixed"])
