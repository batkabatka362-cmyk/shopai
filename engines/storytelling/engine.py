"""
Storytelling Engine — Create compelling brand narratives — origin stories, customer journeys, product stories
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class StorytellingEngine(BaseEngine):
    engine_name = "storytelling"
    required_input_fields = ['brand_data', 'audience']
    required_output_fields = ['narrative', 'story_elements']

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
        templates = {"analyze": """Analyze storytelling opportunity:\n- Brand values and mission\n- Founder/origin story potential\n- Customer transformation stories\n- Product creation journey\n- Problem-solution narrative\n- Cultural context and relevance\n- Emotional territory to own\n\nBrand: {brand_data}\nAudience: {audience}""", "execute": """Generate narrative framework:\n- Brand origin story (hero's journey)\n- Customer journey narrative arc\n- Product story (why it exists)\n- Emotional hooks per story\n- Story formats (short/medium/long)\n- Platform adaptation (social vs long-form)\n\nAnalysis: {analysis}""", "enhance": """Enhance narratives with:\n- Vivid sensory details\n- Emotional turning points\n- Relatable conflict and resolution\n- Memorable phrases and taglines\n- Call to adventure for the customer\n\nStories: {execution}""", "validate": """Validate: narratives are authentic (not fabricated), emotionally resonant, brand-consistent.\n\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    STORY_ARCS = ["heros_journey", "rags_to_riches", "overcoming_monster", "quest", "rebirth", "transformation"]

    @staticmethod
    def _emotional_score(text: str, power_words: list[str] | None = None) -> float:
        pw = power_words or ["love", "discover", "transform", "unlock", "dream", "believe", "imagine", "create"]
        words = text.lower().split()
        hits = sum(1 for w in words if w in pw)
        return round(min(10, hits / max(len(words), 1) * 200), 2)
