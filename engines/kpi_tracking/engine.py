"""
KpiTrackingEngine
Purpose: Track KPI performance against targets and detect anomalies in business metrics
Input: ['kpi_data', 'targets']
Output: ['kpi_status', 'performance_summary']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class KpiTrackingEngine(BaseEngine):
    engine_name = "kpi_tracking"
    required_input_fields = ["kpi_data", "targets"]
    required_output_fields = ["kpi_status", "performance_summary"]

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
                "You are a business performance analyst. Review the KPI data and targets "
                "to assess overall performance health and identify metrics that need immediate attention.\n\n"
                "KPI Data: {kpi_data}\nTargets: {targets}\n\n"
                "Assess: which KPIs are on-track vs. off-track, trend directions, "
                "anomalies or sudden changes, and inter-KPI correlations. Return a structured health assessment."
            ),
            "execute": (
                "Calculate KPI status for each metric and produce a performance summary.\n\n"
                "KPI Data: {kpi_data}\nTargets: {targets}\n\n"
                "For each KPI: compute attainment percentage, status (on_track/at_risk/off_track), "
                "and trend. Summarize overall business performance. Return as JSON: "
                '{{"kpi_status": [{{"kpi": str, "actual": float, "target": float, "attainment": float, "status": str, "trend": str}}], '
                '"performance_summary": {{"overall_health": str, "kpis_on_track": int, "kpis_at_risk": int, "kpis_off_track": int}}}}'
            ),
            "enhance": (
                "Enrich the KPI dashboard with narrative context, root cause hypotheses, and action plans.\n\n"
                "KPI Data: {kpi_data}\nTargets: {targets}\n\n"
                "For each off-track or at-risk KPI: write a brief diagnosis, suggest root causes, "
                "and recommend 2-3 specific corrective actions with expected impact timelines."
            ),
            "validate": (
                "Validate the KPI calculations and performance summary for accuracy.\n\n"
                "KPI Data: {kpi_data}\nTargets: {targets}\n\n"
                "Check: Are attainment percentages mathematically correct? Are status thresholds appropriate? "
                "Is the overall health score consistent with individual KPI statuses? "
                "Flag any data anomalies or miscalculations."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_kpi_score(actual: float, target: float) -> float:
        """Calculate KPI attainment score as a percentage of target (capped at 150%)."""
        if target == 0:
            return 0.0
        return round(min(actual / target, 1.5), 4)

    @staticmethod
    def _detect_anomalies(values: list[float], std_multiplier: float = 2.0) -> list[int]:
        """Detect anomalous indices in a time series using standard deviation method."""
        if len(values) < 3:
            return []
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = variance ** 0.5
        threshold = std_multiplier * std
        return [i for i, v in enumerate(values) if abs(v - mean) > threshold]
