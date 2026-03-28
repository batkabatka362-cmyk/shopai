"""
AutonomousLearning Engine — Self-learning system — continuously learns from outcomes, updates knowledge, and improves decision quality
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class AutonomousLearningEngine(BaseEngine):
    engine_name = "autonomous_learning"
    required_input_fields = ['outcome_data', 'learning_config']
    required_output_fields = ['learned_patterns', 'model_updates']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Analyze outcomes for learning opportunities", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Extract and store learned patterns", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Enhance with cross-domain learning", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Validate learning quality", required=True))
        self.flow.register_executor("validate", self._step_validate)

    def _step_analyze(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("analyze", data)
        r = self._model_router.execute("analyzer", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"analysis": r})

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("execute", data)
        r = self._model_router.execute("worker", prompt, context=data)
        return StepResult(step_name=step_name, model_used="qwen", status=EngineStatus.COMPLETED, output={"execution": r})

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("enhance", data)
        r = self._model_router.execute("creative", prompt, context=data)
        return StepResult(step_name=step_name, model_used="llama", status=EngineStatus.COMPLETED, output={"enhanced": r})

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("validate", data)
        r = self._model_router.execute("validator", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"validation": r})

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        templates = {"analyze": """Analyze outcomes for learning:\n- What decisions were made?\n- What outcomes resulted?\n- Which predictions were accurate/inaccurate?\n- What patterns emerge across decisions?\n- What knowledge gaps caused failures?\n- Feedback loop completeness?\n\nOutcomes: {outcome_data}\nConfig: {learning_config}""", "execute": """Extract learnings:\n- New rules: if X then Y (with confidence)\n- Updated weights: which factors matter more than thought\n- Failure patterns: common failure modes\n- Success patterns: what consistently works\n- Knowledge base updates\n- Model fine-tuning recommendations\n\nAnalysis: {analysis}""", "enhance": """Enhance: cross-domain pattern transfer, meta-learning (learning how to learn faster), anticipatory learning.\n\nPatterns: {execution}""", "validate": """Validate: learnings are statistically significant (not noise), no overfitting to recent events, knowledge base consistent.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _learning_rate(correct: int, total: int) -> float:
        return round(correct / max(total, 1), 4)

    @staticmethod
    def _should_update_model(accuracy_delta: float, sample_size: int, min_samples: int = 100) -> bool:
        return sample_size >= min_samples and abs(accuracy_delta) > 0.02

    @staticmethod
    def _decay_old_learnings(confidence: float, age_days: int, half_life: int = 30) -> float:
        import math
        return round(confidence * math.exp(-0.693 * age_days / half_life), 4)
