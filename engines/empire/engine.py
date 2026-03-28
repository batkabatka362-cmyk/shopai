"""
Empire Engine — Multi-brand, multi-store empire management — orchestrates portfolio of businesses as unified empire
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class EmpireEngine(BaseEngine):
    engine_name = "empire"
    required_input_fields = ['portfolio_data', 'empire_goals']
    required_output_fields = ['empire_strategy', 'portfolio_actions']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze empire portfolio health", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate empire-level strategy", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with empire synergies", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate portfolio coherence", required=True))
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
        templates = {"analyze": """Empire portfolio analysis:\n- Per-store/brand: revenue, growth, profit, market position\n- Portfolio balance: risk diversification, market coverage\n- Shared resources: what can be centralized?\n- Cross-sell/cross-brand opportunities\n- Cannibalization risk between brands\n- Capital allocation efficiency\n- Weakest link identification\n\nPortfolio: {portfolio_data}\nGoals: {empire_goals}""", "execute": """Generate empire strategy:\n- Portfolio moves: grow/maintain/harvest/divest per brand\n- Capital reallocation (from cash cows to stars)\n- Shared infrastructure opportunities\n- New market entry candidates\n- Brand architecture (house of brands vs branded house)\n- Synergy exploitation plan\n\nAnalysis: {analysis}""", "enhance": """Enhance: empire moat building, network effects across brands, flywheel design, category domination plays.\n\nStrategy: {execution}""", "validate": """Validate: no brand cannibalization, capital allocation sums correctly, portfolio is diversified, synergies are real not theoretical.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _portfolio_score(stores: list[dict]) -> dict:
        total_rev = sum(s.get("revenue", 0) for s in stores)
        avg_margin = sum(s.get("margin", 0) for s in stores) / max(len(stores), 1)
        return {"total_revenue": total_rev, "avg_margin": round(avg_margin, 3), "store_count": len(stores)}

    @staticmethod
    def _bcg_classify(growth: float, share: float) -> str:
        if growth > 0.1 and share > 0.2: return "star"
        if growth <= 0.1 and share > 0.2: return "cash_cow"
        if growth > 0.1 and share <= 0.2: return "question_mark"
        return "dog"
