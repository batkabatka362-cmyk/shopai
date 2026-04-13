"""Anthropic Claude adapter — premium reasoning + long context.

Pick this adapter when:

  * the brain needs the highest reasoning quality available
  * the request involves nuanced decision-making, complex
    analysis, or multi-step planning
  * long-context retrieval is needed (200K window)
  * code generation with deep understanding is required

Claude does NOT speak the OpenAI chat completions schema. The
message format uses ``system`` as a top-level parameter (not a
message role), and responses use ``content`` blocks instead of
``choices[].message.content``. This adapter implements its own
``_build_request_payload`` and ``_parse_response``.

Pricing (per 1M tokens, as of 2026):
  * claude-sonnet-4-6:  $3.00 in / $15.00 out
  * claude-haiku-4-5:   $0.80 in / $4.00 out
  * claude-opus-4-6:    $15.00 in / $75.00 out

Reference: https://docs.anthropic.com/en/docs/about-claude/models
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..config import get_config
from ..errors import AdapterError, AdapterNotConfigured
from ._base import LLMBaseAdapter


_ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicAdapter(LLMBaseAdapter):
    name = "anthropic"
    model_default = "claude-sonnet-4-6"
    config_alias = "anthropic"

    capabilities = {
        Capability.CHAT_COMPLETE,
        Capability.REASON_FAST,
        Capability.REASON_DEEP,
        Capability.CODE_GENERATE,
        Capability.LONG_CONTEXT,
    }

    # High priority — best reasoning quality, but costs money.
    # Below Groq (free + fastest) for plain chat.
    priority = 85

    # Pay-per-token, no free tier
    free_tier_daily_limit = 0
    free_tier_monthly_limit = 0

    # Average cost for a typical 500-in / 300-out Sonnet call
    cost_per_call = 0.006

    # Per-token pricing (Sonnet default)
    _cost_per_1m_in = 3.00
    _cost_per_1m_out = 15.00

    base_url = "https://api.anthropic.com/v1"

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        return bool(get_config().get(self.config_alias))

    def _api_key(self) -> str:
        key = get_config().get(self.config_alias)
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env or 'ANTHROPIC_API_KEY'})",
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
        """Translate OpenAI-style messages to Anthropic's Messages
        API schema.

        Key differences from OpenAI:
          * ``system`` is a top-level string, not a message
          * role ``assistant`` stays ``assistant`` (same)
          * no ``choices`` wrapper — response is flat
        """
        system_text: str | None = None
        api_messages: list[dict[str, str]] = []

        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                system_text = (
                    f"{system_text}\n{content}"
                    if system_text
                    else content
                )
                continue
            api_messages.append({"role": role, "content": content})

        payload: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_text:
            payload["system"] = system_text
        if stop:
            payload["stop_sequences"] = (
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
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self._api_key(),
            "anthropic-version": _ANTHROPIC_API_VERSION,
            "Content-Type": "application/json",
        }
        return self._post_json(url, payload, headers=headers)

    def _parse_response(
        self,
        raw: dict[str, Any],
    ) -> tuple[str, dict[str, int], str]:
        """Parse Anthropic's Messages API response.

        Response shape::

            {
              "content": [{"type": "text", "text": "..."}],
              "model": "claude-sonnet-4-6",
              "usage": {"input_tokens": N, "output_tokens": N}
            }
        """
        text = ""
        usage: dict[str, int] = {}
        model = ""

        try:
            content_blocks = raw.get("content") or []
            text_parts = []
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            text = "".join(text_parts)

            raw_usage = raw.get("usage") or {}
            usage = {
                "prompt_tokens": int(raw_usage.get("input_tokens", 0)),
                "completion_tokens": int(raw_usage.get("output_tokens", 0)),
            }
            model = raw.get("model", "") or self.model_default
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"failed to parse Anthropic response: {exc}",
            )

        return text, usage, model

    def _estimate_call_cost(
        self,
        *,
        tokens_in: int,
        tokens_out: int,
    ) -> float:
        """Token-based cost calculation using Anthropic pricing."""
        return (
            tokens_in * self._cost_per_1m_in / 1_000_000
            + tokens_out * self._cost_per_1m_out / 1_000_000
        )
