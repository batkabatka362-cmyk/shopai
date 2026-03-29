"""
ErpIntegration Engine — Erp Integration
Flow: Analyzer(Mistral) → Worker(Qwen) → Creative(LLaMA) → Validator(Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ErpIntegrationEngine(BaseEngine):
    engine_name = "erp_integration"
    required_input_fields = ['erp_config', 'data_mapping']
    required_output_fields = ['integration_setup', 'sync_schedule']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        for step, role, req in [("analyze","analyzer",True),("execute","worker",True),("enhance","creative",False),("validate","validator",True)]:
            self.flow.add_step(EngineStep(name=step, model_role=role, description=f"{step} erp integration", required=req, stop_on_reject=req))
            self.flow.register_executor(step, getattr(self, f"_step_{step}"))

    def _run_step(self, step_name: str, role: str, model: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt(step_name, data)
        result = self._model_router.execute(role, prompt, context=data)
        return StepResult(step_name=step_name, model_used=model, status=EngineStatus.COMPLETED, output={step_name: result})

    def _step_analyze(self, step_name: str, data: dict[str, Any]) -> StepResult:
        return self._run_step(step_name, "analyzer", "mistral", data)

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        return self._run_step(step_name, "worker", "qwen", data)

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        return self._run_step(step_name, "creative", "llama", data)

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        return self._run_step(step_name, "validator", "mistral", data)

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        return f"{step.upper()} erp integration: {data}"
