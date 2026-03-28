"""
Automation Engine — Automate repetitive tasks — rule-based triggers, scheduled actions, event-driven workflows
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AutomationEngine(BaseEngine):
    engine_name = "automation"
    required_input_fields = ['task_data', 'automation_rules']
    required_output_fields = ['automation_plan', 'workflow_definitions']

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
        templates = {"analyze": """Analyze automation opportunities: repetitive tasks, time spent per task, error rates, trigger conditions, dependencies, ROI of automation.\nTasks: {task_data}\nRules: {automation_rules}""", "execute": """Generate automation plan: tasks to automate (priority ranked), trigger definitions, action sequences, error handling, monitoring.\nAnalysis: {analysis}""", "enhance": """Enhance: intelligent automation (adapt based on outcomes), self-healing workflows.\nPlan: {execution}""", "validate": """Validate: no circular triggers, error handling covers edge cases, human override available.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _automation_roi(time_saved_hours: float, hourly_cost: float, setup_cost: float) -> float:
        monthly_savings = time_saved_hours * hourly_cost * 4
        if monthly_savings == 0: return 0.0
        return round(setup_cost / monthly_savings, 1)

    @staticmethod
    def _priority_score(frequency: int, time_per_task: float, error_rate: float) -> float:
        return round(frequency * time_per_task * (1 + error_rate * 5), 2)
