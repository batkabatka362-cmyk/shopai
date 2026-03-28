"""
Media Engine

Purpose: Manage and optimize media assets
Input:   ['media_assets', 'optimization_goals']
Output:  ['optimized_assets', 'performance_metrics']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class MediaEngine(BaseEngine):
    engine_name = "media"
    required_input_fields = ['media_assets', 'optimization_goals']
    required_output_fields = ['optimized_assets', 'performance_metrics']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        # Step 1: Analyze (Mistral)
        self.flow.add_step(EngineStep(
            name="analyze",
            model_role="analyzer",
            description="Analyze input data and decide whether to proceed",
            required=True,
            stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        # Step 2: Execute (Qwen)
        self.flow.add_step(EngineStep(
            name="execute",
            model_role="worker",
            description="Generate structured output based on analysis",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        # Step 3: Enhance (LLaMA)
        self.flow.add_step(EngineStep(
            name="enhance",
            model_role="creative",
            description="Enhance and polish the output",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        # Step 4: Validate (Mistral)
        self.flow.add_step(EngineStep(
            name="validate",
            model_role="validator",
            description="Validate final output quality",
            required=True,
        ))
        self.flow.register_executor("validate", self._step_validate)

    def _step_analyze(self, step_name: str, data: dict[str, Any]) -> StepResult:
        result = self._model_router.execute(
            "analyzer",
            f"Analyze for media: " + str(data),
            context=data,
        )
        return StepResult(
            step_name=step_name,
            model_used="mistral",
            status=EngineStatus.COMPLETED,
            output={"analysis": result},
        )

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        result = self._model_router.execute(
            "worker",
            f"Execute media task: " + str(data),
            context=data,
        )
        return StepResult(
            step_name=step_name,
            model_used="qwen",
            status=EngineStatus.COMPLETED,
            output={"execution": result},
        )

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        result = self._model_router.execute(
            "creative",
            f"Enhance media output: " + str(data),
            context=data,
        )
        return StepResult(
            step_name=step_name,
            model_used="llama",
            status=EngineStatus.COMPLETED,
            output={"enhanced": result},
        )

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        result = self._model_router.execute(
            "validator",
            f"Validate media output quality: " + str(data),
            context=data,
        )
        return StepResult(
            step_name=step_name,
            model_used="mistral",
            status=EngineStatus.COMPLETED,
            output={"validation": result},
        )
