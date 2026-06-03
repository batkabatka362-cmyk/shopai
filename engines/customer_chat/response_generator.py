"""Draft response generator for customer messages.

Two stages:
  1. Template lookup by intent. Substitutes operator-supplied
     context (customer_name, order_id, etc) into placeholders.
  2. Optional LLM refinement when CHAT_COMPLETE adapter is
     configured and ``use_llm=True``.

The template baseline always works, even with no LLM key. The
LLM refinement adds personality + tone-matching when available.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ResponseDraft:
    intent: str
    text: str
    used_llm: bool = False
    requires_human_review: bool = False


_TEMPLATES: dict[str, str] = {
    "order_status": (
        "Hi {name},\n\n"
        "Thanks for reaching out! I can look up your order "
        "right away. Could you share your order number "
        "(starts with #)? You can find it in your order "
        "confirmation email.\n\n"
        "{order_blurb}"
        "Once I have that, I'll send you the latest tracking "
        "update.\n\n"
        "Best,\n"
        "{store_signature}"
    ),
    "shipping": (
        "Hi {name},\n\n"
        "Great question! Here are our shipping options:\n\n"
        "  - Standard (5-7 business days): typically free over "
        "  $50\n"
        "  - Express (2-3 business days): rates calculated at "
        "  checkout\n"
        "  - International: 7-14 business days, customs may "
        "  apply\n\n"
        "Once your order ships, you'll get a tracking link by "
        "email. Let me know if you'd like specifics for your "
        "country!\n\n"
        "Best,\n"
        "{store_signature}"
    ),
    "returns": (
        "Hi {name},\n\n"
        "I'm sorry the item didn't work out. We accept returns "
        "within 30 days of delivery for unused items in the "
        "original packaging.\n\n"
        "{order_blurb}"
        "To start a return:\n"
        "  1. Reply with your order number\n"
        "  2. Let us know which item(s) you'd like to return\n"
        "  3. We'll send you a prepaid label and refund "
        "  confirmation within 24 hours\n\n"
        "Best,\n"
        "{store_signature}"
    ),
    "product_question": (
        "Hi {name},\n\n"
        "Happy to help with that! Could you let me know which "
        "specific product you're asking about? (Product name "
        "or link works great.)\n\n"
        "I'll get you all the details — materials, sizing, "
        "compatibility, anything you need.\n\n"
        "Best,\n"
        "{store_signature}"
    ),
    "complaint": (
        "Hi {name},\n\n"
        "I'm really sorry to hear this — that's not the "
        "experience we want any customer to have.\n\n"
        "{order_blurb}"
        "Let's make this right. Could you share:\n"
        "  - Your order number\n"
        "  - A photo of the issue if possible\n"
        "  - Whether you'd prefer a replacement or full refund\n\n"
        "I'll take care of this personally and get back to you "
        "within 24 hours.\n\n"
        "Sincerely,\n"
        "{store_signature}"
    ),
    "greeting_other": (
        "Hi {name},\n\n"
        "Thanks for reaching out! I'd love to help — could you "
        "share a bit more about what you're looking for? Order "
        "status, a product question, returns, shipping — "
        "happy to dig in.\n\n"
        "Best,\n"
        "{store_signature}"
    ),
}


# Intents that should never auto-send without human review.
_HUMAN_REVIEW_REQUIRED = {"complaint", "returns"}


def _build_context(
    *,
    customer_name: str | None,
    order_id: str | None,
    store_name: str | None,
) -> dict[str, str]:
    """Build the dict used for template substitution."""
    name = customer_name or "there"
    store = store_name or "ShopAI Support"
    if order_id:
        order_blurb = (
            f"I see you mentioned order #{order_id} — "
            "I'll pull it up.\n\n"
        )
    else:
        order_blurb = ""
    return {
        "name": name,
        "order_blurb": order_blurb,
        "store_signature": store,
    }


def generate_response(
    *,
    intent: str,
    customer_name: str | None = None,
    order_id: str | None = None,
    store_name: str | None = None,
    use_llm: bool = False,
    message: str | None = None,
) -> ResponseDraft:
    """Generate a draft response for the given intent."""
    intent_key = (
        intent if intent in _TEMPLATES else "greeting_other"
    )
    template = _TEMPLATES[intent_key]
    ctx = _build_context(
        customer_name=customer_name,
        order_id=order_id,
        store_name=store_name,
    )
    text = template.format(**ctx)

    draft = ResponseDraft(
        intent=intent_key,
        text=text,
        used_llm=False,
        requires_human_review=intent_key in _HUMAN_REVIEW_REQUIRED,
    )

    if use_llm and message:
        refined = _llm_refine(
            base_text=text,
            intent=intent_key,
            customer_message=message,
            customer_name=ctx["name"],
        )
        if refined:
            draft.text = refined
            draft.used_llm = True

    return draft


def _llm_refine(
    *,
    base_text: str,
    intent: str,
    customer_message: str,
    customer_name: str,
) -> str | None:
    """Call CHAT_COMPLETE to refine the templated response.

    Returns None when no LLM adapter is wired or the call fails.
    Failures are non-fatal -- the template baseline is returned
    instead.
    """
    try:
        from core.adapters.router import get_router
        from core.adapters.base import Capability
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM router unavailable: %s", exc)
        return None

    prompt = (
        f"You are a customer service agent. The customer sent:\n"
        f"---\n{customer_message}\n---\n\n"
        f"The intent is classified as: {intent}.\n\n"
        f"Below is a templated draft response. Refine it to "
        f"sound natural, warm, and personalised to the customer's "
        f"specific message. Keep the same structure + key info "
        f"but improve the voice. Address the customer as "
        f"'{customer_name}'. Keep the response under 200 words.\n\n"
        f"DRAFT:\n{base_text}\n\nREFINED:"
    )

    try:
        result = router.execute(
            Capability.CHAT_COMPLETE,
            {
                "prompt": prompt,
                "max_tokens": 350,
                "temperature": 0.6,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("CHAT_COMPLETE raised: %s", exc)
        return None

    if not getattr(result, "ok", False):
        return None
    data = getattr(result, "data", None) or {}
    text = ""
    if isinstance(data, dict):
        text = str(
            data.get("text")
            or data.get("response")
            or data.get("output")
            or "",
        ).strip()
    return text or None
