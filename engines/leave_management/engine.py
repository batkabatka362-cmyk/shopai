"""
LeaveManagement Engine
Flow: Analyzer(Mistral) → Worker(Qwen) → Creative(LLaMA) → Validator(Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class LeaveManagementEngine(BaseEngine):
    engine_name = "leave_management"
    required_input_fields = ['leave_data', 'policy_config']
    required_output_fields = ['leave_balance', 'approval_status']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        for step, role, req in [("analyze","analyzer",True),("execute","worker",True),("enhance","creative",False),("validate","validator",True)]:
            self.flow.add_step(EngineStep(name=step, model_role=role, description=f"{step} leave management", required=req, stop_on_reject=req))
            self.flow.register_executor(step, getattr(self, f"_step_{step}"))

    def _run_step(self, step_name: str, role: str, model: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt(step_name, data)
        result = self._model_router.execute(role, prompt, context=data)
        return StepResult(step_name=step_name, model_used=model, status=EngineStatus.COMPLETED, output={step_name: result})

    def _step_analyze(self, sn: str, d: dict[str, Any]) -> StepResult: return self._run_step(sn, "analyzer", "mistral", d)
    def _step_execute(self, sn: str, d: dict[str, Any]) -> StepResult: return self._run_step(sn, "worker", "qwen", d)
    def _step_enhance(self, sn: str, d: dict[str, Any]) -> StepResult: return self._run_step(sn, "creative", "llama", d)
    def _step_validate(self, sn: str, d: dict[str, Any]) -> StepResult: return self._run_step(sn, "validator", "mistral", d)

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        return f"{step.upper()} leave management: {data}"
