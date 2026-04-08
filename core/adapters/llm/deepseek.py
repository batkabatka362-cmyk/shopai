"""DeepSeek adapter — code generation + deep reasoning.

DeepSeek V3 / R1 sit at GPT-4 quality on benchmarks while
charging fractions of a cent per call. We pick this adapter for:

  * Shopify Functions Rust code generation
  * complex multi-step reasoning (strategy planning)
  * structured output / function calling

DeepSeek's free tier is generous (no hard daily cap on the
public chat endpoint at the time of writing) but we keep
``free_tier_daily_limit = 0`` here to indicate "unmetered" —
the metrics layer will still track usage so the operator can
see the volume.
"""
from __future__ import annotations

from ..base import Capability
from ._openai_compat import OpenAICompatAdapter


class DeepSeekAdapter(OpenAICompatAdapter):
    name = "deepseek"
    base_url = "https://api.deepseek.com/v1"
    config_alias = "deepseek"
    model_default = "deepseek-chat"

    capabilities = {
        Capability.CHAT_COMPLETE,
        Capability.REASON_DEEP,
        Capability.CODE_GENERATE,
    }

    # Higher priority for code generation than chat — router
    # picks DeepSeek before Groq when caller asks for
    # CODE_GENERATE.
    priority = 80
    free_tier_daily_limit = 0
    cost_per_call = 0.0002  # ~$0.14 per million input tokens
