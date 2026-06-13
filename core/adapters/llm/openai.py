"""OpenAIAdapter -- the canonical OpenAI API.

ShopAI's LLM consultant overlay (SHOPAI_AI_STRATEGY=1)
references "openai is the canonical default" but pre-fix
no adapter existed -- only the OpenAI-compatible vendors
(Groq, DeepSeek, Mistral, OpenRouter, etc) and the local
Ollama. An operator setting OPENAI_API_KEY would see
api-status flag "brain ready" but the router had no
adapter to route through.

W963-104 closes this gap.

Why ship OpenAI directly when Groq is faster + free:
  * Premium intelligence tier (gpt-4o / o1) for reasoning-
    heavy paths (strategic_advisor / action_critic /
    action_proposer).
  * Operators with existing OpenAI subscriptions get a
    drop-in path without onboarding a second vendor.
  * Some downstream prompts target gpt-4-family model
    capabilities specifically.

OpenAI is OpenAI-compatible by definition (every other
adapter in this directory implements OpenAI's schema). So
this adapter is a 4-line subclass of OpenAICompatAdapter.

Free tier reference: OpenAI does NOT offer an
unconditional free tier; paid usage starts immediately.
Free credits ($5) for new accounts expire after 3 months.
Cost ladder (Dec 2024):
  gpt-4o-mini:     $0.15/1M in, $0.60/1M out
  gpt-4o:          $2.50/1M in, $10.00/1M out
  o1-mini:         $3.00/1M in, $12.00/1M out
"""
from __future__ import annotations

from ..base import Capability
from ._openai_compat import OpenAICompatAdapter


class OpenAIAdapter(OpenAICompatAdapter):
    """OpenAI chat completions adapter."""

    name = "openai"
    base_url = "https://api.openai.com/v1"
    config_alias = "openai"
    # Default to gpt-4o-mini: balances cost (~5% of gpt-4o)
    # with quality good enough for the consultant overlay's
    # baseline refinements. Operators can override per-call
    # via params["model"] for strategic paths needing gpt-4o.
    model_default = "gpt-4o-mini"

    capabilities = {
        Capability.CHAT_COMPLETE,
        Capability.REASON_FAST,
        Capability.REASON_DEEP,
        Capability.CODE_GENERATE,
        Capability.LONG_CONTEXT,
    }

    # Below Groq (90) because Groq is faster + free, but
    # above the slower / less-mainstream alternatives. When
    # the router is asked for a chat completion and both are
    # configured, Groq still wins by default; operators
    # opt into OpenAI via RouteContext(prefer=["openai"])
    # for premium reasoning tasks.
    priority = 80

    # OpenAI has no unconditional free tier; the $5 new-
    # account credit is short-lived. Quotas left at 0 to
    # signal "paid usage immediately".
    free_tier_daily_limit = 0
    free_tier_monthly_limit = 0
    # Average cost per chat call across mini/standard tiers.
    cost_per_call = 0.002
