"""Gemini adapter — long context + multimodal.

Pick this adapter when:

  * the request needs a context window larger than 128K tokens
    (Gemini 2.5 Flash supports up to 1M)
  * the brain wants vision input (product image analysis)
  * Google Search grounding is desired

Gemini does NOT speak the OpenAI chat completions schema, so
this adapter implements its own ``_build_request_payload`` and
``_parse_response`` instead of inheriting from
``OpenAICompatAdapter``. The HTTP wrapper is still inherited
from ``LLMBaseAdapter._post_json``.

Free tier reference (subject to drift):
https://ai.google.dev/gemini-api/docs/rate-limits
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..config import get_config
from ..errors import AdapterError, AdapterNotConfigured
from ._base import LLMBaseAdapter


class GeminiAdapter(LLMBaseAdapter):
    name = "gemini"
    model_default = "gemini-2.5-flash"
    config_alias = "gemini"

    capabilities = {
        Capability.CHAT_COMPLETE,
        Capability.REASON_DEEP,
        Capability.LONG_CONTEXT,
        Capability.IMAGE_ANALYZE,
    }

    # Lower priority than Groq for plain chat (Groq is faster)
    # but the router prefers Gemini for LONG_CONTEXT and
    # IMAGE_ANALYZE because Groq doesn't offer them.
    priority = 75

    # Free tier as of 2026: 1500 RPD on Flash, 1000 on Flash Lite
    free_tier_daily_limit = 1_500
    free_tier_monthly_limit = 0
    cost_per_call = 0.0

    base_url = "https://generativelanguage.googleapis.com/v1beta"

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        # W963-117: per-store routing via active_store
        from .._per_store_credentials import resolve_per_store
        return bool((resolve_per_store(self.config_alias) or get_config().get(self.config_alias)))

    def _api_key(self) -> str:
        from .._per_store_credentials import resolve_per_store
        key = (resolve_per_store(self.config_alias) or get_config().get(self.config_alias))
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name, f"missing API key (set ${env or 'GEMINI_API_KEY'})",
            )
        return key

    # ── Vendor-specific request shape ──────────────────────────

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
        """Translate OpenAI-style messages to Gemini's
        ``contents`` schema.

        Gemini's API uses ``contents`` (a list of parts grouped
        by role) instead of ``messages``, and the role names are
        ``user`` / ``model`` instead of ``user`` / ``assistant``.
        """
        contents: list[dict[str, Any]] = []
        system_instruction: str | None = None

        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                # Gemini takes system prompt as a separate field
                system_instruction = (
                    f"{system_instruction}\n{content}"
                    if system_instruction
                    else content
                )
                continue
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": content}],
            })

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if stop:
            payload["generationConfig"]["stopSequences"] = (
                stop if isinstance(stop, list) else [stop]
            )
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}],
            }
        # Caller-supplied passthroughs (safety_settings, tools, ...)
        if extra:
            payload.update(extra)
        return payload

    def _call_vendor(
        self,
        payload: dict[str, Any],
        *,
        capability: Capability,
    ) -> dict[str, Any]:
        model = self.model_default
        # Allow per-call model override via the payload (set by
        # _chat in the base class via _build_request_payload)
        if "_model" in payload:
            model = payload.pop("_model")
        url = (
            f"{self.base_url}/models/{model}:generateContent"
            f"?key={self._api_key()}"
        )
        return self._post_json(
            url,
            payload,
            headers={"Content-Type": "application/json"},
        )

    def _parse_response(
        self,
        raw: dict[str, Any],
    ) -> tuple[str, dict[str, int], str]:
        """Translate Gemini's ``candidates[].content.parts[].text``
        to the ``(text, usage, model)`` tuple the base expects."""
        text = ""
        usage: dict[str, int] = {}
        model = ""

        try:
            candidates = raw.get("candidates") or []
            if candidates:
                first = candidates[0] or {}
                content = first.get("content") or {}
                parts = content.get("parts") or []
                if parts:
                    text = "".join(
                        str(p.get("text", "")) for p in parts
                        if isinstance(p, dict)
                    )
            usage_meta = raw.get("usageMetadata") or {}
            usage = {
                "prompt_tokens": int(usage_meta.get("promptTokenCount", 0)),
                "completion_tokens": int(usage_meta.get("candidatesTokenCount", 0)),
                "total_tokens": int(usage_meta.get("totalTokenCount", 0)),
            }
            model = raw.get("modelVersion", "") or self.model_default
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name, f"failed to parse Gemini response: {exc}",
            )

        return text, usage, model
