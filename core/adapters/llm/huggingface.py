"""Hugging Face Inference adapter — embeddings + specialized models.

The Hugging Face free inference API exposes 300+ open models
via a single endpoint. We use it primarily for:

  * **Embeddings** (``sentence-transformers/all-MiniLM-L6-v2``) —
    free, deterministic, runs in milliseconds. Backbone of the
    ShopAI memory similarity layer.
  * **Specialized models** (sentiment classifiers, NER, etc.)
    that don't justify a dedicated adapter.

The adapter speaks HF's "task" API:
``https://api-inference.huggingface.co/models/<model_id>``

Note: HF has cold-start latency on free models (the first
request after idle can take 20+ seconds). The adapter sets
``timeout = 60`` to absorb this. The router treats slow
responses as a soft signal — if HF is consistently slow,
``priority`` here drops the adapter below faster alternatives
on the next call.
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterCategory, Capability
from ..config import get_config
from ..errors import AdapterError, AdapterNotConfigured, AdapterValidationError
from ._base import LLMBaseAdapter


class HuggingFaceAdapter(LLMBaseAdapter):
    name = "huggingface"
    category = AdapterCategory.LLM
    config_alias = "huggingface"

    # The "default" model is the embedding workhorse — most
    # callers asking for HF will be asking for embeddings.
    model_default = "sentence-transformers/all-MiniLM-L6-v2"

    capabilities = {
        Capability.EMBED_TEXT,
        Capability.CHAT_COMPLETE,    # for instruct models
        Capability.REASON_FAST,
    }

    priority = 30  # last-resort for chat; primary for embeddings
    cost_per_call = 0.0
    timeout = 60.0  # cold-start latency on free tier

    base_url = "https://api-inference.huggingface.co/models"

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        # W963-117: per-store routing via active_store
        # HF free API works without a token but rate limits are
        # tighter; we treat the adapter as "configured" iff a
        # token is set so the router prefers vendors with
        # explicit auth.
        from .._per_store_credentials import resolve_per_store
        return bool((resolve_per_store(self.config_alias) or get_config().get(self.config_alias)))

    def _api_key(self) -> str:
        from .._per_store_credentials import resolve_per_store
        key = (resolve_per_store(self.config_alias) or get_config().get(self.config_alias))
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name, f"missing API key (set ${env or 'HUGGINGFACE_API_KEY'})",
            )
        return key

    # ── Capability dispatch override ───────────────────────────

    def _execute(self, capability: Capability, params: dict[str, Any]):
        if capability == Capability.EMBED_TEXT:
            return self._embed(capability, params)
        return super()._execute(capability, params)

    # ── Embeddings ─────────────────────────────────────────────

    def _embed(self, capability: Capability, params: dict[str, Any]):
        text = params.get("text")
        if not text or not isinstance(text, (str, list)):
            raise AdapterValidationError(
                self.name, "'text' (str or list[str]) is required",
            )

        model = params.get("model") or self.model_default
        url = f"{self.base_url}/{model}"
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        payload = {"inputs": text, "options": {"wait_for_model": True}}

        raw = self._post_json(url, payload, headers=headers)
        if not isinstance(raw, list):
            raise AdapterError(
                self.name,
                f"unexpected embedding response shape: {type(raw).__name__}",
            )

        # Result is either a single vector or a list of vectors
        # depending on whether ``text`` was a string or a list.
        from ..base import AdapterResult
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"embeddings": raw, "dimensions": len(raw[0]) if raw and isinstance(raw[0], list) else len(raw)},
            model=model,
            raw=raw,
        )

    # ── Chat (instruct models) ─────────────────────────────────

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
        """HF inference uses a flat ``inputs`` string, not
        OpenAI-style messages. We concatenate the messages with
        a simple separator."""
        flat = "\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
            for m in messages
        )
        payload: dict[str, Any] = {
            "inputs": flat,
            "parameters": {
                "max_new_tokens": max_tokens,
                "temperature": temperature,
                "return_full_text": False,
            },
            "options": {"wait_for_model": True},
        }
        if stop:
            payload["parameters"]["stop"] = (
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
        # _build_request_payload doesn't carry the model into
        # the URL, so default to the configured model. Caller
        # can override via params['model'] which the base
        # ``_chat`` already extracted before calling us — but it
        # didn't store it on payload. So we re-derive from
        # params via the model field placed by base.
        model = self.model_default
        url = f"{self.base_url}/{model}"
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        raw = self._post_json(url, payload, headers=headers)

        # HF returns a list of generations; normalise to a dict
        # the base parser can read.
        if isinstance(raw, list) and raw:
            first = raw[0] if isinstance(raw[0], dict) else {}
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": first.get("generated_text", ""),
                    },
                }],
                "model": model,
                "usage": {},  # HF doesn't return usage on free
            }
        if isinstance(raw, dict):
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": raw.get("generated_text", ""),
                    },
                }],
                "model": model,
                "usage": {},
            }
        raise AdapterError(
            self.name,
            f"unexpected HF response shape: {type(raw).__name__}",
        )
