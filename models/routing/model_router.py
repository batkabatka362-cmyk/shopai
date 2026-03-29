"""ModelRouter — routes tasks to the correct model by role.

Rules:
  - analyzer → Mistral
  - worker   → Qwen
  - creative → LLaMA
  - validator → Mistral

Models do NOT communicate directly. The router is the only access point.
"""

from __future__ import annotations

import time
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

# Shared model instances (singleton per process)
_model_instances: dict[str, BaseModel] | None = None


def _get_models() -> dict[str, BaseModel]:
    global _model_instances
    if _model_instances is None:
        _model_instances = {
            "mistral": MistralWrapper(),
            "qwen": QwenWrapper(),
            "llama": LlamaWrapper(),
        }
    return _model_instances


class ModelRouter:
    """Single access point for all model interactions."""

    def __init__(self) -> None:
        self._models = _get_models()

    def get_model(self, role: str) -> BaseModel:
        model_name = ROLE_MAP.get(role)
        if model_name is None:
            raise ValueError(f"Unknown model role: {role}")
        return self._models[model_name]

    def execute(
        self,
        role: str,
        prompt: str,
        context: dict[str, Any] | None = None,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        model = self.get_model(role)
        logger.info("Routing role=%s -> model=%s", role, model.model_name)

        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            start = time.monotonic()
            try:
                result = model.execute(prompt, context)
                elapsed = time.monotonic() - start
                logger.info("Model %s responded in %.3fs", model.model_name, elapsed)

                # Guarantee dict output
                if not isinstance(result, dict):
                    result = {"raw_output": result}
                return result

            except Exception as exc:
                last_error = exc
                elapsed = time.monotonic() - start
                logger.warning(
                    "Model %s failed (attempt %d/%d, %.3fs): %s",
                    model.model_name, attempt + 1, max_retries + 1, elapsed, exc,
                )
                if attempt < max_retries:
                    time.sleep(0.1 * (attempt + 1))

        # All retries exhausted — return error dict instead of crashing
        logger.error("Model %s failed after %d attempts: %s", model.model_name, max_retries + 1, last_error)
        return {
            "error": True,
            "model": model.model_name,
            "role": role,
            "message": str(last_error),
        }

    def load_all(self) -> None:
        for model in self._models.values():
            model.load()

    def health_check(self) -> dict[str, bool]:
        """Check if all models are responsive."""
        status = {}
        for name, model in self._models.items():
            try:
                model.execute("health_check", context={})
                status[name] = True
            except Exception:
                status[name] = False
        return status
