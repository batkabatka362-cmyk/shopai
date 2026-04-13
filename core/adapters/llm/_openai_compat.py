"""OpenAI-compatible LLM adapter base.

Many free-tier vendors implement the OpenAI ``/v1/chat/completions``
schema 1:1 (Groq, DeepSeek, Mistral, OpenRouter, Together AI,
Fireworks, Anyscale, ...). They differ only in:

  * the base URL
  * the model identifier
  * the auth header (always ``Authorization: Bearer <key>``)
  * the rate-limit / pricing numbers

Rather than copy 70 lines of HTTP plumbing into each subclass,
``OpenAICompatAdapter`` lifts the shared payload + parser +
``_call_vendor`` into a single class. Concrete adapters become
~25 lines of vendor-specific config (URL, model, free-tier
quotas) plus the ``name`` / ``capabilities`` overrides.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..config import get_config
from ..errors import AdapterNotConfigured
from ._base import LLMBaseAdapter


class OpenAICompatAdapter(LLMBaseAdapter):
    """Subclass for any vendor speaking OpenAI's chat completions
    schema. Subclasses MUST set:

      * ``name``           — registry key
      * ``base_url``       — vendor API root, e.g.
                             ``"https://api.groq.com/openai/v1"``
      * ``model_default``  — fallback model when caller doesn't
                             specify
      * ``config_alias``   — key in ``ENV_ALIASES`` that holds
                             the API key

    They MAY override:

      * ``capabilities``        — additional verbs they support
      * ``priority``            — router preference (0-100)
      * ``free_tier_daily_limit`` / ``free_tier_monthly_limit``
      * ``cost_per_call``       — average $/call
      * ``extra_headers()``     — non-Authorization headers
    """

    base_url: str = ""
    config_alias: str = ""

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        if not self.base_url:
            return False
        if not self.config_alias:
            return False
        return bool(get_config().get(self.config_alias))

    def extra_headers(self) -> dict[str, str]:
        """Override to add vendor-specific headers (e.g.
        OpenRouter ``HTTP-Referer``)."""
        return {}

    def _api_key(self) -> str:
        key = get_config().get(self.config_alias)
        if not key:
            env_var = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env_var or self.config_alias})",
            )
        return key

    def _endpoint_url(self) -> str:
        """Default ``/chat/completions`` path. Override if your
        vendor uses a different route."""
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def _call_vendor(
        self,
        payload: dict[str, Any],
        *,
        capability: Capability,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers())

        return self._post_json(
            self._endpoint_url(),
            payload,
            headers=headers,
        )
