"""AnthropicAdapter -- Claude Messages API.

ShopAI's api-status recommended Anthropic Claude as the
"premium LLM" tier. Pre-fix no adapter existed; an operator
setting ANTHROPIC_API_KEY would see "brain ready" but the
router had no path to route through.

W963-105 closes the gap with a proper Messages API
adapter (NOT OpenAI-compat -- Anthropic uses its own
``/v1/messages`` schema with a separate ``system`` field
and a ``content: [{type, text}]`` response shape).

Why ship Anthropic alongside the existing OpenAI-compat
fleet (Groq, OpenAI, etc.):
  * Best-in-class reasoning for the action_critic /
    strategist_advisor consultant paths -- Claude's
    refusal-resistance + multi-step reasoning produce
    sharper adversarial critiques than gpt-4o-mini.
  * Operator-side: many ShopAI users already have
    Anthropic billing relationships.
  * Long-context handling -- Claude's 200K+ context fits
    multi-engine output bundles for fleet-wide brief
    refinements.

Auth: x-api-key header (NOT Bearer). Requires the
``anthropic-version`` header pinned to a known release
(2023-06-01 is stable through current Claude releases).

Models (Dec 2024):
  claude-sonnet-4-5         -- premium balanced
  claude-opus-4-7           -- premium reasoning
  claude-haiku-4-5-20251001 -- fast/cheap
  claude-sonnet-3-5-20240620 -- legacy fallback

Default to claude-sonnet-4-5 -- balanced cost vs
intelligence for the consultant overlay's strategic
refinements. Operators can override per-call via
params["model"] for opus-grade reasoning.

Endpoint: POST https://api.anthropic.com/v1/messages
Docs: https://docs.anthropic.com/en/api/messages
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..config import get_config
from ..errors import (
    AdapterError,
    AdapterNotConfigured,
)
from ._base import LLMBaseAdapter


_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicAdapter(LLMBaseAdapter):
    """Anthropic Claude adapter (Messages API)."""

    name = "anthropic"
    base_url = "https://api.anthropic.com/v1"
    config_alias = "anthropic"
    # Sonnet 4.5: balanced cost/intelligence default.
    # Operator overrides via params["model"] for premium
    # reasoning (e.g. "claude-opus-4-7") or fast/cheap
    # ("claude-haiku-4-5-20251001").
    model_default = "claude-sonnet-4-5"

    capabilities = {
        Capability.CHAT_COMPLETE,
        Capability.REASON_FAST,
        Capability.REASON_DEEP,
        Capability.CODE_GENERATE,
        Capability.LONG_CONTEXT,
    }

    # Priority 78 -- above Resend-tier alternatives but
    # below Groq (90) and OpenAI (80) for chat default.
    # Anthropic shines specifically on REASON_DEEP, where
    # the router's capability ranking picks it ahead of
    # Groq for adversarial/critical paths.
    priority = 78

    # Anthropic has no unconditional free tier (similar to
    # OpenAI). Quotas at 0 to signal paid usage.
    free_tier_daily_limit = 0
    free_tier_monthly_limit = 0
    # Average cost across Sonnet calls; Opus is ~5x more.
    cost_per_call = 0.015

    # ── Configuration ─────────────────────────────────────

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
                self.name,
                f"missing API key (set ${env or 'ANTHROPIC_API_KEY'})",
            )
        return key

    # ── Vendor-specific request shape ─────────────────────

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
        """Translate OpenAI-style messages to Anthropic's
        Messages schema.

        Two structural differences:
          1. Anthropic takes ``system`` as a TOP-LEVEL field
             (not as messages[0] with role='system'). Strip
             any system messages out + concatenate them.
          2. ``max_tokens`` is REQUIRED in Anthropic
             (OpenAI defaults silently); we always set it.
          3. ``stop_sequences`` instead of OpenAI's ``stop``.
        """
        anthropic_messages: list[dict[str, str]] = []
        system_parts: list[str] = []

        for m in messages:
            role = str(m.get("role", "user"))
            content = str(m.get("content", ""))
            if role == "system":
                if content:
                    system_parts.append(content)
                continue
            # Anthropic uses 'user'/'assistant' (same as OpenAI)
            anthropic_messages.append({
                "role": role,
                "content": content,
            })

        payload: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
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
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        return self._post_json(url, payload, headers=headers)

    def _parse_response(
        self,
        raw: dict[str, Any],
    ) -> tuple[str, dict[str, int], str]:
        """Translate Anthropic's content/usage shape to the
        ``(text, usage, model)`` tuple the base expects.

        Anthropic returns:
            {
              "content": [{"type": "text", "text": "..."}, ...],
              "model":   "claude-sonnet-4-5",
              "usage":   {"input_tokens": N, "output_tokens": N}
            }

        Concatenates every text part (multi-part responses
        happen with tool use or thinking blocks). Maps
        input_tokens -> prompt_tokens, output_tokens ->
        completion_tokens to match OpenAI naming the base
        layer expects.
        """
        try:
            content = raw.get("content") or []
            text_parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text_parts.append(str(part.get("text", "")))
            text = "".join(text_parts)

            usage_raw = raw.get("usage") or {}
            usage: dict[str, int] = {
                "prompt_tokens": int(
                    usage_raw.get("input_tokens", 0) or 0,
                ),
                "completion_tokens": int(
                    usage_raw.get("output_tokens", 0) or 0,
                ),
            }
            usage["total_tokens"] = (
                usage["prompt_tokens"]
                + usage["completion_tokens"]
            )
            model = str(raw.get("model", "") or self.model_default)
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"failed to parse Anthropic response: {exc}",
            )

        return text, usage, model
