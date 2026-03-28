"""
AutonomousScaling Engine — Self-scaling system — automatically scales resources, engines, and operations based on demand
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AutonomousScalingEngine(BaseEngine):
    engine_name = "autonomous_scaling"
    required_input_fields = ['load_metrics', 'scaling_policy']
    required_output_fields = ['scaling_actions', 'capacity_forecast']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze load and capacity", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate scaling actions", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with predictive scaling", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate scaling safety", required=True))
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
        templates = {"analyze": """Analyze scaling needs:\n- Current load vs capacity per engine\n- Growth trajectory (linear/exponential)\n- Bottleneck identification\n- Cost per unit of scale\n- Historical scaling patterns\n- Peak prediction\n\nLoad: {load_metrics}\nPolicy: {scaling_policy}""", "execute": """Generate scaling actions:\n- Scale up/down decisions per resource\n- Pre-scaling for predicted peaks\n- Cost-optimal scaling path\n- Engine priority during resource contention\n- Graceful degradation plan if scaling fails\n\nAnalysis: {analysis}""", "enhance": """Enhance: predictive auto-scaling, cost-aware scaling (spot vs reserved), multi-region distribution.\n\nActions: {execution}""", "validate": """Validate: scaling actions don't exceed budget, no oscillation (scale up then immediately down), minimum service levels maintained.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _utilization(used: float, capacity: float) -> float:
        return round(used / max(capacity, 0.01) * 100, 2)

    @staticmethod
    def _scale_decision(utilization: float, scale_up_threshold: float = 80, scale_down_threshold: float = 20) -> str:
        if utilization > scale_up_threshold: return "scale_up"
        if utilization < scale_down_threshold: return "scale_down"
        return "maintain"

    @staticmethod
    def _cost_per_unit(total_cost: float, total_capacity: float) -> float:
        return round(total_cost / max(total_capacity, 0.01), 4)
