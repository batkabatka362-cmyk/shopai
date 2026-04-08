"""Ollama adapter — local self-hosted LLM, PII-safe.

Why Ollama is the sovereignty fallback:

  * **$0 cost** — runs on the operator's hardware
  * **No rate limit** — only constraint is GPU memory
  * **PII-safe** — data never leaves the host (no third-party
    transit), so the router picks Ollama when
    ``RouteContext(contains_pii=True)`` is set
  * **Same model family as Groq** — Llama 3.3 8B/70B, Qwen 2.5,
    DeepSeek-Coder all available locally so prompts swap
    cleanly between cloud and local

Configuration:

  * ``OLLAMA_BASE_URL`` env var (default ``http://localhost:11434``)
  * No API key needed
  * The adapter is "configured" iff the URL is set; the actual
    model availability is checked by ``health_check()``

Notes:

  * Ollama's ``/api/chat`` endpoint speaks an OpenAI-ish schema
    but with subtle differences (``message`` not ``messages`` in
    streaming, ``done`` flag, ``total_duration`` instead of
    ``usage``). We translate explicitly.
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterCategory, Capability
from ..config import get_config
from ..errors import AdapterError, AdapterUnavailable
from ._base import LLMBaseAdapter


_DEFAULT_OLLAMA_URL = "http://localhost:11434"


class OllamaAdapter(LLMBaseAdapter):
    name = "ollama_local"
    category = AdapterCategory.LLM
    model_default = "llama3.3:8b"

    capabilities = {
        Capability.CHAT_COMPLETE,
        Capability.REASON_FAST,
        Capability.REASON_DEEP,
        Capability.CODE_GENERATE,
    }

    # Default priority is lower than Groq (cloud LLMs are
    # faster on a typical operator's hardware) but the
    # ``is_pii_safe`` override below makes the router pick
    # Ollama first whenever the request carries PII.
    priority = 60
    cost_per_call = 0.0
    free_tier_daily_limit = 0  # unlimited (local)
    timeout = 120.0  # local inference can be slow on CPU-only

    def base_url(self) -> str:
        return get_config().get("ollama_url", _DEFAULT_OLLAMA_URL) or _DEFAULT_OLLAMA_URL

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        # Local adapter is "configured" if the URL is set —
        # health_check does the actual reachability test.
        return bool(self.base_url())

    def is_pii_safe(self) -> bool:
        """Local inference: data never leaves the host. Router
        picks this adapter first for PII-bearing requests."""
        return True

    # ── Vendor schema ──────────────────────────────────────────

    def _build_request_payload(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float,
        stop: Any,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        """Ollama's chat endpoint accepts ``model``, ``messages``,
        and ``options``. ``stream`` defaults to True so we
        explicitly disable it for the single-shot case."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if stop:
            payload["options"]["stop"] = (
                stop if isinstance(stop, list) else [stop]
            )
        if extra:
            payload.update(extra)
        return payload

    def _call_vendor(
        self,
        payload: dict[str, Any],
        *,
        capability: Capability,
    ) -> dict[str, Any]:
        url = f"{self.base_url().rstrip('/')}/api/chat"
        return self._post_json(
            url,
            payload,
            headers={"Content-Type": "application/json"},
        )

    def _parse_response(
        self,
        raw: dict[str, Any],
    ) -> tuple[str, dict[str, int], str]:
        """Ollama returns ``{"message": {"role", "content"}, ...}``
        plus ``prompt_eval_count`` / ``eval_count`` for tokens."""
        try:
            message = raw.get("message") or {}
            text = str(message.get("content", "") or "")
            usage = {
                "prompt_tokens": int(raw.get("prompt_eval_count", 0) or 0),
                "completion_tokens": int(raw.get("eval_count", 0) or 0),
                "total_tokens": (
                    int(raw.get("prompt_eval_count", 0) or 0)
                    + int(raw.get("eval_count", 0) or 0)
                ),
            }
            model = str(raw.get("model", "") or self.model_default)
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name, f"failed to parse Ollama response: {exc}",
            )

        return text, usage, model

    def health_check(self) -> bool:
        """Ping Ollama's ``/api/tags`` endpoint to confirm the
        local server is reachable. Returns False on any error
        (network, timeout, missing requests library) so the
        router can short-circuit Ollama-routed requests when
        the local server is down."""
        if not super().is_configured():
            return False
        try:
            from . import _base as _base_module
            if not _base_module._REQUESTS_AVAILABLE:
                return False
            response = _base_module._requests.get(
                f"{self.base_url().rstrip('/')}/api/tags",
                timeout=2.0,
            )
            return response.status_code == 200
        except Exception:  # noqa: BLE001
            return False
