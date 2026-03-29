"""
ConversionTrackingEngine
Purpose: Analyze conversion funnels, calculate rates, and identify drop-off points
Input: ['funnel_data', 'conversion_goals']
Output: ['conversion_rates', 'funnel_analysis']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ConversionTrackingEngine(BaseEngine):
    engine_name = "conversion_tracking"
    required_input_fields = ["funnel_data", "conversion_goals"]
    required_output_fields = ["conversion_rates", "funnel_analysis"]

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze input", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate output", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance output", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate output", required=True))
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
            "analyze": (
                "You are a conversion rate optimization expert. Examine the funnel data and conversion goals "
                "to identify where users are dropping off and what the biggest opportunities for improvement are.\n\n"
                "Funnel Data: {funnel_data}\nConversion Goals: {conversion_goals}\n\n"
                "Assess: funnel stage completion rates, major drop-off points, goal alignment, "
                "and statistical significance of observed patterns. Return a structured funnel assessment."
            ),
            "execute": (
                "Calculate conversion rates and produce a detailed funnel analysis.\n\n"
                "Funnel Data: {funnel_data}\nConversion Goals: {conversion_goals}\n\n"
                "Compute: step-by-step conversion rates, overall funnel conversion, "
                "and identify the top 3 drop-off points. Return as JSON: "
                '{{"conversion_rates": {{"overall": float, "by_step": dict}}, '
                '"funnel_analysis": {{"stages": list, "drop_off_points": list, "bottleneck": str}}}}'
            ),
            "enhance": (
                "Enrich the funnel analysis with actionable optimization recommendations.\n\n"
                "Funnel Data: {funnel_data}\nConversion Goals: {conversion_goals}\n\n"
                "Provide: specific CRO recommendations for each drop-off point, "
                "estimated impact of fixes, A/B test ideas, and quick wins vs. long-term improvements."
            ),
            "validate": (
                "Validate the conversion rate calculations and funnel analysis for accuracy.\n\n"
                "Funnel Data: {funnel_data}\nConversion Goals: {conversion_goals}\n\n"
                "Check: Are conversion rates mathematically correct? Is the funnel ordered logically? "
                "Do the goals map to the correct funnel stages? Flag any data inconsistencies."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_conversion_rate(entered: int, converted: int) -> float:
        """Calculate the conversion rate between two funnel stages."""
        if entered <= 0:
            return 0.0
        return round(converted / entered, 4)

    @staticmethod
    def _identify_drop_off_points(stages: list[dict[str, Any]], threshold: float = 0.3) -> list[dict[str, Any]]:
        """Identify funnel stages where drop-off exceeds the given threshold."""
        drop_offs = []
        for i in range(1, len(stages)):
            prev_count = stages[i - 1].get("count", 0)
            curr_count = stages[i].get("count", 0)
            if prev_count > 0:
                drop_rate = 1.0 - (curr_count / prev_count)
                if drop_rate >= threshold:
                    drop_offs.append({
                        "from_stage": stages[i - 1].get("name"),
                        "to_stage": stages[i].get("name"),
                        "drop_rate": round(drop_rate, 4),
                        "lost_users": prev_count - curr_count,
                    })
        return sorted(drop_offs, key=lambda x: x["drop_rate"], reverse=True)
