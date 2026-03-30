"""
LearningLoopEngine
Purpose: Extract learnings from performance data and generate improvement recommendations
Input: ['performance_data', 'learning_config']
Output: ['learned_patterns', 'improvement_recommendations']
Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class LearningLoopEngine(BaseEngine):
    engine_name = "learning_loop"
    required_input_fields = ["performance_data", "learning_config"]
    required_output_fields = ["learned_patterns", "improvement_recommendations"]

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
                "You are a machine learning and performance optimization expert. "
                "Review the performance data and learning configuration to identify what worked, "
                "what failed, and where the highest-leverage improvement opportunities lie.\n\n"
                "Performance Data: {performance_data}\nLearning Config: {learning_config}\n\n"
                "Assess: performance trends, variance patterns, success/failure correlations, "
                "and which dimensions of the config are driving results. Return a structured analysis."
            ),
            "execute": (
                "Extract learned patterns and generate concrete improvement recommendations.\n\n"
                "Performance Data: {performance_data}\nLearning Config: {learning_config}\n\n"
                "Identify the top patterns in the data and map them to actionable recommendations. "
                "Return as JSON: "
                '{{"learned_patterns": [{{"pattern": str, "confidence": float, "supporting_data": list}}], '
                '"improvement_recommendations": [{{"recommendation": str, "expected_delta": float, "priority": str}}]}}'
            ),
            "enhance": (
                "Enrich the learned patterns with strategic context and implementation roadmaps.\n\n"
                "Performance Data: {performance_data}\nLearning Config: {learning_config}\n\n"
                "For each recommendation: explain the causal mechanism, estimate ROI, "
                "identify dependencies, and propose a phased implementation plan. "
                "Make the output compelling for engineering and product leadership."
            ),
            "validate": (
                "Validate the learned patterns and recommendations for statistical soundness.\n\n"
                "Performance Data: {performance_data}\nLearning Config: {learning_config}\n\n"
                "Check: Are patterns supported by sufficient data? Are confidence scores calibrated? "
                "Do recommendations follow logically from the patterns? "
                "Flag any spurious correlations or overfitted conclusions."
            ),
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    @staticmethod
    def _extract_learnings(performance_records: list[dict[str, Any]], metric_key: str = "score") -> list[dict[str, Any]]:
        """Extract top-performing configurations and their common attributes as learnings."""
        if not performance_records:
            return []
        sorted_records = sorted(performance_records, key=lambda r: float(r.get(metric_key, 0)), reverse=True)
        top_n = sorted_records[: max(1, len(sorted_records) // 4)]
        attribute_counts: dict[str, dict[Any, int]] = {}
        for record in top_n:
            for k, v in record.items():
                if k == metric_key:
                    continue
                if k not in attribute_counts:
                    attribute_counts[k] = {}
                attribute_counts[k][v] = attribute_counts[k].get(v, 0) + 1
        learnings = []
        for attr, counts in attribute_counts.items():
            best_val = max(counts, key=lambda v: counts[v])
            learnings.append({"attribute": attr, "best_value": best_val, "frequency": counts[best_val]})
        return learnings

    @staticmethod
    def _calculate_improvement_delta(baseline: float, improved: float) -> float:
        """Calculate the relative improvement delta between baseline and improved metric values."""
        if baseline == 0:
            return 0.0
        return round((improved - baseline) / abs(baseline), 4)
