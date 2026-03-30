"""
Agbi Engine — Artificial General Business Intelligence — unified intelligence layer that reasons across all business domains like a human CEO
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AgbiEngine(BaseEngine):
    engine_name = "agbi"
    required_input_fields = ['business_state', 'market_environment']
    required_output_fields = ['business_strategy', 'execution_directives']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze complete business state", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate holistic business strategy", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with visionary leadership thinking", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate strategic completeness", required=True))
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
        templates = {"analyze": """Holistic business analysis (CEO-level):\n- Financial health: revenue, profit, cash flow, runway\n- Market position: share, growth, competitive advantage\n- Operations: efficiency, bottlenecks, capacity\n- Customer: satisfaction, retention, LTV trends\n- Team: capability gaps, productivity\n- Product: market fit, pipeline, lifecycle stage\n- Risk: existential threats, blind spots\n\nBusiness: {business_state}\nMarket: {market_environment}""", "execute": """Generate CEO-level directives:\n- Strategic priorities (top 3, ruthlessly focused)\n- Resource allocation across all functions\n- Kill list (what to stop doing)\n- Bet list (where to invest aggressively)\n- Hiring/capability priorities\n- 30/60/90 day milestones\n- Success metrics and review cadence\n\nAnalysis: {analysis}""", "enhance": """Enhance: visionary narrative (where are we going and why it matters), culture and morale considerations, stakeholder communication.\n\nStrategy: {execution}""", "validate": """Validate: strategy is internally consistent, resources don't exceed capacity, priorities are truly prioritized (not everything), risks addressed.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _business_health_score(revenue_growth: float, margin: float, cash_months: float, nps: float) -> float:
        r = min(10, max(0, revenue_growth * 10))
        m = min(10, max(0, margin * 10))
        c = min(10, max(0, cash_months))
        n = min(10, max(0, nps / 10))
        return round(r * 0.3 + m * 0.25 + c * 0.25 + n * 0.2, 2)

    @staticmethod
    def _strategic_focus_check(priorities: list[str]) -> dict:
        if len(priorities) <= 3:
            return {"focused": True, "count": len(priorities)}
        return {"focused": False, "count": len(priorities), "warning": "Too many priorities. Cut to 3."}
