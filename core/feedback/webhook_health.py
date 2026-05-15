"""Live webhook subscription health check.

Mirrors ``core/adapters/shopify/scope_health.py`` for the
webhook surface. The webhook registry (PR #182) declares what
topics the app expects to subscribe to; the manifest generator
(PR #182) emits the deployable TOML fragment. But neither
catches the runtime case: the merchant's actual app install
might have a different set of webhook subscriptions registered
on Shopify's side than the registry declares.

First symptom of a stale subscription set:
  - Engine actions fire, but outcomes never attribute (the
    bridge silently never receives the matching event)
  - OR Shopify review rejects the install because a GDPR-
    mandatory topic isn't registered

Both are slow / hard-to-debug. This module surfaces the drift
directly.

It calls ``SHOPIFY_LIST_WEBHOOKS`` via the webhooks adapter,
collects the registered topics from the response, and compares
against the declared registry. Reports:

  - **missing_on_app**: declared but not registered. The bridge
    will never see these events.
  - **extra_on_app**: registered but not declared. The
    operator's app may be subscribed to topics this codebase
    doesn't handle (legacy install, half-rolled-back change,
    over-subscription).
  - **gdpr_missing**: the strictest subset of missing_on_app —
    GDPR-mandatory topics that aren't registered. Public-
    distribution Shopify apps MUST register all three; this
    elevates the visibility for that specific failure.

Returns ``None`` when the webhooks adapter is unconfigured or
the API call fails — same fail-open contract as scope_health.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from utils.logger import get_logger

from core.feedback.webhook_registry import (
    all_topics,
    gdpr_topics,
)

logger = get_logger("feedback.webhook_health")


@dataclass(frozen=True)
class WebhookHealthReport:
    """Live vs declared webhook comparison."""

    registered_topics: frozenset[str]
    declared_topics: frozenset[str]
    missing_on_app: list[str]
    extra_on_app: list[str]
    gdpr_missing: list[str]
    is_healthy: bool


def _enum_to_rest(enum_form: str) -> str:
    """Convert Shopify's GraphQL enum topic form (e.g.
    ``ORDERS_CREATE``) back to the REST-style identifier
    (``orders/create``) the registry uses.

    Most GDPR-mandatory topics include a slash and an
    underscore: ``customers/data_request`` ↔
    ``CUSTOMERS_DATA_REQUEST``. The first underscore separates
    the resource from the action; subsequent underscores stay.
    """
    if not isinstance(enum_form, str) or not enum_form:
        return ""
    lowered = enum_form.strip().lower()
    # Resource name is everything up to the first underscore;
    # the rest stays joined.
    if "_" not in lowered:
        return lowered
    resource, _, rest = lowered.partition("_")
    return f"{resource}/{rest}"


def compare_to_live(adapter: Any = None) -> WebhookHealthReport | None:
    """Compare the webhook registry's declared topics against
    what Shopify reports the live app installation actually
    has registered.

    Args:
        adapter: Optional pre-constructed
            :class:`ShopifyWebhooksAdapter` instance. Production
            callers pass ``None``.

    Returns:
        :class:`WebhookHealthReport` on success, ``None`` when
        the live data isn't available (unconfigured adapter,
        network failure, malformed response).
    """
    if adapter is None:
        try:
            from core.adapters.shopify.webhooks import (
                ShopifyWebhooksAdapter,
            )
            adapter = ShopifyWebhooksAdapter()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "webhooks adapter init failed: %s", exc,
            )
            return None
        if not adapter.is_configured():
            logger.debug("webhooks adapter not configured")
            return None

    try:
        from core.adapters.base import Capability
        # Page through; collect every registered topic. Shopify
        # caps page size at 250 — for now we just read the first
        # page since any production-grade install has well under
        # 250 subscriptions. A future PR can paginate if needed.
        result = adapter.execute(
            Capability.SHOPIFY_LIST_WEBHOOKS,
            {"limit": 250},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "webhook list call failed: %s", exc,
        )
        return None

    if not getattr(result, "ok", False):
        logger.debug(
            "webhook list returned not-ok: %s",
            getattr(result, "error", "unknown"),
        )
        return None

    data = getattr(result, "data", {}) or {}
    if not isinstance(data, dict):
        return None
    webhooks = data.get("webhooks")
    if not isinstance(webhooks, list):
        return None

    # Each entry has a `topic` field from _normalise_webhook;
    # Shopify returns the GraphQL enum form (e.g. ORDERS_CREATE).
    # Convert back to REST form for comparison with the registry.
    registered = frozenset(
        _enum_to_rest(str(w.get("topic", "")))
        for w in webhooks
        if isinstance(w, dict) and w.get("topic")
    )
    declared = all_topics()

    missing = sorted(declared - registered)
    extra = sorted(registered - declared)
    gdpr_missing_set = gdpr_topics() & set(missing)

    return WebhookHealthReport(
        registered_topics=registered,
        declared_topics=declared,
        missing_on_app=missing,
        extra_on_app=extra,
        gdpr_missing=sorted(gdpr_missing_set),
        is_healthy=not missing,
    )
