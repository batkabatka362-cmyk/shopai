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

    def load(self) -> None:
        if self._loaded:
            return
        self.logger.info("Loading LLaMA model (creative)...")
        self._loaded = True
        self.logger.info("LLaMA model ready")

    def execute(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._loaded:
            self.load()

        self.logger.info("LLaMA creating (prompt_len=%d)", len(prompt))

        return {
            "enhanced": True,
            "content": {},
            "raw_prompt": prompt,
            "context_keys": list((context or {}).keys()),
        }

    def enhance(self, content: dict[str, Any], style: str = "persuasive") -> dict[str, Any]:
        """Convenience method for creative enhancement."""
        prompt = self.format_prompt(
            "Enhance the following content with {style} style:\n{content}",
            {"style": style, "content": str(content)},
        )
        return self.execute(prompt, context=content)
