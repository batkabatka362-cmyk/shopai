"""Webhook → LearningLoop feedback bridge (audit #5).

The autonomous loop already records what the system *intended*
(decisions in MemoryIntelligence) and what it *did* on Shopify
(writebacks in DataArchitecture). What was missing: what
*actually happened next* — the orders, refunds, and cancellations
that downstream-tested those decisions in the real world.

This package closes the loop. It listens on the existing Shopify
webhook stream (``core.webhooks.ShopifyWebhookHandler``), matches
each event back to an EXECUTED engine action where possible, and
feeds the LearningLoop with a real-world outcome signal so the
brain layer learns from production behaviour, not just its own
predictions.

Public surface:

  * :class:`WebhookFeedbackBridge` — ``handle_event(topic, payload)``
  * :func:`get_webhook_feedback_bridge` — process-wide singleton.
"""
from __future__ import annotations

from core.feedback.webhook_bridge import (
    WebhookFeedbackBridge,
    get_webhook_feedback_bridge,
)

__all__ = [
    "WebhookFeedbackBridge",
    "get_webhook_feedback_bridge",
]
