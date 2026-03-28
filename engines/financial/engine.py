"""
Financial Engine — Financial intelligence — P&L analysis, cash flow, unit economics, forecasting
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class FinancialEngine(BaseEngine):
    engine_name = "financial"
    required_input_fields = ['financial_data', 'report_type']
    required_output_fields = ['financial_report', 'projections']

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
        templates = {"analyze": """Analyze financials: revenue, COGS, gross margin, operating expenses, net profit, cash flow, unit economics (CAC, LTV, payback).\nData: {financial_data}\nType: {report_type}""", "execute": """Generate financial report: P&L summary, margin analysis, cash flow projection, unit economics breakdown, break-even analysis, recommendations.\nAnalysis: {analysis}""", "enhance": """Enhance: visual-ready data formatting, narrative for non-financial audience.\nReport: {execution}""", "validate": """Validate: accounting consistent, margins realistic, projections sourced.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _gross_margin(revenue: float, cogs: float) -> float:
        if revenue == 0: return 0.0
        return round((revenue - cogs) / revenue * 100, 2)

    @staticmethod
    def _net_margin(revenue: float, total_costs: float) -> float:
        if revenue == 0: return 0.0
        return round((revenue - total_costs) / revenue * 100, 2)

    @staticmethod
    def _ltv_cac_ratio(ltv: float, cac: float) -> float:
        if cac == 0: return 0.0
        return round(ltv / cac, 2)

    @staticmethod
    def _break_even_units(fixed_costs: float, price: float, variable_cost: float) -> int:
        contribution = price - variable_cost
        if contribution <= 0: return -1
        return int(fixed_costs / contribution) + 1
