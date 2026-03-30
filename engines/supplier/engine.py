"""
Supplier Engine

Purpose: Evaluate, score, and select suppliers based on reliability, cost, quality, and speed
Input:   ['supplier_data', 'requirements']
Output:  ['supplier_rankings', 'recommendations']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class SupplierEngine(BaseEngine):
    engine_name = "supplier"
    required_input_fields = ['supplier_data', 'requirements']
    required_output_fields = ['supplier_rankings', 'recommendations']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze input and assess viability",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate structured domain output",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance output with creative insights",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate output quality and consistency",
            required=True,
        ))
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
        templates = {
            "analyze": """Evaluate suppliers against requirements.

Score each supplier on: price competitiveness, product quality, delivery reliability, shipping speed, communication responsiveness, MOQ flexibility, returns policy.

Flag red flags: slow response (>48h), high defect rate (>5%), unreliable delivery (<85% on-time).

Suppliers: {supplier_data}
Requirements: {requirements}""",
            "execute": """Rank suppliers and generate selection recommendations.

- Weighted scores per criterion
- Overall ranking
- Primary/backup supplier recommendations
- Negotiation points per supplier
- Risk assessment

Analysis: {analysis}""",
            "enhance": """Add strategic supplier management recommendations:
- Diversification strategy (don't rely on single supplier)
- Long-term relationship building tactics
- Volume discount negotiation angles

Rankings: {execution}""",
            "validate": """Validate: scores in range, no missing criteria, rankings consistent with scores, red flags properly surfaced.

Output: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    SUPPLIER_CRITERIA = ["price", "quality", "reliability", "speed", "communication", "moq", "returns_policy"]

    DEFAULT_WEIGHTS = {
        "price": 0.25, "quality": 0.20, "reliability": 0.20,
        "speed": 0.15, "communication": 0.10, "moq": 0.05, "returns_policy": 0.05,
    }

    @classmethod
    def _score_supplier(cls, supplier: dict, weights: dict | None = None) -> float:
        w = weights or cls.DEFAULT_WEIGHTS
        total = sum(float(supplier.get(c, 0)) * w.get(c, 0) for c in cls.SUPPLIER_CRITERIA)
        return round(total, 2)

    @staticmethod
    def _check_red_flags(supplier: dict) -> list[str]:
        flags = []
        if float(supplier.get("avg_response_hours", 0)) > 48:
            flags.append("slow_response")
        if float(supplier.get("defect_rate", 0)) > 0.05:
            flags.append("high_defect_rate")
        if float(supplier.get("on_time_rate", 1)) < 0.85:
            flags.append("unreliable_delivery")
        return flags

