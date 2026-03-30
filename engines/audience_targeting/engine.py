"""
AudienceTargetingEngine
Purpose: Match campaign goals to the highest-value audience segments for maximum ad ROI
Input: ['campaign_goals', 'audience_data']
Output: ['target_audiences', 'targeting_recommendations']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AudienceTargetingEngine(BaseEngine):
    engine_name = "audience_targeting"
    required_input_fields = ["campaign_goals", "audience_data"]
    required_output_fields = ["target_audiences", "targeting_recommendations"]

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
                "You are a digital advertising and audience strategy expert. Analyze the campaign goals and available "
                "audience data to identify which audience segments are most likely to convert and deliver the best ROI.\n\n"
                "Campaign Goals: {campaign_goals}\nAudience Data: {audience_data}\n\n"
                "Assess: audience-goal alignment, segment size vs. quality tradeoffs, overlap between segments, "
                "historical performance signals, and which exclusions would improve efficiency. "
                "Return a targeting strategy assessment."
            ),
            "execute": (
                "Select and prioritize target audiences based on campaign goals and audience data.\n\n"
                "Campaign Goals: {campaign_goals}\nAudience Data: {audience_data}\n\n"
                "Rank audiences by match score and provide specific targeting recommendations. Return as JSON: "
                '{{"target_audiences": [{{"audience_id": str, "name": str, "size": int, "match_score": float, "estimated_cpa": float}}], '
                '"targeting_recommendations": [{{"recommendation": str, "audience": str, "rationale": str, "priority": str}}]}}'
            ),
            "enhance": (
                "Develop detailed audience activation strategies and creative direction for each target segment.\n\n"
                "Campaign Goals: {campaign_goals}\nAudience Data: {audience_data}\n\n"
                "For each target audience: recommend ad formats, messaging angles, bidding strategy, "
                "lookalike expansion opportunities, and retargeting sequences. Provide channel-specific guidance."
            ),
            "validate": (
                "Validate audience targeting selections for effectiveness and compliance.\n\n"
                "Campaign Goals: {campaign_goals}\nAudience Data: {audience_data}\n\n"
                "Check: Are selected audiences large enough to be statistically significant? "
                "Are match scores supported by evidence? Are there any targeting restrictions or compliance concerns? "
                "Is the targeting diverse enough to avoid over-concentration? Flag any issues."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_audience_match_score(audience: dict[str, Any], goals: dict[str, Any]) -> float:
        """Score how well an audience aligns with campaign goals based on intent and behavioral signals."""
        score = 0.0
        goal_type = goals.get("type", "conversion")
        if goal_type == "conversion":
            score += float(audience.get("purchase_intent_score", 0)) * 0.5
            score += float(audience.get("past_purchaser_rate", 0)) * 0.3
            score += float(audience.get("category_affinity_score", 0)) * 0.2
        elif goal_type == "awareness":
            score += float(audience.get("reach_potential", 0)) * 0.5
            score += float(audience.get("engagement_rate", 0)) * 0.3
            score += (1.0 - float(audience.get("past_exposure_rate", 0))) * 0.2
        elif goal_type == "retention":
            score += float(audience.get("churn_risk_score", 0)) * 0.4
            score += float(audience.get("recency_score", 0)) * 0.35
            score += float(audience.get("loyalty_score", 0)) * 0.25
        return round(min(score, 1.0), 4)

    @staticmethod
    def _filter_audiences(audiences: list[dict[str, Any]], min_size: int = 1000, min_match_score: float = 0.3) -> list[dict[str, Any]]:
        """Filter audiences below minimum size or match score thresholds."""
        return [
            a for a in audiences
            if int(a.get("size", 0)) >= min_size and float(a.get("match_score", 0)) >= min_match_score
        ]
