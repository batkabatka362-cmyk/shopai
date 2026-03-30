"""InferenceBackend — abstract interface for model inference providers.

All backends implement the same interface. The system never depends on
a specific provider — backends are swappable without code changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class InferenceBackend(ABC):
    """Abstract base for inference backends (ollama, vllm, etc.)."""

    backend_name: str = "base"

    @abstractmethod
    def generate(
        self,
        model_name: str,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate a completion. Returns {text, tokens_used, model, backend}."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the backend is reachable and ready."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """List available models on this backend."""

    def health_check(self) -> dict[str, Any]:
        """Check backend health."""
        available = self.is_available()
        models = self.list_models() if available else []
        return {
            "backend": self.backend_name,
            "available": available,
            "models": models,
        }
