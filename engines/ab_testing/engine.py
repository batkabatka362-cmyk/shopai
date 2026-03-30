"""
AbTesting Engine

Purpose: Design and analyze A/B tests with statistical rigor
Input:   ['test_config', 'variants']
Output:  ['test_plan', 'statistical_analysis']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

import math
from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AbTestingEngine(BaseEngine):
    engine_name = "ab_testing"
    required_input_fields = ['test_config', 'variants']
    required_output_fields = ['test_plan', 'statistical_analysis']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze test configuration and variant design",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate test plan and statistical framework",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance test variants with creative alternatives",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate statistical methodology and test design",
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
            "analyze": """You are a statistical testing expert. Analyze the A/B test configuration and variants.

Evaluate:
1. Hypothesis clarity and measurability
2. Sample size requirements for statistical power
3. Traffic allocation strategy
4. Test duration estimates
5. Potential confounding variables

Test config: {test_config}
Variants: {variants}

Return: test feasibility, required sample size, estimated duration, and methodology recommendations.""",
            "execute": """Based on the analysis, generate a complete test plan and statistical framework.

Analysis results: {analysis}
Test config: {test_config}
Variants: {variants}

Provide:
- test_hypothesis, primary_metric, secondary_metrics
- sample_size_per_variant, traffic_split
- test_duration_days, confidence_level
- segmentation_plan, exclusion_criteria

Return as structured JSON with test_plan and statistical_analysis objects.""",
            "enhance": """Enhance the test plan with creative variant ideas and deeper insights.

Add:
- Additional variant suggestions
- Micro-conversion tracking points
- Qualitative research supplements
- Post-test iteration roadmap

Current output: {execution}""",
            "validate": """Validate the test plan for statistical rigor and practical feasibility.

Check:
1. Sample size is sufficient for desired power (80%+)
2. Test duration accounts for weekly cycles
3. No peeking/early stopping without correction
4. Metrics are properly defined and trackable
5. Traffic split is balanced and fair

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _calculate_sample_size(baseline_rate: float, min_detectable_effect: float, alpha: float = 0.05, power: float = 0.8) -> int:
        if min_detectable_effect == 0 or baseline_rate == 0:
            return 0
        z_alpha = 1.96 if alpha == 0.05 else 2.576
        z_beta = 0.84 if power == 0.8 else 1.28
        p1 = baseline_rate
        p2 = baseline_rate * (1 + min_detectable_effect)
        numerator = (z_alpha * math.sqrt(2 * p1 * (1 - p1)) + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
        denominator = (p2 - p1) ** 2
        return math.ceil(numerator / denominator) if denominator > 0 else 0

    @staticmethod
    def _calculate_significance(control_conversions: int, control_total: int, variant_conversions: int, variant_total: int) -> dict:
        if control_total == 0 or variant_total == 0:
            return {"significant": False, "p_value": 1.0, "lift": 0.0}
        p_control = control_conversions / control_total
        p_variant = variant_conversions / variant_total
        lift = (p_variant - p_control) / p_control * 100 if p_control > 0 else 0.0
        p_pool = (control_conversions + variant_conversions) / (control_total + variant_total)
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / control_total + 1 / variant_total)) if p_pool > 0 else 1
        z_score = (p_variant - p_control) / se if se > 0 else 0
        significant = abs(z_score) > 1.96
        return {"significant": significant, "z_score": round(z_score, 4), "lift": round(lift, 2)}
