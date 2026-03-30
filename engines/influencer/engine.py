"""
Influencer Engine

Purpose: Match brands with influencers and plan collaboration campaigns
Input:   ['campaign_goals', 'niche_data']
Output:  ['influencer_matches', 'collaboration_plan']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class InfluencerEngine(BaseEngine):
    engine_name = "influencer"
    required_input_fields = ['campaign_goals', 'niche_data']
    required_output_fields = ['influencer_matches', 'collaboration_plan']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze campaign goals and niche landscape",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate influencer matches and collaboration plans",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance collaboration ideas with creative concepts",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate influencer selections and ROI projections",
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
            "analyze": """You are an influencer marketing analyst. Analyze campaign goals and niche data to identify ideal influencer profiles.

Evaluate:
1. Target audience alignment with niche influencers
2. Campaign budget vs influencer tier feasibility
3. Content format preferences (reels, stories, posts, lives)
4. Authenticity and engagement rate benchmarks
5. Past collaboration performance in the niche

Campaign goals: {campaign_goals}
Niche data: {niche_data}

Return: ideal influencer profile, tier recommendation, budget allocation, and risk assessment.""",
            "execute": """Based on the analysis, generate influencer matches and collaboration plans.

Analysis results: {analysis}
Campaign goals: {campaign_goals}
Niche data: {niche_data}

For each influencer match provide:
- influencer_profile, follower_count, engagement_rate
- niche_relevance_score, estimated_reach
- collaboration_type, deliverables, timeline
- estimated_cost, projected_roi

Return as structured JSON with influencer_matches and collaboration_plan arrays.""",
            "enhance": """Enhance the influencer collaboration plan with creative campaign concepts.

For each collaboration, add:
- Unique content angle or storyline
- Viral potential hooks
- Cross-promotion opportunities
- User-generated content strategies

Current output: {execution}""",
            "validate": """Validate the influencer selections and collaboration plan.

Check:
1. Influencer engagement rates are realistic (1-10%)
2. Budget allocations sum to total budget
3. Timeline is feasible for deliverables
4. ROI projections are conservative and justified
5. No influencer conflicts of interest

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _score_influencer_fit(influencer: dict, campaign: dict) -> float:
        niche_match = 1.0 if influencer.get("niche") == campaign.get("target_niche") else 0.5
        engagement = float(influencer.get("engagement_rate", 0))
        audience_size = min(float(influencer.get("followers", 0)) / 1_000_000, 1.0)
        return round((niche_match * 4 + engagement * 3 + audience_size * 3) / 10 * 10, 2)

    @staticmethod
    def _estimate_roi(cost: float, estimated_reach: int, conversion_rate: float, avg_order_value: float) -> float:
        if cost == 0:
            return 0.0
        revenue = estimated_reach * conversion_rate * avg_order_value
        return round((revenue - cost) / cost * 100, 2)
