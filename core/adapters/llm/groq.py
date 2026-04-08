"""Groq adapter — primary chat / fast reasoning.

Why Groq is the default chat adapter:

* **Speed**: 300+ tokens/sec on Llama 3.3 70B (LPU hardware) —
  ~5x faster than Gemini Flash, ideal for real-time customer
  service responses.
* **Free tier**: 14,400 requests/day, 30 req/min — the most
  generous unconditional free tier among OpenAI-compatible
  vendors.
* **Open weights**: Llama 3.3, Llama 4, Mixtral, Qwen — no
  vendor lock-in, can be swapped to a self-hosted Ollama
  instance running the same model with zero prompt rewrites.
* **No training on prompts** (per Groq's privacy policy).

Free tier reference (subject to change — keep numbers in env if
they drift): https://console.groq.com/docs/rate-limits
"""
from __future__ import annotations

from ..base import Capability
from ._openai_compat import OpenAICompatAdapter


class GroqAdapter(OpenAICompatAdapter):
    name = "groq"
    base_url = "https://api.groq.com/openai/v1"
    config_alias = "groq"
    model_default = "llama-3.3-70b-versatile"

    capabilities = {
        Capability.CHAT_COMPLETE,
        Capability.REASON_FAST,
        Capability.REASON_DEEP,
        Capability.CODE_GENERATE,
    }

    # High priority because it's the fastest free option in the
    # registry. Router prefers it for chat by default.
    priority = 90

    # Free tier: 14400 RPD, 30 RPM (Llama 3.3 70B versatile)
    free_tier_daily_limit = 14_400
    free_tier_monthly_limit = 0  # no monthly cap on free tier
    cost_per_call = 0.0
