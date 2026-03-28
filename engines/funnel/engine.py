"""
Funnel Engine — Design and optimize conversion funnels from awareness to purchase
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class FunnelEngine(BaseEngine):
    engine_name = "funnel"
    required_input_fields = ['funnel_data', 'conversion_goals']
    required_output_fields = ['funnel_design', 'optimization_plan']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze funnel stages and drop-off points", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate optimized funnel design", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with persuasion elements per stage", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate funnel metrics", required=True))
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
        templates = {"analyze": """Analyze: stage-by-stage conversion rates, drop-off points, time per stage, page performance, exit pages.\nFunnel: {funnel_data}\nGoals: {conversion_goals}""", "execute": """Generate: optimized funnel stages, recommended page layouts, CTA per stage, retargeting triggers, expected conversion rates.\nAnalysis: {analysis}""", "enhance": """Enhance: micro-commitments per stage, social proof placement, urgency triggers, trust signals.\nFunnel: {execution}""", "validate": """Validate: conversion rates between stages are realistic, no impossible jumps, retargeting logic sound.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _stage_conversion(entered: int, converted: int) -> float:
        return round(converted / max(entered, 1) * 100, 2)

    @staticmethod
    def _funnel_health(stage_rates: list[float]) -> str:
        avg = sum(stage_rates) / len(stage_rates) if stage_rates else 0
        return "healthy" if avg > 30 else "needs_work" if avg > 15 else "critical"
