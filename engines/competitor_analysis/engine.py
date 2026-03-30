"""
CompetitorAnalysis Engine — Analyze competitors — pricing, positioning, strengths/weaknesses, market share, strategy detection
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
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Domain analysis", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate structured output", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Creative enhancement", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Quality validation", required=True))
        self.flow.register_executor("validate", self._step_validate)

    def _step_analyze(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("analyze", data)
        r = self._model_router.execute("analyzer", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"analysis": r})

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("execute", data)
        r = self._model_router.execute("worker", prompt, context=data)
        return StepResult(step_name=step_name, model_used="qwen", status=EngineStatus.COMPLETED, output={"execution": r})

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("enhance", data)
        r = self._model_router.execute("creative", prompt, context=data)
        return StepResult(step_name=step_name, model_used="llama", status=EngineStatus.COMPLETED, output={"enhanced": r})

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("validate", data)
        r = self._model_router.execute("validator", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"validation": r})

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        templates = {"analyze": """Analyze competitors:\n- Who are the top 5-10 competitors?\n- Pricing strategy per competitor\n- Product range and quality positioning\n- Marketing channels and spend estimates\n- Customer reviews sentiment\n- Strengths and weaknesses\n- Market share estimates\n- Recent moves (new products, price changes, campaigns)\n\nCompetitor data: {competitor_data}\nSegment: {market_segment}""", "execute": """Generate competitive intelligence:\n- Competitor scorecards (1-10 per dimension)\n- Positioning map (price vs quality)\n- Strategy classification per competitor (cost leader/differentiator/niche)\n- Gap analysis: where no competitor serves well\n- Their likely next moves\n- Our competitive advantage opportunities\n\nAnalysis: {analysis}""", "enhance": """Enhance with strategic insights:\n- How to outposition each competitor\n- Messaging that exploits their weaknesses\n- Blue ocean opportunities\n\nIntelligence: {execution}""", "validate": """Validate: no bias toward any competitor, data-backed claims, gaps are real not wishful.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _market_share(revenue: float, total_market: float) -> float:
        if total_market == 0: return 0.0
        return round(revenue / total_market * 100, 2)

    @staticmethod
    def _competitive_score(strengths: int, weaknesses: int) -> float:
        total = strengths + weaknesses
        if total == 0: return 5.0
        return round(strengths / total * 10, 2)

    @staticmethod
    def _strategy_type(price_position: str, quality_position: str) -> str:
        if price_position == "low" and quality_position == "low": return "cost_leader"
        if price_position == "high" and quality_position == "high": return "premium"
        if price_position == "low" and quality_position == "high": return "value_disruptor"
        if price_position == "high" and quality_position == "low": return "overpriced"
        return "mid_market"

    @staticmethod
    def _threat_level(market_share: float, growth_rate: float) -> str:
        if market_share > 30 and growth_rate > 10: return "critical"
        if market_share > 15 or growth_rate > 20: return "high"
        if market_share > 5: return "moderate"
        return "low"
