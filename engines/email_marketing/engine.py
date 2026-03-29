"""
EmailMarketing Engine

Purpose: Design and optimize email marketing campaigns with personalized content and scheduling
Input:   ['campaign_data', 'audience_segment']
Output:  ['email_content', 'send_schedule']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class EmailMarketingEngine(BaseEngine):
    engine_name = "email_marketing"
    required_input_fields = ['campaign_data', 'audience_segment']
    required_output_fields = ['email_content', 'send_schedule']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze campaign goals and audience segments",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate email content and scheduling plan",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance email copy with persuasive creative elements",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate email content and schedule quality",
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
            "analyze": """You are an email marketing strategist. Analyze the campaign data and audience segment to determine the best approach.

Evaluate:
1. Audience demographics and engagement history
2. Campaign objectives and KPIs
3. Optimal email frequency and timing
4. Personalization opportunities
5. Compliance with email regulations (CAN-SPAM, GDPR)

Campaign data: {campaign_data}
Audience segment: {audience_segment}

Return: campaign viability score, recommended approach, audience insights, and risk factors.""",
            "execute": """Based on the analysis, generate email content and a send schedule.

Analysis results: {analysis}
Campaign data: {campaign_data}
Audience segment: {audience_segment}

For each email in the campaign provide:
- subject_line, preview_text
- body_content (HTML-ready)
- call_to_action
- send_datetime (ISO format)
- segment_targeting

Return as structured JSON with email_content and send_schedule arrays.""",
            "enhance": """Enhance the email campaign with compelling creative elements.

For each email, add:
- A/B test subject line variants
- Emotional hooks and urgency triggers
- Personalization tokens
- Dynamic content blocks

Current output: {execution}""",
            "validate": """Validate the email campaign output for quality and deliverability.

Check:
1. Subject lines are under 60 characters
2. All emails have valid send times
3. No spam trigger words in content
4. CTA buttons are present in every email
5. Personalization tokens are properly formatted

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _calculate_send_time(audience_segment: dict) -> str:
        timezone = audience_segment.get("timezone", "UTC")
        peak_hours = audience_segment.get("peak_engagement_hours", [10, 14, 19])
        best_hour = peak_hours[0] if peak_hours else 10
        return f"{best_hour:02d}:00 {timezone}"

    @staticmethod
    def _personalize_content(template: str, user_data: dict) -> str:
        result = template
        for key, value in user_data.items():
            token = "{{" + key + "}}"
            result = result.replace(token, str(value))
        return result
