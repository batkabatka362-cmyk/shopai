"""OpenRouter adapter — universal fallback router.

OpenRouter exposes 100+ models (Anthropic, Google, Meta, Mistral,
Qwen, DeepSeek, ...) behind one OpenAI-compatible endpoint with
a small subset available on a free tier (``:free`` model
suffix). The adapter sits at the bottom of the fallback chain:
when every preferred adapter is down or rate-limited, the
router still has SOMETHING to call.

Why low priority:

  * The free models on OpenRouter rotate; we cannot rely on a
    specific model being available on any given day.
  * Latency is higher than Groq / Cerebras (proxied request).

Why we still keep it:

  * Single API key gives us access to 100+ vendors as a
    last-resort fallback.
  * Useful for one-off experiments without wiring a new adapter.
"""
from __future__ import annotations

from ..base import Capability
from ._openai_compat import OpenAICompatAdapter


class OpenRouterAdapter(OpenAICompatAdapter):
    name = "openrouter"
    base_url = "https://openrouter.ai/api/v1"
    config_alias = "openrouter"
    # Free model — adjust if OpenRouter rotates the slug. Caller
    # can always override via ``params["model"]``.
    model_default = "meta-llama/llama-3.3-70b-instruct:free"

    capabilities = {
        Capability.CHAT_COMPLETE,
        Capability.REASON_FAST,
        Capability.REASON_DEEP,
        Capability.CODE_GENERATE,
    }

    # Low priority — only used as a fallback after preferred
    # adapters fail or get rate-limited.
    priority = 40
    free_tier_daily_limit = 50   # very conservative — free tier
    cost_per_call = 0.0

    def extra_headers(self) -> dict[str, str]:
        """OpenRouter encourages identifying the calling app via
        ``HTTP-Referer`` and ``X-Title`` headers."""
        return {
            "HTTP-Referer": "https://shopai.local",
            "X-Title": "ShopAI Autonomous Operator",
        }
