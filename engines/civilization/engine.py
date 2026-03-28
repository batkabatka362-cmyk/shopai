"""
Civilization Engine — Civilization-scale orchestration — manages ecosystem of empires, markets, and autonomous systems at maximum scale
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class CivilizationEngine(BaseEngine):
    engine_name = "civilization"
    required_input_fields = ['ecosystem_state', 'civilization_objectives']
    required_output_fields = ['civilization_plan', 'system_directives']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze civilization-scale ecosystem", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate civilization-level orchestration", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with long-term vision", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate civilization sustainability", required=True))
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
        templates = {"analyze": """Civilization-scale analysis:\n- Total ecosystem health across all empires\n- Market coverage: gaps and overlaps\n- Resource utilization across entire system\n- Network effects and flywheel strength\n- Competitive moat depth\n- Long-term sustainability (5+ year view)\n- Systemic risks that could cascade\n\nEcosystem: {ecosystem_state}\nObjectives: {civilization_objectives}""", "execute": """Generate civilization directives:\n- Empire coordination strategy\n- Global resource allocation\n- Market expansion sequence\n- Technology investment priorities\n- Talent and capability development\n- Risk hedging across entire portfolio\n- 1/3/5 year milestones\n\nAnalysis: {analysis}""", "enhance": """Enhance: generational thinking, compounding advantages, creating conditions for emergent opportunities, legacy building.\n\nPlan: {execution}""", "validate": """Validate: plan is sustainable (not extractive), risks diversified, no single point of failure, value creation is genuine.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _ecosystem_health(empires: list[dict]) -> dict:
        total = len(empires)
        healthy = sum(1 for e in empires if e.get("health", 0) > 7)
        return {"total": total, "healthy": healthy, "health_rate": round(healthy / max(total, 1), 2)}
