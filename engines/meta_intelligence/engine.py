"""
MetaIntelligence Engine — Intelligence about intelligence — monitors and optimizes the AI system's own cognitive performance
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class MetaIntelligenceEngine(BaseEngine):
    engine_name = "meta_intelligence"
    required_input_fields = ['engine_performance', 'intelligence_metrics']
    required_output_fields = ['optimization_plan', 'capability_map']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze system intelligence quality", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate intelligence optimization plan", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with emergent capability discovery", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate intelligence improvements", required=True))
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
        templates = {"analyze": """Analyze system intelligence:\n- Per-engine accuracy and decision quality\n- Cross-engine coordination effectiveness\n- Knowledge utilization rate\n- Learning velocity (how fast does system improve?)\n- Blind spots (what does system consistently miss?)\n- Reasoning chain quality\n- Model utilization efficiency\n\nPerformance: {engine_performance}\nMetrics: {intelligence_metrics}""", "execute": """Generate optimization plan:\n- Weakest engines to improve first\n- Knowledge gaps to fill\n- New capabilities to develop\n- Engine combination synergies to exploit\n- Prompt optimization targets\n- Model routing improvements\n\nAnalysis: {analysis}""", "enhance": """Enhance: emergent capabilities from combining engines in new ways, intelligence multiplication strategies.\n\nPlan: {execution}""", "validate": """Validate: improvements are measurable, no capability regression, optimization doesn't sacrifice safety.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _intelligence_score(accuracy: float, speed: float, adaptability: float) -> float:
        return round(accuracy * 0.5 + speed * 0.2 + adaptability * 0.3, 3)

    @staticmethod
    def _capability_gap(required: dict[str, float], current: dict[str, float]) -> dict[str, float]:
        gaps = {}
        for cap, req in required.items():
            cur = current.get(cap, 0)
            if cur < req:
                gaps[cap] = round(req - cur, 3)
        return gaps
