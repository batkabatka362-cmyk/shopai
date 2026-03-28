"""
AnomalyDetection Engine — Detect anomalies in data — statistical outliers, behavioral deviations, pattern breaks
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AnomalyDetectionEngine(BaseEngine):
    engine_name = "anomaly_detection"
    required_input_fields = ['data_stream', 'baseline']
    required_output_fields = ['anomalies', 'severity_scores']

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
        templates = {"analyze": """Analyze data for anomalies: compare against baseline, detect statistical outliers, pattern deviations, sudden changes.\nStream: {data_stream}\nBaseline: {baseline}""", "execute": """Generate anomaly report: detected anomalies with timestamps, severity scores, likely causes, recommended actions.\nAnalysis: {analysis}""", "enhance": """Enhance: contextual anomaly classification (expected seasonal vs true anomaly).\nReport: {execution}""", "validate": """Validate: false positive rate acceptable, all anomalies have severity, actionable.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _z_score(value: float, mean: float, std_dev: float) -> float:
        if std_dev == 0: return 0.0
        return round((value - mean) / std_dev, 3)

    @staticmethod
    def _is_anomaly(z_score: float, threshold: float = 2.5) -> bool:
        return abs(z_score) > threshold

    @staticmethod
    def _severity(z_score: float) -> str:
        z = abs(z_score)
        if z > 4: return "critical"
        if z > 3: return "high"
        if z > 2: return "medium"
        return "low"
