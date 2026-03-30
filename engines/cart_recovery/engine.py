"""
CartRecoveryEngine
Purpose: Generate targeted recovery campaigns for abandoned carts to recapture lost revenue
Input: ['abandoned_carts', 'recovery_config']
Output: ['recovery_campaigns', 'expected_recovery_rate']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class CartRecoveryEngine(BaseEngine):
    engine_name = "cart_recovery"
    required_input_fields = ["abandoned_carts", "recovery_config"]
    required_output_fields = ["recovery_campaigns", "expected_recovery_rate"]

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
                "You are a cart abandonment recovery specialist. Analyze the abandoned carts and recovery config "
                "to segment carts by recovery probability and identify the optimal recovery approach for each.\n\n"
                "Abandoned Carts: {abandoned_carts}\nRecovery Config: {recovery_config}\n\n"
                "Assess: cart value distribution, abandonment reasons, customer purchase history, "
                "time since abandonment, and available recovery channels. Segment by recovery priority."
            ),
            "execute": (
                "Design specific recovery campaigns for the abandoned carts.\n\n"
                "Abandoned Carts: {abandoned_carts}\nRecovery Config: {recovery_config}\n\n"
                "For each cart segment: specify channel, timing, offer, and messaging. Return as JSON: "
                '{{"recovery_campaigns": [{{"cart_id": str, "channel": str, "timing_hours": int, '
                '"offer_type": str, "offer_value": float, "message_template": str, "recovery_probability": float}}], '
                '"expected_recovery_rate": {{"overall": float, "by_segment": dict, "projected_revenue": float}}}}'
            ),
            "enhance": (
                "Write emotionally compelling recovery messages for each campaign.\n\n"
                "Abandoned Carts: {abandoned_carts}\nRecovery Config: {recovery_config}\n\n"
                "Craft subject lines with urgency and personalization, body copy that references specific cart items, "
                "a clear call-to-action, and a scarcity element where appropriate. Make it feel helpful, not pushy."
            ),
            "validate": (
                "Validate recovery campaigns for effectiveness and compliance.\n\n"
                "Abandoned Carts: {abandoned_carts}\nRecovery Config: {recovery_config}\n\n"
                "Check: Are timing windows within opt-in consent periods? Are offers within margin constraints? "
                "Are recovery probability estimates realistic? Is messaging compliant with anti-spam regulations? "
                "Flag any campaigns with poor ROI or compliance risks."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_recovery_probability(cart: dict[str, Any], hours_since_abandonment: float) -> float:
        """Estimate the probability of recovering an abandoned cart based on cart value, customer history, and time."""
        base_prob = 0.15
        cart_value = float(cart.get("value", 0))
        if cart_value > 100:
            base_prob += 0.05
        elif cart_value > 50:
            base_prob += 0.02
        if cart.get("customer_has_purchased_before", False):
            base_prob += 0.08
        if hours_since_abandonment <= 1:
            time_factor = 1.0
        elif hours_since_abandonment <= 24:
            time_factor = 0.7
        elif hours_since_abandonment <= 72:
            time_factor = 0.4
        else:
            time_factor = 0.15
        return round(min(base_prob * time_factor / 0.15, 0.65), 4)

    @staticmethod
    def _generate_recovery_offer(cart_value: float, customer_segment: str, config: dict[str, Any]) -> dict[str, Any]:
        """Generate an appropriate recovery offer based on cart value and customer segment."""
        offer_rules = config.get("offer_rules", {})
        segment_rule = offer_rules.get(customer_segment, offer_rules.get("default", {}))
        offer_type = segment_rule.get("type", "discount")
        if offer_type == "discount":
            pct = float(segment_rule.get("discount_pct", 0.1))
            return {"type": "discount", "value": round(cart_value * pct, 2), "unit": "currency", "discount_pct": pct}
        elif offer_type == "free_shipping":
            return {"type": "free_shipping", "value": float(segment_rule.get("shipping_value", 5.99)), "unit": "currency"}
        return {"type": "reminder", "value": 0.0, "unit": "none"}
