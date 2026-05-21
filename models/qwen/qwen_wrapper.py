"""QwenWrapper — WORKER role.

Responsibilities:
  - Execute tasks
  - Generate structured outputs
  - Rewrite and format content
  - Handle bulk operations

Restrictions:
  - Does NOT analyze deeply
  - Does NOT make decisions
  - Does NOT create emotional marketing
"""

from __future__ import annotations

from typing import Any

from models.base.base_model import BaseModel


class QwenWrapper(BaseModel):
    model_name = "qwen"
    model_role = "worker"

    def __init__(self, model_path: str | None = None) -> None:
        super().__init__()
        self._model_path = model_path
        self._loaded = False
        self._backend = None

    def load(self) -> None:
        if self._loaded:
            return
        self.logger.info("Loading Qwen model (worker)...")
        try:
            from models.inference.ollama_backend import OllamaBackend
            backend = OllamaBackend()
            if backend.is_available():
                models = backend.list_models()
                if any("qwen" in m.lower() for m in models):
                    self._backend = backend
                    self.logger.info("Qwen connected via Ollama")
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(
                "Qwen Ollama backend init failed (will run "
                "computed-mode): %s", exc,
            )
        self._loaded = True
        self.logger.info("Qwen model ready (backend=%s)", "ollama" if self._backend else "computed")

    def execute(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._loaded:
            self.load()

        from utils.helpers import generate_id
        request_id = generate_id("req")

        if self._backend is not None:
            try:
                result = self._backend.generate(
                    model_name="qwen2.5",
                    prompt=prompt,
                    system_prompt="You are a task execution specialist. Generate structured JSON output with actionable results.",
                    temperature=0.5,
                )
                if result.get("text"):
                    return {
                        "request_id": request_id, "model": self.model_name, "role": self.model_role,
                        "text": result["text"], "generated": True, "tokens_used": result.get("tokens_used", 0),
                        "backend": "ollama", "context_keys": list((context or {}).keys()),
                    }
            except Exception as exc:
                self.logger.warning("Ollama inference failed: %s", exc)

        return {
            "request_id": request_id, "model": self.model_name, "role": self.model_role,
            "generated": True, "content": {}, "context_keys": list((context or {}).keys()),
        }

    def generate(self, data: dict[str, Any], output_format: str = "structured") -> dict[str, Any]:
        """Convenience method for content generation tasks."""
        prompt = self.format_prompt(
            "Generate {output_format} output from data:\n{data}",
            {"output_format": output_format, "data": str(data)},
        )
        return self.execute(prompt, context=data)
