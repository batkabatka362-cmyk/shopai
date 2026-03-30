"""
Monitoring Engine — Monitor system and business performance — real-time metrics, alerts, health checks
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class MonitoringEngine(BaseEngine):
    engine_name = "monitoring"
    required_input_fields = ['system_metrics', 'thresholds']
    required_output_fields = ['monitoring_report', 'alerts']

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
        templates = {"analyze": """Analyze system health: engine response times, error rates, throughput, resource utilization, SLA compliance, anomaly detection.\nMetrics: {system_metrics}\nThresholds: {thresholds}""", "execute": """Generate monitoring report: health status per component, SLA compliance %, active alerts, trend analysis, capacity forecast.\nAnalysis: {analysis}""", "enhance": """Enhance: predictive health monitoring, auto-remediation suggestions.\nReport: {execution}""", "validate": """Validate: all components covered, thresholds appropriate, no alert fatigue.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _health_status(error_rate: float, latency_ms: float, uptime: float) -> str:
        if error_rate > 5 or latency_ms > 5000 or uptime < 0.95: return "critical"
        if error_rate > 1 or latency_ms > 2000 or uptime < 0.99: return "degraded"
        return "healthy"

    @staticmethod
    def _sla_compliance(actual: float, target: float) -> float:
        return round(min(100, actual / max(target, 0.01) * 100), 2)
