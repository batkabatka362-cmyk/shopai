"""
SuperIntelligence Engine — Orchestrates all intelligence layers — coordinates meta-learning, reasoning, and cross-engine intelligence for superhuman business decisions
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class SuperIntelligenceEngine(BaseEngine):
    engine_name = "super_intelligence"
    required_input_fields = ['global_context', 'strategic_objectives']
    required_output_fields = ['strategic_decisions', 'system_evolution_plan']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze global business context", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate strategic superintelligence output", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with paradigm-shifting insights", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate strategic coherence", required=True))
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
        templates = {"analyze": """Global intelligence analysis:\n- Synthesize inputs from ALL engines (75+)\n- Identify macro patterns invisible to individual engines\n- Cross-domain correlation (marketing <-> inventory <-> pricing)\n- Predict market shifts before signals are obvious\n- Assess total system capability vs market opportunity\n- Strategic landscape: where can we win that nobody sees?\n\nContext: {global_context}\nObjectives: {strategic_objectives}""", "execute": """Generate strategic output:\n- Top 3 strategic moves ranked by asymmetric upside\n- Resource reallocation across all engines\n- New engine combinations for emergent capabilities\n- Market timing decisions\n- 90-day strategic roadmap\n- System evolution priorities\n\nAnalysis: {analysis}""", "enhance": """Enhance: category-creating strategies, 10x thinking, non-obvious connections, contrarian bets with asymmetric payoff.\n\nStrategy: {execution}""", "validate": """Validate: strategies are actionable, resources exist, timeline realistic, risk-reward favorable, no blind optimism.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _strategic_score(opportunity: float, capability: float, timing: float) -> float:
        return round(opportunity * 0.4 + capability * 0.35 + timing * 0.25, 3)

    @staticmethod
    def _cross_engine_synergy(engine_a: str, engine_b: str, correlation: float) -> dict:
        return {"engines": [engine_a, engine_b], "synergy": round(correlation, 3), "exploit": correlation > 0.7}
