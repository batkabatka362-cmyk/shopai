"""Mistral adapter — EU-resident, GDPR-sovereign LLM.

Pick this adapter when:

  * the request carries EU customer PII and the operator wants
    to keep data inside the EU jurisdiction
  * the brain is configured with ``RouteContext(region="eu")``
  * regulatory audit logs require an EU-resident processor

Mistral's free "La Plateforme" tier exists but the per-minute
rate is lower than Groq. The router defaults to Groq for
non-EU traffic and only picks Mistral when the context flags
EU residency.
"""
from __future__ import annotations

from ..base import Capability
from ._openai_compat import OpenAICompatAdapter


class MistralAdapter(OpenAICompatAdapter):
    name = "mistral"
    base_url = "https://api.mistral.ai/v1"
    config_alias = "mistral"
    model_default = "mistral-small-latest"

    capabilities = {
        Capability.CHAT_COMPLETE,
        Capability.REASON_FAST,
        Capability.REASON_DEEP,
        Capability.CODE_GENERATE,
    }

    # Lower default priority than Groq because the free tier is
    # smaller. The router still picks Mistral first when the
    # caller sets ``RouteContext(region="eu")`` thanks to the
    # ``is_pii_safe`` override below.
    priority = 70
    free_tier_daily_limit = 0  # rate-limited per-minute, not per-day
    cost_per_call = 0.0001

    def is_pii_safe(self) -> bool:
        """EU-resident processor — safe for EU PII even though
        the data leaves the operator's machine. The router's
        PII-routing rule treats this as eligible."""
        return True
