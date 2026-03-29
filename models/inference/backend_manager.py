"""BackendManager — manages inference backends and model-to-backend routing.

Maps each model role to a specific backend + model name.
Supports fallback: if primary backend is down, try secondary.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from .inference_backend import InferenceBackend
from .ollama_backend import OllamaBackend
from .vllm_backend import VllmBackend

logger = get_logger("inference.manager")

# Default model mapping: role → (backend, model_name)
DEFAULT_MODEL_MAP = {
    "analyzer": ("ollama", "mistral"),
    "worker": ("ollama", "qwen2.5"),
    "creative": ("ollama", "llama3.1"),
    "validator": ("ollama", "mistral"),
}


class BackendManager:
    """Manages inference backends and routes model requests.

    NEVER modifies engine code or system structure.
    Only manages the inference layer.
    """

    def __init__(
        self,
        model_map: dict[str, tuple[str, str]] | None = None,
        ollama_url: str = "http://localhost:11434",
        vllm_url: str = "http://localhost:8000",
    ) -> None:
        self._backends: dict[str, InferenceBackend] = {
            "ollama": OllamaBackend(ollama_url),
            "vllm": VllmBackend(vllm_url),
        }
        self._model_map = model_map or dict(DEFAULT_MODEL_MAP)

    def generate(
        self,
        role: str,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Generate using the backend mapped to this role."""
        if role not in self._model_map:
            return {"error": True, "message": f"Unknown role: {role}"}

        backend_name, model_name = self._model_map[role]
        backend = self._backends.get(backend_name)
        if backend is None:
            return {"error": True, "message": f"Unknown backend: {backend_name}"}

        result = backend.generate(
            model_name=model_name,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Fallback: if primary failed and there's another backend, try it
        if result.get("error") and len(self._backends) > 1:
            for alt_name, alt_backend in self._backends.items():
                if alt_name != backend_name:
                    logger.info("Trying fallback backend %s for role %s", alt_name, role)
                    result = alt_backend.generate(
                        model_name=model_name,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    if not result.get("error"):
                        break

        return result

    def health_check(self) -> dict[str, Any]:
        """Check all backends."""
        return {name: backend.health_check() for name, backend in self._backends.items()}

    def set_model(self, role: str, backend: str, model_name: str) -> None:
        """Change which model/backend a role uses (runtime config only)."""
        self._model_map[role] = (backend, model_name)
        logger.info("Model mapping updated: %s -> %s/%s", role, backend, model_name)

    def get_model_map(self) -> dict[str, tuple[str, str]]:
        """Get current role → (backend, model) mapping."""
        return dict(self._model_map)
