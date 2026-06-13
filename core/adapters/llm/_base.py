"""LLM adapter abstract base.

Concrete LLM adapters (Groq, Gemini, DeepSeek, Mistral, Ollama,
OpenRouter, Hugging Face) extend ``LLMBaseAdapter`` to share the
common request/response shape, the optional ``requests`` import,
the rate-limit / 429 handling, and the AdapterResult contract.

Subclasses implement ``_call_vendor()`` (which makes the actual
HTTP call and returns a parsed dict) and let the base handle:

* prompt → message normalisation
* token counting (best-effort)
* HTTP error → ``AdapterError`` mapping
* AdapterResult assembly with latency / cost / model metadata

The base supports two capabilities by default:

  * ``Capability.CHAT_COMPLETE`` — single-shot chat
  * ``Capability.REASON_FAST``   — alias for chat_complete on
                                    fast vendors

Concrete adapters add more (``CODE_GENERATE``, ``LONG_CONTEXT``,
``IMAGE_ANALYZE``, ``EMBED_TEXT``) by overriding ``capabilities``
on the class.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from ..base import AdapterCategory, AdapterResult, BaseAdapter, Capability
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

# Optional requests import — same pattern as
# data_pipeline/ingestion/api/shopify_api.py so the test suite
# can run in environments where requests is not installed.
try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = get_logger("adapters.llm")


_DEFAULT_TIMEOUT = 30.0


class LLMBaseAdapter(BaseAdapter):
    """Abstract base for every LLM adapter.

    Subclasses MUST set ``name`` and SHOULD set ``model_default``
    and ``capabilities``. The base provides:

    * ``_chat()``  — common HTTP execution wrapper
    * ``_handle_http_error()`` — vendor status code → typed exception
    * ``_estimate_tokens()`` — best-effort token counting

    Concrete subclasses override ``_call_vendor()`` (low-level
    HTTP) and may override ``_build_request_payload()`` /
    ``_parse_response()`` to translate vendor-specific schemas.
    """

    category = AdapterCategory.LLM
    capabilities = {Capability.CHAT_COMPLETE, Capability.REASON_FAST}

    # Subclass-overridable defaults
    model_default: str = ""
    timeout: float = _DEFAULT_TIMEOUT
    max_tokens_default: int = 1024

    # Free-tier safety: subclasses set these so the metrics layer
    # can flag when we're approaching the daily quota
    free_tier_daily_limit: int = 0
    free_tier_monthly_limit: int = 0

    def is_configured(self) -> bool:  # noqa: D401
        """Override in subclasses that need an API key. The base
        check confirms the optional ``requests`` library is
        available — without it no LLM adapter can run anywhere."""
        return _REQUESTS_AVAILABLE

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        """Route the capability to the right internal handler.

        All chat-style capabilities funnel into ``_chat()``;
        embedding requests go to ``_embed()`` (which the base
        leaves unimplemented — embedding-capable adapters must
        override). Subclasses can extend this method to add
        additional capability branches.
        """
        if capability in (
            Capability.CHAT_COMPLETE,
            Capability.REASON_FAST,
            Capability.REASON_DEEP,
            Capability.CODE_GENERATE,
            Capability.LONG_CONTEXT,
            Capability.IMAGE_ANALYZE,
        ):
            return self._chat(capability, params)
        if capability == Capability.EMBED_TEXT:
            return self._embed(capability, params)
        raise AdapterValidationError(
            self.name, f"unhandled capability: {capability.value}",
        )

    # ── Chat completion ────────────────────────────────────────

    def _chat(self, capability: Capability, params: dict[str, Any]) -> AdapterResult:
        """Common chat completion path.

        ``params`` shape (every field optional unless noted):

        * ``prompt``      — string user input (required if
                            ``messages`` not given)
        * ``messages``    — OpenAI-style ``[{role, content}, …]``
        * ``system``      — system prompt to prepend
        * ``model``       — override the adapter's default model
        * ``temperature`` — sampling temperature (0.0–2.0)
        * ``max_tokens``  — generation cap
        * ``stop``        — list of stop sequences
        """
        messages = self._normalise_messages(params)
        if not messages:
            raise AdapterValidationError(
                self.name, "either 'prompt' or 'messages' is required",
            )

        model = params.get("model") or self.model_default
        max_tokens = int(params.get("max_tokens") or self.max_tokens_default)
        temperature = float(params.get("temperature", 0.7))
        stop = params.get("stop")

        payload = self._build_request_payload(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
            extra=params.get("extra", {}),
        )

        raw = self._call_vendor(payload, capability=capability)
        text, usage, response_model = self._parse_response(raw)

        cost = self._estimate_call_cost(
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
        )

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "text": text,
                "model": response_model or model,
                "messages": messages,
            },
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            cost_usd=cost,
            model=response_model or model,
            raw=raw,
        )

    def _embed(self, capability: Capability, params: dict[str, Any]) -> AdapterResult:
        """Override in adapters that support embeddings."""
        raise AdapterValidationError(
            self.name, "embedding not supported by this adapter",
        )

    # ── Hooks for subclasses ───────────────────────────────────

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
        """Default OpenAI-compatible payload. Override for
        vendors with a different schema (Gemini, Ollama, HF)."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if stop:
            payload["stop"] = stop
        if extra:
            payload.update(extra)
        return payload

    def _call_vendor(
        self,
        payload: dict[str, Any],
        *,
        capability: Capability,
    ) -> dict[str, Any]:
        """Concrete adapters MUST override. Should return the
        parsed JSON dict from the vendor.

        On vendor errors, raise the appropriate ``AdapterError``
        subclass — the base ``execute()`` method catches it.
        """
        raise NotImplementedError(
            f"{type(self).__name__}._call_vendor must be implemented",
        )

    def _parse_response(
        self,
        raw: dict[str, Any],
    ) -> tuple[str, dict[str, int], str]:
        """Default OpenAI-compatible parser. Returns
        ``(text, usage, model)``. Override for non-OpenAI
        schemas."""
        text = ""
        usage: dict[str, int] = {}
        model = ""

        try:
            choices = raw.get("choices") or []
            if choices:
                first = choices[0] or {}
                msg = first.get("message") or {}
                text = msg.get("content") or first.get("text", "") or ""
            usage = raw.get("usage") or {}
            model = raw.get("model", "")
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"failed to parse response: {type(exc).__name__}: {exc}",
            )

        return text, usage, model

    # ── Helpers ────────────────────────────────────────────────

    def _normalise_messages(
        self, params: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Convert the (prompt | messages) duo into a flat
        OpenAI-style messages list with optional system prompt
        prepended."""
        messages: list[dict[str, str]] = []
        system = params.get("system")
        if isinstance(system, str) and system:
            messages.append({"role": "system", "content": system})

        existing = params.get("messages")
        if isinstance(existing, list) and existing:
            for m in existing:
                if isinstance(m, dict) and "role" in m and "content" in m:
                    messages.append({
                        "role": str(m["role"]),
                        "content": str(m["content"]),
                    })
            return messages

        prompt = params.get("prompt")
        if isinstance(prompt, str) and prompt:
            messages.append({"role": "user", "content": prompt})
        return messages

    def _handle_http_error(
        self,
        status_code: int,
        body: str,
        *,
        retry_after: float | None = None,
    ) -> AdapterError:
        """Translate HTTP status → typed AdapterError. Used by
        every concrete adapter when their HTTP call returns a
        non-2xx response."""
        snippet = (body or "")[:200]
        if status_code == 401 or status_code == 403:
            return AdapterAuthError(
                self.name,
                f"vendor rejected credentials ({status_code}): {snippet}",
            )
        if status_code == 429:
            return AdapterRateLimited(
                self.name,
                f"rate limit ({status_code}): {snippet}",
                retry_after=retry_after,
            )
        if 500 <= status_code < 600:
            return AdapterUnavailable(
                self.name,
                f"vendor 5xx ({status_code}): {snippet}",
            )
        return AdapterError(
            self.name,
            f"vendor returned {status_code}: {snippet}",
        )

    def _estimate_call_cost(
        self,
        *,
        tokens_in: int,
        tokens_out: int,
    ) -> float:
        """Optional per-token cost calculation. Default returns
        ``cost_per_call``. Subclasses with token-based pricing
        override this."""
        return float(self.cost_per_call)

    # ── HTTP execution helper used by concrete adapters ───────

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Shared HTTP POST helper.

        W962-64: parity retry on 429 + 5xx + transient
        transport errors. Pre-fix the llm base parsed
        Retry-After + raised immediately without actually
        retrying.
        """
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )

        import time as _t
        last_exc: Exception | None = None
        for attempt in range(1, max(1, max_retries) + 1):
            try:
                response = _requests.post(
                    url,
                    json=payload,
                    headers=headers or {},
                    timeout=timeout if timeout is not None else self.timeout,
                )
            except _requests.Timeout as exc:  # type: ignore[union-attr]
                last_exc = exc
                if attempt < max_retries:
                    _t.sleep(min(2 ** attempt, 8))
                    continue
                raise AdapterTimeout(
                    self.name, f"timeout after {self.timeout}s: {exc}",
                ) from exc
            except _requests.ConnectionError as exc:  # type: ignore[union-attr]
                last_exc = exc
                if attempt < max_retries:
                    _t.sleep(min(2 ** attempt, 8))
                    continue
                raise AdapterUnavailable(
                    self.name, f"connection error: {exc}",
                ) from exc
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                msg = str(exc).lower()
                if any(s in msg for s in (
                    "chunkedencoding", "ssl", "protocol",
                    "remote disconnected",
                )) and attempt < max_retries:
                    _t.sleep(min(2 ** attempt, 8))
                    continue
                raise AdapterError(
                    self.name, f"http post failed: {type(exc).__name__}: {exc}",
                ) from exc

            if response.status_code >= 400:
                retry_after_header = response.headers.get("Retry-After", "")
                try:
                    retry_after = float(retry_after_header) if retry_after_header else None
                except ValueError:
                    retry_after = None
                # Retry transient errors
                if (
                    response.status_code == 429
                    or 500 <= response.status_code < 600
                ) and attempt < max_retries:
                    wait = (
                        retry_after if retry_after is not None
                        else min(2 ** attempt, 8)
                    )
                    _t.sleep(min(wait, 30))
                    continue
                raise self._handle_http_error(
                    response.status_code,
                    getattr(response, "text", "") or "",
                    retry_after=retry_after,
                )
            # success path falls through to caller body below
            break
        else:
            raise AdapterError(
                self.name,
                f"exhausted retries: {last_exc}" if last_exc else "exhausted retries",
            )

        try:
            return response.json() or {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON response: {exc}",
            ) from exc
