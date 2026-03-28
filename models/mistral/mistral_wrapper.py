"""MistralWrapper — ANALYZER role.

Responsibilities:
  - Analyze structured input
  - Evaluate products / data
  - Produce decisions with score + reason
  - Validate final outputs

Required output format:
  { "score": float, "decision": "approve"|"reject", "reason": str }

Restrictions:
  - Does NOT generate final content
  - Does NOT perform execution
  - Does NOT handle creative writing
"""

from __future__ import annotations

from typing import Any

from models.base.base_model import BaseModel


class MistralWrapper(BaseModel):
    model_name = "mistral"
    model_role = "analyzer"

    def __init__(self, model_path: str | None = None) -> None:
        super().__init__()
        self._model_path = model_path
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self.logger.info("Loading Mistral model (analyzer)...")
        # Model loading will be implemented when local inference is set up
        self._loaded = True
        self.logger.info("Mistral model ready")

    def execute(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._loaded:
            self.load()

        self.logger.info("Mistral analyzing (prompt_len=%d)", len(prompt))

        # Placeholder: returns structured analysis output
        # Will be replaced with actual model inference
        return {
            "score": 0.0,
            "decision": "pending",
            "reason": "Model inference not yet connected",
            "raw_prompt": prompt,
            "context_keys": list((context or {}).keys()),
        }

    def analyze(self, data: dict[str, Any], task: str = "evaluate") -> dict[str, Any]:
        """Convenience method for analysis tasks."""
        prompt = self.format_prompt(
            "Task: {task}\nData: {data}\nProvide score (0-10), decision (approve/reject), and reason.",
            {"task": task, "data": str(data)},
        )
        return self.execute(prompt, context=data)

    def validate(self, output: dict[str, Any], criteria: str = "quality") -> dict[str, Any]:
        """Convenience method for validation tasks."""
        prompt = self.format_prompt(
            "Validate output against criteria: {criteria}\nOutput: {output}\nProvide score, decision, reason.",
            {"criteria": criteria, "output": str(output)},
        )
        return self.execute(prompt, context=output)
