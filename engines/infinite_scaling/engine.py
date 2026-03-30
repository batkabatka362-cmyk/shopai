"""
InfiniteScaling Engine — Infinite scaling engine — designs systems that scale without linear cost increase, leveraging automation and network effects
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class InfiniteScalingEngine(BaseEngine):
    engine_name = "infinite_scaling"
    required_input_fields = ['scaling_state', 'growth_trajectory']
    required_output_fields = ['scaling_blueprint', 'automation_roadmap']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze scaling constraints and opportunities", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate infinite scaling blueprint", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with exponential thinking", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate scaling physics", required=True))
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
        templates = {"analyze": """Analyze scaling dynamics:\n- Current cost-per-unit trajectory\n- Which costs scale linearly vs sublinearly?\n- Automation coverage: what % of ops is automated?\n- Network effects: do more users = more value per user?\n- Platform leverage: what infrastructure enables 10x with <2x cost?\n- Human bottlenecks: where does scaling require hiring?\n\nState: {scaling_state}\nTrajectory: {growth_trajectory}""", "execute": """Generate scaling blueprint:\n- Zero-marginal-cost opportunities\n- Automation roadmap (eliminate human steps)\n- Platform plays (build once, deploy many)\n- Network effect amplification strategies\n- API-first architecture for partner scaling\n- Self-serve scaling (customers help themselves)\n\nAnalysis: {analysis}""", "enhance": """Enhance: exponential thinking, what if 100x current scale? What breaks? What compounds? Platform ecosystem design.\n\nBlueprint: {execution}""", "validate": """Validate: scaling claims are physically possible, costs don't have hidden linear components, quality maintained at scale.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _scaling_efficiency(revenue: float, cost: float, previous_revenue: float, previous_cost: float) -> float:
        if previous_revenue == 0 or previous_cost == 0:
            return 0.0
        rev_growth = revenue / previous_revenue
        cost_growth = cost / previous_cost
        return round(rev_growth / max(cost_growth, 0.01), 3)

    @staticmethod
    def _is_superlinear(efficiency: float) -> bool:
        return efficiency > 1.0

    @staticmethod
    def _automation_coverage(automated_tasks: int, total_tasks: int) -> float:
        return round(automated_tasks / max(total_tasks, 1) * 100, 2)
