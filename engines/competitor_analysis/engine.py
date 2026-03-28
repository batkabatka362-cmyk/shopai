"""
CompetitorAnalysis Engine — Analyze competitor strategies, pricing, positioning, and weaknesses
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class CompetitorAnalysisEngine(BaseEngine):
    engine_name = "competitor_analysis"
    required_input_fields = ['competitor_data', 'market_segment']
    required_output_fields = ['competitor_profiles', 'strategy_gaps']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze competitor landscape and strategies", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate competitor profiles and gap analysis", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with competitive positioning angles", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate competitor data completeness", required=True))
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
            "analyze": """Analyze competitors in this market segment:\n- Pricing strategies and price points\n- Product range and differentiation\n- Marketing channels and ad spend indicators\n- Customer reviews sentiment\n- Strengths and weaknesses\n- Market share estimates\n\nCompetitors: {competitor_data}\nSegment: {market_segment}""",
            "execute": """Generate structured profiles:\n- Per competitor: pricing, positioning, strengths, weaknesses, threat level\n- Strategy gaps: what competitors miss\n- Blue ocean opportunities\n- Competitive advantage recommendations\n\nAnalysis: {analysis}""",
            "enhance": """Add strategic narrative: how to outmaneuver each competitor, what messaging beats theirs, where they're vulnerable.\n\nProfiles: {execution}""",
            "validate": """Validate: all competitors profiled, threat levels consistent with data, no unsupported claims, gaps are actionable.\n\nOutput: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\nData: " + str(data)

    @staticmethod
    def _price_position(our_price: float, competitor_prices: list[float]) -> str:
        if not competitor_prices:
            return "unknown"
        avg = sum(competitor_prices) / len(competitor_prices)
        if our_price < avg * 0.85:
            return "budget"
        elif our_price > avg * 1.15:
            return "premium"
        return "competitive"

    @staticmethod
    def _threat_level(competitor: dict) -> str:
        score = 0
        if float(competitor.get("market_share", 0)) > 0.2:
            score += 3
        if float(competitor.get("ad_spend", 0)) > 10000:
            score += 2
        if float(competitor.get("review_rating", 0)) > 4.5:
            score += 2
        return "high" if score >= 5 else "medium" if score >= 3 else "low"
