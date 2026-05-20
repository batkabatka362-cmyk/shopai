"""Auto-register missing webhook subscriptions.

Companion to ``core/feedback/webhook_health.py`` which *detects*
drift. This module *closes* it.

The motivating failure mode (caught live by shopify-doctor):
the manifest declares 8 webhook topics including 3
GDPR-mandatory ones (``customers/data_request``,
``customers/redact``, ``shop/redact``), but the running install
has registered ZERO of them. Public-distribution Shopify review
WILL REJECT the app until those three are registered.

This module bridges that gap: takes a callback URL, finds the
missing topics via the existing health check, and POSTs each
missing subscription through the webhooks adapter.

Operator workflow::

    $ shopai shopify-webhooks-register-missing \\
        --callback-url https://app.shopai.com/webhooks/shopify

Single callback URL for all topics is the conventional
Shopify pattern -- the receiving handler dispatches on the
``X-Shopify-Topic`` header. Per-topic separate URLs are
supported via a future ``--callback-fn`` argument; not in
this first pass.

The function never raises -- failures are collected into
``failed_topics`` so the operator gets a single coherent
report instead of having to retry through partial state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger

from core.feedback.webhook_health import compare_to_live
from core.feedback.webhook_registry import gdpr_topics

logger = get_logger("feedback.webhook_drift_fixer")


@dataclass
class WebhookRegisterReport:
    """Result of an auto-register run."""

    callback_url: str
    target_topics: list[str] = field(default_factory=list)
    registered: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    drift_unavailable: bool = False

    @property
    def is_clean(self) -> bool:
        """True when every targeted topic was registered (or
        was already registered) and none failed."""
        return not self.failed and not self.drift_unavailable


def auto_register_missing_topics(
    *,
    callback_url: str,
    only_gdpr: bool = False,
    webhooks_adapter: Any = None,
    webhook_format: str = "JSON",
) -> WebhookRegisterReport:
    """Register every missing webhook subscription on the live
    install.

    Args:
        callback_url: HTTPS endpoint Shopify will POST every
            event to. Conventionally a single URL with the
            handler dispatching on ``X-Shopify-Topic``.
        only_gdpr: When True, only the GDPR-mandatory topics
            are targeted. The other operational topics
            (orders/create / orders/paid / etc.) are skipped
            -- useful when the operator wants to satisfy
            review requirements first and add the rest after
            verifying the bridge wiring.
        webhooks_adapter: Optional pre-built
            :class:`ShopifyWebhooksAdapter` for tests.
            Production callers pass ``None`` so the function
            wires its own.
        webhook_format: ``"JSON"`` or ``"XML"``. Default JSON
            -- matches the bridge's expectations.

    Returns:
        :class:`WebhookRegisterReport`. ``is_clean`` is True
        when every targeted topic ended in the registered or
        already-registered list and none failed.

    The function never raises -- adapter failures and
    individual create errors are collected into ``failed`` and
    returned for the operator to inspect.
    """
    callback_url = (callback_url or "").strip()
    if not callback_url:
        return WebhookRegisterReport(
            callback_url="",
            drift_unavailable=False,
            failed=[{
                "topic": "",
                "error": "callback_url_required",
            }],
        )

    # Discover what's missing on the live install. If
    # compare_to_live returns None, the apps adapter is not
    # configured or the API call failed -- we can't safely
    # register anything blind.
    drift = compare_to_live(adapter=webhooks_adapter)
    if drift is None:
        return WebhookRegisterReport(
            callback_url=callback_url,
            drift_unavailable=True,
        )

    missing = list(drift.missing_on_app)
    if only_gdpr:
        gdpr = gdpr_topics()
        missing = [t for t in missing if t in gdpr]

    report = WebhookRegisterReport(
        callback_url=callback_url,
        target_topics=list(missing),
    )

    if not missing:
        return report

    # Resolve adapter for the create calls. Reuse the one
    # passed in (tests inject a single mock that handles both
    # list + create); otherwise build one fresh.
    if webhooks_adapter is None:
        webhooks_adapter = _build_webhooks_adapter()
        if webhooks_adapter is None:
            for topic in missing:
                report.failed.append({
                    "topic": topic,
                    "error": "adapter_unavailable",
                })
            return report

    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        for topic in missing:
            report.failed.append({
                "topic": topic,
                "error": f"capability_import_failed: {exc}",
            })
        return report

    for topic in missing:
        params = {
            "topic": topic,
            "callback_url": callback_url,
            "format": webhook_format,
        }
        try:
            result = webhooks_adapter.execute(
                Capability.SHOPIFY_CREATE_WEBHOOK, params,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "create webhook %s raised: %s", topic, exc,
            )
            report.failed.append({
                "topic": topic, "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            err_str = str(err)
            # Shopify returns a user-error when the topic is
            # already subscribed at the same callback. Treat
            # that as already-registered rather than a failure
            # -- the system is in the right state, the call
            # was just redundant.
            if (
                "already" in err_str.lower()
                or "duplicate" in err_str.lower()
            ):
                report.skipped_existing.append(topic)
                continue
            report.failed.append({
                "topic": topic, "error": err_str,
            })
            continue

        report.registered.append(topic)

    return report


def _build_webhooks_adapter() -> Any:
    """Construct a ShopifyWebhooksAdapter from configured
    credentials. Returns ``None`` if not configured."""
    try:
        from core.adapters.shopify.webhooks import (
            ShopifyWebhooksAdapter,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "ShopifyWebhooksAdapter import failed: %s", exc,
        )
        return None
    try:
        adapter = ShopifyWebhooksAdapter()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "ShopifyWebhooksAdapter init failed: %s", exc,
        )
        return None
    if not adapter.is_configured():
        logger.debug("ShopifyWebhooksAdapter not configured")
        return None
    return adapter
