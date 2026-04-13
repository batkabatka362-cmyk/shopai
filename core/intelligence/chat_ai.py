"""ChatAI — customer chat routed through the LLM adapter layer.

History:

  * **Pre-cleanup** ChatAI was a regex matcher that pretended
    to be an AI. It returned hardcoded template strings that
    had no relationship to the merchant's real policies, and
    reported high confidence so callers thought they were
    getting AI-generated answers.
  * **Cleanup pass** ripped the regex + templates out and made
    ``respond()`` return an ``adapter_required`` envelope so
    consumers could detect the gap.
  * **This migration** routes the message through the
    ``SmartRouter`` using ``Capability.CHAT_COMPLETE``. The
    router picks the best configured LLM adapter (Groq → Gemini
    → DeepSeek → Mistral → Ollama → OpenRouter → HuggingFace)
    with automatic fallback. When NO adapter is wired the
    method still returns the placeholder envelope so existing
    callers don't break.

The class signature (``ChatAI().respond(message, context)``) is
unchanged; new code just gets a real ``response`` field instead
of an empty string.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("intelligence.chat_ai")


_SYSTEM_PROMPT = (
    "You are a customer service assistant for an e-commerce store. "
    "Be concise, friendly, and helpful. If you don't know the answer "
    "or need order-specific information, say so honestly and suggest "
    "the customer reach out to support. Never invent shipping policies, "
    "return windows, or discount codes — answer only with information "
    "the merchant has actually provided in the context."
)


class ChatAI:
    """Customer chat router. Delegates to the LLM adapter layer.

    The class is intentionally thin: ``respond()`` builds a
    prompt from the customer message + optional context dict,
    sends it through the SmartRouter, and returns either the
    LLM's reply or the cleanup-era ``adapter_required``
    placeholder when no adapter is available.
    """

    def respond(
        self,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a response for *message*.

        Args:
            message: Raw customer text.
            context: Optional dict with merchant data the LLM
                should consider (recent orders, customer name,
                product details, ...). Forwarded into the
                prompt verbatim — caller controls what the LLM
                sees.

        Returns:
            Structured envelope::

                {
                    "status": "ok" | "adapter_required" | "error",
                    "response": "...",
                    "intent": "unknown",      # placeholder for future
                    "confidence": "low|med|high|none",
                    "adapter": "groq" | "gemini" | ...,
                    "model": "...",
                    "message": "<echo of original>",
                    "context": {...},
                }

            ``status = "adapter_required"`` is returned when no
            LLM adapter is configured at all — same shape as the
            cleanup-era placeholder so legacy consumers keep
            working.
        """
        ctx = context or {}
        msg = message if isinstance(message, str) else ""

        result = self._route_to_llm(msg, ctx)
        if result is None:
            # No router available at all — adapter package
            # missing or import failed.
            return self._placeholder(msg, ctx)
        if not result.ok:
            # Router exists but every candidate failed (no
            # configured adapter, vendor outage, ...). Return
            # the placeholder envelope so callers can detect
            # the gap. Logged at debug level — the metrics
            # collector already records the failure cause.
            logger.debug(
                "chat_ai router returned failure: %s",
                type(result.error).__name__ if result.error else "?",
            )
            return self._placeholder(msg, ctx)

        text = (result.data or {}).get("text", "") or ""
        if not text.strip():
            return self._placeholder(msg, ctx)

        return {
            "status": "ok",
            "response": text.strip(),
            "intent": "unknown",  # placeholder for future intent classifier
            "confidence": "medium",
            "adapter": result.adapter,
            "model": result.model or "",
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "message": msg,
            "context": ctx,
        }

    # ── Internals ──────────────────────────────────────────────

    def _route_to_llm(
        self,
        message: str,
        context: dict[str, Any],
    ) -> Any:
        """Send the message through the SmartRouter using
        ``Capability.CHAT_COMPLETE``. Returns the
        ``AdapterResult`` (success or failure), or ``None`` if
        the adapter package is unavailable / import failed.
        """
        try:
            from core.adapters import Capability, get_router
        except Exception as exc:  # noqa: BLE001
            logger.debug("adapter import failed: %s", exc)
            return None

        prompt = self._build_prompt(message, context)
        try:
            return get_router().execute(
                Capability.CHAT_COMPLETE,
                {
                    "prompt": prompt,
                    "system": _SYSTEM_PROMPT,
                    "max_tokens": 400,
                    "temperature": 0.3,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("chat_ai router raised: %s", exc)
            return None

    @staticmethod
    def _build_prompt(message: str, context: dict[str, Any]) -> str:
        """Build the user-side prompt. Includes the merchant
        context as a JSON-style block so the LLM can ground its
        answer in real data instead of inventing policies."""
        parts: list[str] = []
        if context:
            # Compact JSON-ish dump of the context — the LLM is
            # very good at parsing this without prose framing.
            import json
            try:
                ctx_dump = json.dumps(context, ensure_ascii=False, default=str)
            except Exception:  # noqa: BLE001
                ctx_dump = str(context)
            parts.append(f"CONTEXT: {ctx_dump}")
        parts.append(f"CUSTOMER MESSAGE: {message}")
        parts.append(
            "Reply directly to the customer in 1-3 sentences. "
            "Do not preface with 'Sure' or 'I'd be happy'.",
        )
        return "\n\n".join(parts)

    @staticmethod
    def _placeholder(message: str, context: dict[str, Any]) -> dict[str, Any]:
        """Return the cleanup-era ``adapter_required`` envelope.

        Used when the LLM adapter layer cannot satisfy the
        request (no adapter configured, every candidate failed,
        empty response). The shape matches what the cleanup
        commit pinned so existing tests + callers don't break.
        """
        return {
            "status": "adapter_required",
            "adapter": "chat_ai",
            "message": message,
            "context": context,
            "response": "",
            "action": "route_to_adapter",
            "intent": "unknown",
            "confidence": "none",
        }
