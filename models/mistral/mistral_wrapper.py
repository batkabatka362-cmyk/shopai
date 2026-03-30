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
        self._backend = None

    def load(self) -> None:
        if self._loaded:
            return
        self.logger.info("Loading Mistral model (analyzer)...")
        try:
            from models.inference.ollama_backend import OllamaBackend
            backend = OllamaBackend()
            if backend.is_available():
                models = backend.list_models()
                if any("mistral" in m.lower() for m in models):
                    self._backend = backend
                    self.logger.info("Mistral connected via Ollama")
        except Exception:
            pass
        self._loaded = True
        self.logger.info("Mistral model ready (backend=%s)", "ollama" if self._backend else "computed")

    def execute(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._loaded:
            self.load()

        from utils.helpers import generate_id
        request_id = generate_id("req")

        # Real inference via Ollama if available
        if self._backend is not None:
            try:
                result = self._backend.generate(
                    model_name="mistral",
                    prompt=prompt,
                    system_prompt="You are a data analyst. Return structured JSON with score (0-10), decision (approve/reject), and reason.",
                    temperature=0.3,
                )
                if result.get("text"):
                    return {
                        "request_id": request_id, "model": self.model_name, "role": self.model_role,
                        "text": result["text"], "tokens_used": result.get("tokens_used", 0),
                        "backend": "ollama", "context_keys": list((context or {}).keys()),
                    }
            except Exception as exc:
                self.logger.warning("Ollama inference failed: %s", exc)

        # Fallback: SmartExecutor will fill in computed results
        return {
            "request_id": request_id, "model": self.model_name, "role": self.model_role,
            "score": 0.0, "decision": "pending", "reason": "Model inference not yet connected",
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
