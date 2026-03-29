"""
CustomerSegmentationEngine
Purpose: Segment customers into meaningful groups and build segment profiles for targeting
Input: ['customer_data', 'segmentation_criteria']
Output: ['customer_segments', 'segment_profiles']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class CustomerSegmentationEngine(BaseEngine):
    engine_name = "customer_segmentation"
    required_input_fields = ["customer_data", "segmentation_criteria"]
    required_output_fields = ["customer_segments", "segment_profiles"]

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
                "You are a customer analytics expert. Review the customer data and segmentation criteria "
                "to identify natural groupings and the most discriminating segmentation dimensions.\n\n"
                "Customer Data: {customer_data}\nSegmentation Criteria: {segmentation_criteria}\n\n"
                "Assess: data completeness per customer, most predictive behavioral and demographic dimensions, "
                "natural cluster boundaries, and potential for actionable segment differentiation. "
                "Return a segmentation approach recommendation."
            ),
            "execute": (
                "Apply the segmentation criteria to assign customers to segments and build segment profiles.\n\n"
                "Customer Data: {customer_data}\nSegmentation Criteria: {segmentation_criteria}\n\n"
                "Assign each customer to a segment and summarize each segment's characteristics. Return as JSON: "
                '{{"customer_segments": [{{"customer_id": str, "segment": str, "segment_score": float}}], '
                '"segment_profiles": [{{"segment": str, "size": int, "avg_ltv": float, "key_traits": list, "description": str}}]}}'
            ),
            "enhance": (
                "Enrich segment profiles with personas, messaging strategies, and channel recommendations.\n\n"
                "Customer Data: {customer_data}\nSegmentation Criteria: {segmentation_criteria}\n\n"
                "For each segment: create a named persona (e.g., 'The Deal Hunter'), describe their motivations, "
                "preferred channels, best offers, and what would cause them to churn. Make profiles marketing-ready."
            ),
            "validate": (
                "Validate the customer segments for separability, coverage, and actionability.\n\n"
                "Customer Data: {customer_data}\nSegmentation Criteria: {segmentation_criteria}\n\n"
                "Check: Are segments meaningfully distinct? Is every customer assigned? "
                "Are segment sizes actionable (not too small or too large)? "
                "Do segments align with the stated criteria? Flag any overlap or misassignment issues."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _calculate_segment_score(customer: dict[str, Any], segment_rules: dict[str, Any]) -> float:
        """Score how well a customer fits a given segment based on rule matching."""
        required_fields = segment_rules.get("required", {})
        preferred_fields = segment_rules.get("preferred", {})
        score = 0.0
        required_weight = 0.7 / max(len(required_fields), 1)
        preferred_weight = 0.3 / max(len(preferred_fields), 1)
        for field, expected in required_fields.items():
            if customer.get(field) == expected:
                score += required_weight
        for field, expected in preferred_fields.items():
            if customer.get(field) == expected:
                score += preferred_weight
        return round(min(score, 1.0), 4)

    @staticmethod
    def _assign_segment(customer: dict[str, Any], segment_definitions: list[dict[str, Any]]) -> str:
        """Assign a customer to the best-matching segment from a list of segment definitions."""
        best_segment = "general"
        best_score = 0.0
        for seg_def in segment_definitions:
            seg_name = seg_def.get("name", "unknown")
            rules = seg_def.get("rules", {})
            score = 0.0
            for field, condition in rules.items():
                customer_val = customer.get(field)
                if isinstance(condition, dict):
                    min_val = condition.get("min", float("-inf"))
                    max_val = condition.get("max", float("inf"))
                    if isinstance(customer_val, (int, float)) and min_val <= customer_val <= max_val:
                        score += 1.0
                elif customer_val == condition:
                    score += 1.0
            if score > best_score:
                best_score = score
                best_segment = seg_name
        return best_segment
