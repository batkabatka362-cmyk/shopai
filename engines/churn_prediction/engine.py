"""
ChurnPrediction Engine

Purpose: Predict customer churn and generate retention strategies
Input:   ['customer_data', 'activity_history']
Output:  ['churn_scores', 'retention_actions']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ChurnPredictionEngine(BaseEngine):
    engine_name = "churn_prediction"
    required_input_fields = ['customer_data', 'activity_history']
    required_output_fields = ['churn_scores', 'retention_actions']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze customer behavior and churn indicators",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Calculate churn scores and generate retention actions",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance retention strategies with creative win-back ideas",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate churn predictions and retention plan feasibility",
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
            "analyze": """You are a customer retention analyst. Analyze customer data and activity history to identify churn risk factors.

Evaluate:
1. Purchase frequency trends (declining, stable, growing)
2. Engagement metrics (email opens, site visits, app usage)
3. Support ticket history and sentiment
4. Payment issues or failed transactions
5. Competitive switching indicators

Customer data: {customer_data}
Activity history: {activity_history}

Return: churn risk factors, customer segments at risk, early warning signals, and data completeness assessment.""",
            "execute": """Based on the analysis, calculate churn scores and generate retention actions.

Analysis results: {analysis}
Customer data: {customer_data}
Activity history: {activity_history}

For each customer provide:
- customer_id, churn_score (0-100), risk_level (low/medium/high/critical)
- top_risk_factors, days_to_predicted_churn
- recommended_actions (specific retention interventions)
- estimated_retention_probability, customer_ltv

Return as structured JSON with churn_scores and retention_actions arrays.""",
            "enhance": """Enhance the retention strategy with creative win-back campaigns.

Add:
- Personalized re-engagement email sequences
- Exclusive loyalty offers
- Surprise and delight moments
- Community building initiatives

Current output: {execution}""",
            "validate": """Validate the churn predictions and retention plan.

Check:
1. Churn scores are properly normalized (0-100)
2. Risk levels align with score thresholds
3. Retention actions are actionable and specific
4. Cost of retention doesn't exceed customer LTV
5. No duplicate customer entries

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _calculate_churn_probability(days_since_last_purchase: int, avg_purchase_interval: float, engagement_score: float) -> float:
        if avg_purchase_interval == 0:
            return 0.5
        recency_factor = min(days_since_last_purchase / avg_purchase_interval, 3.0) / 3.0
        engagement_factor = 1.0 - min(engagement_score / 100, 1.0)
        churn_prob = (recency_factor * 0.6 + engagement_factor * 0.4)
        return round(min(max(churn_prob, 0.0), 1.0), 4)

    @staticmethod
    def _generate_retention_offer(customer_ltv: float, churn_probability: float, avg_order_value: float) -> dict:
        max_discount = min(customer_ltv * churn_probability * 0.1, avg_order_value * 0.3)
        if churn_probability > 0.8:
            offer_type = "aggressive_winback"
        elif churn_probability > 0.5:
            offer_type = "moderate_incentive"
        else:
            offer_type = "gentle_reminder"
        return {"offer_type": offer_type, "max_discount": round(max_discount, 2), "urgency": "high" if churn_probability > 0.7 else "normal"}
