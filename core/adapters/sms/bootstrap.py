"""SMS adapter bootstrap.

Single entry point that instantiates every SMS adapter and
registers it with ``AdapterRegistry``. Mirrors the LLM / Email /
Shopify / search / shipping / payment / image bootstraps so the
controller can call all of them at startup with the same
idempotency guarantees.

Usage::

    from core.adapters.sms.bootstrap import register_all
    register_all()

Twilio requires ``TWILIO_ACCOUNT_SID``, ``TWILIO_AUTH_TOKEN``,
and ``TWILIO_FROM_NUMBER``. The adapter still registers when
any are unset; the smart router silently skips it via
``is_configured()`` so the brain transparently picks a different
SMS vendor (or surfaces ``NoAdapterAvailable`` when no adapter
satisfies the capability).
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .twilio import TwilioAdapter

logger = get_logger("adapters.sms.bootstrap")


_SMS_ADAPTER_CLASSES = (
    TwilioAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every SMS adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map so callers
    (and the controller's startup probe) can warn about missing
    credentials without crashing the process.
    """
    reg = registry if registry is not None else get_registry()
    status: dict[str, bool] = {}

    for cls in _SMS_ADAPTER_CLASSES:
        try:
            adapter = cls()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to instantiate %s: %s", cls.__name__, exc,
            )
            continue

        try:
            reg.register(adapter, replace=True)
            status[adapter.name] = adapter.is_configured()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to register %s: %s", adapter.name, exc,
            )

    configured = sum(1 for v in status.values() if v)
    logger.info(
        "SMS adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
