"""
Orchestration Engine — Coordinate complex multi-step processes — engine chaining, parallel execution, error recovery
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class OrchestrationEngine(BaseEngine):
    engine_name = "orchestration"
    required_input_fields = ['process_data', 'dependencies']
    required_output_fields = ['execution_plan', 'coordination_map']

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
        templates = {"analyze": """Analyze process: steps, engine dependencies, data flow, parallel opportunities, failure modes, recovery strategies.\nProcess: {process_data}\nDeps: {dependencies}""", "execute": """Generate execution plan: step ordering (DAG), parallel groups, data handoff schema, error recovery per step, timeout config.\nAnalysis: {analysis}""", "enhance": """Enhance: adaptive routing, load-aware scheduling, circuit breakers.\nPlan: {execution}""", "validate": """Validate: DAG is acyclic, all data dependencies met, timeout values reasonable.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _topological_sort(deps: dict[str, list[str]]) -> list[str]:
        visited = set()
        order = []
        def visit(node):
            if node in visited: return
            visited.add(node)
            for dep in deps.get(node, []):
                visit(dep)
            order.append(node)
        for node in deps:
            visit(node)
        return order

    @staticmethod
    def _can_parallelize(step_a: dict, step_b: dict) -> bool:
        a_out = set(step_a.get("outputs", []))
        b_in = set(step_b.get("inputs", []))
        return len(a_out & b_in) == 0
