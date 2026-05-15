"""Webhook subscription registry — declarative source of truth
for which Shopify webhook topics this app subscribes to.

Mirrors the OAuth scope registry (PRs #173-#179) for the
webhook surface: every topic the app cares about has a single
declaration with its polarity, purpose, and lifecycle metadata.

Before this registry, the polarity buckets lived as hard-coded
sets inside ``webhook_bridge.py``:

  _POSITIVE_TOPICS = {"orders/create", "orders/paid"}
  _NEGATIVE_TOPICS = {"orders/cancelled", "refunds/create"}

The bridge consumed them directly. Operators wanting to know
"which webhook topics does this app need at install time?"
had to grep across the codebase. Worse, GDPR-mandated topics
(customers/data_request, customers/redact, shop/redact) that
Shopify REQUIRES for every public-distribution app weren't
declared anywhere — they had to be remembered.

This registry centralises:

  - **Subscribed topics**: each declared with polarity for the
    bridge's outcome attribution + a one-line purpose comment.
  - **GDPR-mandated topics**: declared with the
    ``gdpr_mandatory=True`` flag so they appear in the install
    manifest even though the bridge doesn't tag them with a
    polarity (they're consumed by a different handler).
  - **Operational topics**: app/uninstalled — operationally
    necessary so the system can react to an uninstall (clean
    up state) without polling.

The bridge derives ``_POSITIVE_TOPICS`` / ``_NEGATIVE_TOPICS``
from this registry. Changing a topic's polarity is now a
one-line edit here instead of a cross-file search.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebhookSubscription:
    """One Shopify webhook topic this app subscribes to."""

    topic: str
    polarity: str  # "positive" | "negative" | "neutral"
    purpose: str
    gdpr_mandatory: bool = False


# Source of truth: every Shopify webhook topic the app needs.
WEBHOOK_REGISTRY: tuple[WebhookSubscription, ...] = (
    # ── Outcome attribution (positive) ──────────────────────
    WebhookSubscription(
        topic="orders/create",
        polarity="positive",
        purpose=(
            "Match minted discount codes to actual orders — "
            "primary positive outcome signal for engines that "
            "create codes"
        ),
    ),
    WebhookSubscription(
        topic="orders/paid",
        polarity="positive",
        purpose=(
            "Confirm payment completed on a matched order — "
            "second-stage positive signal (orders/create fires "
            "first, then orders/paid confirms revenue)"
        ),
    ),
    # ── Outcome attribution (negative) ──────────────────────
    WebhookSubscription(
        topic="orders/cancelled",
        polarity="negative",
        purpose=(
            "Engine-attributed order was cancelled — negative "
            "outcome (revenue didn't materialise)"
        ),
    ),
    WebhookSubscription(
        topic="refunds/create",
        polarity="negative",
        purpose=(
            "Engine-attributed order was refunded — negative "
            "outcome with metrics.revenue capturing the refund "
            "amount"
        ),
    ),
    # ── GDPR-mandatory (every public-distribution Shopify app
    #    MUST subscribe to these three) ──────────────────────
    WebhookSubscription(
        topic="customers/data_request",
        polarity="neutral",
        purpose=(
            "GDPR: merchant requested a customer's data export. "
            "App must respond within 30 days with all stored "
            "customer data."
        ),
        gdpr_mandatory=True,
    ),
    WebhookSubscription(
        topic="customers/redact",
        polarity="neutral",
        purpose=(
            "GDPR: merchant requested deletion of a customer's "
            "data. App must purge within 30 days."
        ),
        gdpr_mandatory=True,
    ),
    WebhookSubscription(
        topic="shop/redact",
        polarity="neutral",
        purpose=(
            "GDPR: 48 hours after uninstall, app must purge all "
            "data associated with the merchant's shop."
        ),
        gdpr_mandatory=True,
    ),
    # ── Operational lifecycle ───────────────────────────────
    WebhookSubscription(
        topic="app/uninstalled",
        polarity="neutral",
        purpose=(
            "Merchant uninstalled the app — clean up local "
            "state, stop processing for the shop. Precedes the "
            "48-hour countdown to shop/redact."
        ),
    ),
)


def all_topics() -> frozenset[str]:
    """Flat set of every subscribed topic."""
    return frozenset(sub.topic for sub in WEBHOOK_REGISTRY)


def positive_topics() -> frozenset[str]:
    """Topics tagged as positive outcome signals — consumed by
    the bridge's polarity classification."""
    return frozenset(
        sub.topic for sub in WEBHOOK_REGISTRY
        if sub.polarity == "positive"
    )


def negative_topics() -> frozenset[str]:
    """Topics tagged as negative outcome signals."""
    return frozenset(
        sub.topic for sub in WEBHOOK_REGISTRY
        if sub.polarity == "negative"
    )


def gdpr_topics() -> frozenset[str]:
    """GDPR-mandatory topics — every public Shopify app MUST
    subscribe to these to pass review."""
    return frozenset(
        sub.topic for sub in WEBHOOK_REGISTRY
        if sub.gdpr_mandatory
    )


def get_subscription(topic: str) -> WebhookSubscription | None:
    """Return the registered subscription for ``topic``, or
    ``None`` if not subscribed."""
    for sub in WEBHOOK_REGISTRY:
        if sub.topic == topic:
            return sub
    return None
