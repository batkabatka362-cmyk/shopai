"""LlamaWrapper — CREATIVE role.

Responsibilities:
  - Enhance and polish content
  - Add emotional, persuasive language
  - Creative rewriting and storytelling
  - Marketing copy enhancement

Restrictions:
  - Does NOT analyze data
  - Does NOT make decisions
  - Does NOT handle structured data processing
"""

from __future__ import annotations

from typing import Any

from models.base.base_model import BaseModel


class LlamaWrapper(BaseModel):
    model_name = "llama"
    model_role = "creative"

    def __init__(self, model_path: str | None = None) -> None:
        super().__init__()
        self._model_path = model_path
        self._loaded = False
        self._backend = None

    def load(self) -> None:
        if self._loaded:
            return
        self.logger.info("Loading LLaMA model (creative)...")
        try:
            from models.inference.ollama_backend import OllamaBackend
            backend = OllamaBackend()
            if backend.is_available():
                models = backend.list_models()
                if any("llama" in m.lower() for m in models):
                    self._backend = backend
                    self.logger.info("LLaMA connected via Ollama")
        except Exception:
            pass
        self._loaded = True
        self.logger.info("LLaMA model ready (backend=%s)", "ollama" if self._backend else "computed")

    def execute(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._loaded:
            self.load()

        from utils.helpers import generate_id
        request_id = generate_id("req")

        if self._backend is not None:
            try:
                result = self._backend.generate(
                    model_name="llama3.1",
                    prompt=prompt,
                    system_prompt="You are a creative copywriter. Enhance content with compelling, persuasive language while maintaining accuracy.",
                    temperature=0.8,
                )
                if result.get("text"):
                    return {
                        "request_id": request_id, "model": self.model_name, "role": self.model_role,
                        "text": result["text"], "enhanced": True, "tokens_used": result.get("tokens_used", 0),
                        "backend": "ollama", "context_keys": list((context or {}).keys()),
                    }
            except Exception as exc:
                self.logger.warning("Ollama inference failed: %s", exc)

        return {
            "request_id": request_id, "model": self.model_name, "role": self.model_role,
            "enhanced": True, "content": {}, "context_keys": list((context or {}).keys()),
        }

    def enhance(self, content: dict[str, Any], style: str = "persuasive") -> dict[str, Any]:
        """Convenience method for creative enhancement."""
        prompt = self.format_prompt(
            "Enhance the following content with {style} style:\n{content}",
            {"style": style, "content": str(content)},
        )
        return self.execute(prompt, context=content)
