"""
Notification Engine

Purpose: Plan and optimize multi-channel notification delivery
Input:   ['event_data', 'notification_config']
Output:  ['notification_plan', 'delivery_schedule']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class NotificationEngine(BaseEngine):
    engine_name = "notification"
    required_input_fields = ['event_data', 'notification_config']
    required_output_fields = ['notification_plan', 'delivery_schedule']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze events and determine notification strategy",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate notification plan and delivery schedule",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance notification copy and engagement elements",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate notification frequency and user preference compliance",
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
            "analyze": """You are a notification strategy expert. Analyze event data and notification configuration.

Evaluate:
1. Event types and their notification urgency
2. User channel preferences (email, push, SMS, in-app)
3. Notification fatigue risk assessment
4. Time zone and optimal delivery windows
5. Regulatory compliance (opt-in, frequency caps)

Event data: {event_data}
Notification config: {notification_config}

Return: event prioritization, channel recommendations, timing analysis, and frequency cap suggestions.""",
            "execute": """Based on the analysis, generate a notification plan and delivery schedule.

Analysis results: {analysis}
Event data: {event_data}
Notification config: {notification_config}

For each notification provide:
- event_type, priority_level, channel
- title, body, action_url
- delivery_time, fallback_channel
- user_segments, personalization_fields

Return as structured JSON with notification_plan and delivery_schedule arrays.""",
            "enhance": """Enhance the notifications with compelling and action-driving copy.

For each notification, improve:
- Attention-grabbing title
- Concise but informative body
- Clear call-to-action
- Personalization depth

Current output: {execution}""",
            "validate": """Validate the notification plan for user experience and compliance.

Check:
1. Notification frequency respects user preferences
2. Quiet hours are observed per time zone
3. All notifications have opt-out mechanisms
4. Priority levels match event urgency
5. No duplicate notifications for the same event

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _determine_channel(event_type: str, user_preferences: dict) -> str:
        urgency_map = {"order_update": "push", "promotion": "email", "price_drop": "push", "security": "sms", "newsletter": "email", "reminder": "push"}
        default_channel = urgency_map.get(event_type, "email")
        preferred = user_preferences.get("preferred_channel", default_channel)
        enabled_channels = user_preferences.get("enabled_channels", ["email"])
        return preferred if preferred in enabled_channels else (enabled_channels[0] if enabled_channels else "email")

    @staticmethod
    def _optimize_send_time(timezone: str, event_urgency: str) -> str:
        if event_urgency in ("critical", "high"):
            return "immediate"
        optimal_hours = {"morning": "09:00", "afternoon": "14:00", "evening": "19:00"}
        return f"{optimal_hours.get('afternoon', '14:00')} {timezone}"
