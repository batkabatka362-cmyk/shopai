"""OllamaBackend — inference via local Ollama server.

Connects to Ollama API (default http://localhost:11434).
Supports Mistral, Qwen, LLaMA, and any model Ollama can run.
"""
from __future__ import annotations

import json
import time
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from utils.logger import get_logger
from .inference_backend import InferenceBackend

logger = get_logger("inference.ollama")


class OllamaBackend(InferenceBackend):
    """Ollama local inference backend."""

    backend_name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self._base_url = base_url.rstrip("/")

    def generate(
        self,
        model_name: str,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: list[str] | None = None,
    ) -> dict[str, Any]:
        """Call Ollama /api/generate endpoint."""
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt
        if stop:
            payload["options"]["stop"] = stop

        start = time.monotonic()
        try:
            data = json.dumps(payload).encode()
            req = Request(
                f"{self._base_url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())

            elapsed = time.monotonic() - start
            text = result.get("response", "")
            tokens = result.get("eval_count", len(text.split()))

            logger.info("Ollama generate: model=%s tokens=%d elapsed=%.2fs", model_name, tokens, elapsed)
            return {
                "text": text,
                "tokens_used": tokens,
                "model": model_name,
                "backend": self.backend_name,
                "elapsed_seconds": round(elapsed, 3),
            }

        except (URLError, OSError, json.JSONDecodeError) as exc:
            elapsed = time.monotonic() - start
            logger.error("Ollama generate failed: %s (%.2fs)", exc, elapsed)
            return {
                "text": "",
                "tokens_used": 0,
                "model": model_name,
                "backend": self.backend_name,
                "error": str(exc),
                "elapsed_seconds": round(elapsed, 3),
            }

    def is_available(self) -> bool:
        """Check if Ollama server is running."""
        try:
            req = Request(f"{self._base_url}/api/tags", method="GET")
            with urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except (URLError, OSError):
            return False

    def list_models(self) -> list[str]:
        """List models available in Ollama."""
        try:
            req = Request(f"{self._base_url}/api/tags", method="GET")
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return [m["name"] for m in data.get("models", [])]
        except (URLError, OSError, json.JSONDecodeError):
            return []
