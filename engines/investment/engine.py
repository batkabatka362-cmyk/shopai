"""
Investment Engine — Evaluate investment decisions — ROI analysis, payback period, risk-adjusted returns
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class InvestmentEngine(BaseEngine):
    engine_name = "investment"
    required_input_fields = ['investment_options', 'constraints']
    required_output_fields = ['investment_analysis', 'recommendations']

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
        r = self._model_router.execute("analyzer", self._build_prompt("analyze", data), context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"analysis": r})

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        r = self._model_router.execute("worker", self._build_prompt("execute", data), context=data)
        return StepResult(step_name=step_name, model_used="qwen", status=EngineStatus.COMPLETED, output={"execution": r})

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        r = self._model_router.execute("creative", self._build_prompt("enhance", data), context=data)
        return StepResult(step_name=step_name, model_used="llama", status=EngineStatus.COMPLETED, output={"enhanced": r})

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        r = self._model_router.execute("validator", self._build_prompt("validate", data), context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"validation": r})

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        templates = {"analyze": """Analyze investments: projected returns, risk profile, payback period, opportunity cost, capital requirements, strategic alignment.\nOptions: {investment_options}\nConstraints: {constraints}""", "execute": """Generate investment analysis: NPV/IRR per option, risk-adjusted ranking, recommended allocation, timeline, milestones.\nAnalysis: {analysis}""", "enhance": """Enhance: asymmetric upside opportunities, optionality value.\nAnalysis: {execution}""", "validate": """Validate: return projections conservative, risks acknowledged, diversification adequate.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _roi(gain: float, cost: float) -> float:
        if cost == 0: return 0.0
        return round((gain - cost) / cost * 100, 2)

    @staticmethod
    def _payback_months(investment: float, monthly_return: float) -> float:
        if monthly_return <= 0: return float("inf")
        return round(investment / monthly_return, 1)

    @staticmethod
    def _npv(cash_flows: list[float], discount_rate: float) -> float:
        total = 0.0
        for i, cf in enumerate(cash_flows):
            total += cf / (1 + discount_rate) ** i
        return round(total, 2)
