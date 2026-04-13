"""OpenAI GPT-4o adapter — cloud LLM fallback.

Pick this adapter when:

  * Ollama is down or too slow for the request
  * the brain needs state-of-the-art reasoning quality
  * multimodal (image + text) input is required
  * function / tool calling with strict schema adherence

GPT-4o is the default model — best price-to-performance ratio
across the OpenAI lineup. The adapter also supports ``gpt-4o-mini``
for cheaper high-throughput work and ``o3-mini`` for deep
reasoning tasks.

Pricing (per 1M tokens, as of 2026):
  * gpt-4o:        $2.50 in / $10.00 out
  * gpt-4o-mini:   $0.15 in / $0.60 out
  * o3-mini:       $1.10 in / $4.40 out

Reference: https://platform.openai.com/docs/models
"""
from __future__ import annotations

from ..base import Capability
from ._openai_compat import OpenAICompatAdapter


class OpenAIAdapter(OpenAICompatAdapter):
    name = "openai"
    base_url = "https://api.openai.com/v1"
    config_alias = "openai"
    model_default = "gpt-4o"

    capabilities = {
        Capability.CHAT_COMPLETE,
        Capability.REASON_FAST,
        Capability.REASON_DEEP,
        Capability.CODE_GENERATE,
        Capability.IMAGE_ANALYZE,
    }

    # Mid-high priority — preferred over Ollama/OpenRouter but
    # below Groq (which is free and faster for plain chat).
    priority = 80

    # Pay-per-token, no free tier
    free_tier_daily_limit = 0
    free_tier_monthly_limit = 0

    # Average cost for a typical 500-in / 300-out call
    cost_per_call = 0.0043

    # Per-token pricing for accurate cost tracking
    _cost_per_1m_in = 2.50
    _cost_per_1m_out = 10.00

    def _estimate_call_cost(
        self,
        *,
        tokens_in: int,
        tokens_out: int,
    ) -> float:
        """Token-based cost calculation using OpenAI pricing."""
        return (
            tokens_in * self._cost_per_1m_in / 1_000_000
            + tokens_out * self._cost_per_1m_out / 1_000_000
        )
