"""VllmBackend — inference via vLLM server (OpenAI-compatible API).

Connects to vLLM serving endpoint (default http://localhost:8000).
vLLM provides high-throughput inference with PagedAttention.
"""
from __future__ import annotations

import json
import time
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from utils.logger import get_logger
from .inference_backend import InferenceBackend

logger = get_logger("inference.vllm")


class VllmBackend(InferenceBackend):
    """vLLM inference backend (OpenAI-compatible API)."""

    backend_name = "vllm"

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
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
        """Call vLLM /v1/completions endpoint (OpenAI-compatible)."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stop:
            payload["stop"] = stop

        start = time.monotonic()
        try:
            data = json.dumps(payload).encode()
            req = Request(
                f"{self._base_url}/v1/chat/completions",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())

            elapsed = time.monotonic() - start
            choice = result.get("choices", [{}])[0]
            text = choice.get("message", {}).get("content", "")
            usage = result.get("usage", {})
            tokens = usage.get("total_tokens", len(text.split()))

            logger.info("vLLM generate: model=%s tokens=%d elapsed=%.2fs", model_name, tokens, elapsed)
            return {
                "text": text,
                "tokens_used": tokens,
                "model": model_name,
                "backend": self.backend_name,
                "elapsed_seconds": round(elapsed, 3),
            }

        except (URLError, OSError, json.JSONDecodeError) as exc:
            elapsed = time.monotonic() - start
            logger.error("vLLM generate failed: %s (%.2fs)", exc, elapsed)
            return {
                "text": "",
                "tokens_used": 0,
                "model": model_name,
                "backend": self.backend_name,
                "error": str(exc),
                "elapsed_seconds": round(elapsed, 3),
            }

    def is_available(self) -> bool:
        """Check if vLLM server is running."""
        try:
            req = Request(f"{self._base_url}/v1/models", method="GET")
            with urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except (URLError, OSError):
            return False

    def list_models(self) -> list[str]:
        """List models available in vLLM."""
        try:
            req = Request(f"{self._base_url}/v1/models", method="GET")
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return [m["id"] for m in data.get("data", [])]
        except (URLError, OSError, json.JSONDecodeError):
            return []
