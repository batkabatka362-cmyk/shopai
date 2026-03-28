"""ModelRouter — routes tasks to the correct model by role.

Rules:
  - analyzer → Mistral
  - worker   → Qwen
  - creative → LLaMA
  - validator → Mistral

Models do NOT communicate directly. The router is the only access point.
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from models.base.base_model import BaseModel
from models.mistral.mistral_wrapper import MistralWrapper
from models.qwen.qwen_wrapper import QwenWrapper
from models.llama.llama_wrapper import LlamaWrapper

logger = get_logger("model.router")

ROLE_MAP: dict[str, str] = {
    "analyzer": "mistral",
    "worker": "qwen",
    "creative": "llama",
    "validator": "mistral",
}


class ModelRouter:
    """Single access point for all model interactions."""

    def __init__(self) -> None:
        self._models: dict[str, BaseModel] = {
            "mistral": MistralWrapper(),
            "qwen": QwenWrapper(),
            "llama": LlamaWrapper(),
        }

    def get_model(self, role: str) -> BaseModel:
        model_name = ROLE_MAP.get(role)
        if model_name is None:
            raise ValueError(f"Unknown model role: {role}")
        return self._models[model_name]

    def execute(self, role: str, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        model = self.get_model(role)
        logger.info("Routing role=%s -> model=%s", role, model.model_name)
        return model.execute(prompt, context)

    def load_all(self) -> None:
        for model in self._models.values():
            model.load()
