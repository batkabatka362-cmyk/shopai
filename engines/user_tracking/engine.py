"""
UserTrackingEngine
Purpose: Track individual user behavior and build comprehensive user profiles
Input: ['user_id', 'tracking_config']
Output: ['user_profile', 'tracking_events']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class UserTrackingEngine(BaseEngine):
    engine_name = "user_tracking"
    required_input_fields = ["user_id", "tracking_config"]
    required_output_fields = ["user_profile", "tracking_events"]

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
                "You are a user behavior analyst. Review the tracking configuration and user context "
                "to determine what events and signals are most relevant for building this user's profile.\n\n"
                "User ID: {user_id}\nTracking Config: {tracking_config}\n\n"
                "Identify: key behavioral dimensions to track, data gaps, privacy constraints, "
                "and the most informative signals given the config. Return a structured analysis plan."
            ),
            "execute": (
                "Build a comprehensive user profile and event timeline based on the tracking configuration.\n\n"
                "User ID: {user_id}\nTracking Config: {tracking_config}\n\n"
                "Generate: a user profile with behavioral attributes, preferences, and engagement metrics, "
                "plus a list of key tracking events. Return as JSON with fields: "
                '{{"user_profile": {{"attributes": dict, "preferences": list, "engagement_score": float}}, '
                '"tracking_events": [{{"event_type": str, "timestamp": str, "properties": dict}}]}}'
            ),
            "enhance": (
                "Enrich the user profile with predictive insights and personalization signals.\n\n"
                "User ID: {user_id}\nTracking Config: {tracking_config}\n\n"
                "Add: predicted next actions, churn risk score, lifetime value estimate, "
                "and recommended personalization strategies. Make the profile actionable for marketing and product teams."
            ),
            "validate": (
                "Validate the user profile and tracking events for data integrity and compliance.\n\n"
                "User ID: {user_id}\nTracking Config: {tracking_config}\n\n"
                "Check: Are all required tracking fields populated? Do events follow the correct schema? "
                "Are there privacy or consent issues? Flag any anomalies or data quality problems."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _build_user_profile(events: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        """Aggregate user events into a structured profile with key behavioral attributes."""
        profile: dict[str, Any] = {
            "event_count": len(events),
            "event_types": list({e.get("event_type", "unknown") for e in events}),
            "attributes": {},
        }
        for rule in config.get("attribute_rules", []):
            key = rule.get("attribute")
            source = rule.get("source_field")
            if key and source:
                values = [e.get(source) for e in events if source in e]
                if values:
                    profile["attributes"][key] = values[-1]
        return profile

    @staticmethod
    def _calculate_lifetime_value(purchase_events: list[dict[str, Any]], avg_order_value: float = 0.0) -> float:
        """Estimate customer lifetime value from purchase history and average order value."""
        if not purchase_events:
            return 0.0
        total_spent = sum(float(e.get("amount", avg_order_value)) for e in purchase_events)
        purchase_count = len(purchase_events)
        if purchase_count == 0:
            return 0.0
        frequency_multiplier = min(purchase_count / 12.0, 3.0)
        return total_spent * frequency_multiplier
