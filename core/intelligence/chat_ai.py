"""ChatAI — customer chat routing placeholder.

**Important:** this module used to pretend to be an AI. It contained
~150 lines of hardcoded regex intent detection (``order_status``,
``shipping``, ``returns``, ``recommendation``, ...) and canned
string responses ("📦 **Shipping Info:**\\n• Standard shipping:
5-7 business days..."). Every one of those responses was static
template copy that had no relationship to the merchant's actual
shipping policy, return window, discount codes, or products.
Worse, it returned ``"confidence": "high"`` for matches so callers
believed they were getting an AI-generated answer when it was a
1-line regex match.

That fiction has been removed. ``ChatAI`` now only acts as a
routing **placeholder**: it returns a structured response with
``status = "adapter_required"`` and the raw message so the
adapter layer (Shopify Inbox + Gemini/Claude LLM) can take over
once it lands. Keeping the same class name and ``respond()``
signature means no consumer import breaks during the transition —
callers simply need to check the ``status`` field and fall back
to their own handling (or wait for the real adapter).
"""
from __future__ import annotations

from typing import Any


class ChatAI:
    """Placeholder chat router. Real AI logic lives in the adapter layer.

    The old implementation did regex intent detection (10 intents,
    ~100 lines) and returned canned template replies. Both are
    gone — the only surviving behaviour is returning the input
    message and a ``status = "adapter_required"`` sentinel so that
    the future Gemini/Claude + Shopify Inbox adapter can own the
    real response generation without any consumer code change.
    """

    def respond(
        self,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a placeholder response for *message*.

        Pre-cleanup this method returned one of ten canned replies
        selected by a regex over the message text. It now returns
        an explicit ``adapter_required`` envelope and does no
        intent classification of its own. The ``message`` and
        ``context`` fields are echoed back so the adapter layer
        can pick them up when it is wired in.
        """
        return {
            "status": "adapter_required",
            "adapter": "chat_ai",
            "message": message if isinstance(message, str) else "",
            "context": context or {},
            "response": "",
            "action": "route_to_adapter",
            "intent": "unknown",
            "confidence": "none",
        }
