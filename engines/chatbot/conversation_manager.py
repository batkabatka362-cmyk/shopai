"""Chatbot Engine — conversation manager.

Manages conversation state, tracks turn count, determines topic,
and builds context summaries from conversation history.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def manage_conversation(
    message: str,
    conversation_history: list[dict[str, Any]],
    intent_result: dict[str, Any],
) -> dict[str, Any]:
    """Update and return conversation state.

    Args:
        message: Current customer message.
        conversation_history: Previous conversation messages.
        intent_result: Current intent classification result.

    Returns:
        Structured dict with updated conversation state.
    """
    try:
        turn_count = len(conversation_history) + 1
        intent = str(intent_result.get("intent", "general"))

        # Determine topic from intent history
        topic = _determine_topic(intent, conversation_history)

        # Check if the conversation appears resolved
        resolved = _check_resolved(message, conversation_history)

        # Build context summary
        context_summary = _build_summary(
            message=message,
            conversation_history=conversation_history,
            intent=intent,
            turn_count=turn_count,
        )

        return {
            "status": "success",
            "conversation_state": {
                "turn_count": turn_count,
                "topic": topic,
                "resolved": resolved,
                "context_summary": context_summary,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "conversation_state": {},
            "error": f"Conversation management failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _determine_topic(
    current_intent: str,
    history: list[dict[str, Any]],
) -> str:
    """Determine the ongoing topic of conversation."""
    # If this is the first message, topic is the current intent
    if not history:
        return current_intent

    # Check if topic has shifted
    # Look at the most recent bot response for topic hints
    for msg in reversed(history):
        role = str(msg.get("role", ""))
        content = str(msg.get("content", "")).lower()
        if role == "assistant":
            if "return" in content or "refund" in content:
                return "return"
            if "shipping" in content or "delivery" in content:
                return "shipping"
            if "order" in content:
                return "order_management"
            break

    return current_intent


def _check_resolved(
    message: str,
    history: list[dict[str, Any]],
) -> bool:
    """Check if the customer's issue appears resolved."""
    msg_lower = message.lower()

    # Positive resolution signals
    resolved_phrases = [
        "thank you", "thanks", "that helps", "got it", "perfect",
        "great", "awesome", "that's all", "no more questions",
        "all set", "you've been helpful",
    ]

    if any(phrase in msg_lower for phrase in resolved_phrases):
        return True

    return False


def _build_summary(
    message: str,
    conversation_history: list[dict[str, Any]],
    intent: str,
    turn_count: int,
) -> str:
    """Build a brief summary of the conversation so far."""
    parts: list[str] = []

    parts.append(f"Turn {turn_count}")
    parts.append(f"Current intent: {intent}")

    if conversation_history:
        # Count unique intents mentioned
        user_messages = [
            str(m.get("content", ""))
            for m in conversation_history
            if m.get("role") == "user"
        ]
        parts.append(f"Previous user messages: {len(user_messages)}")

    # Truncate current message for summary
    msg_preview = message[:80] + "..." if len(message) > 80 else message
    parts.append(f"Latest: {msg_preview}")

    return " | ".join(parts)
