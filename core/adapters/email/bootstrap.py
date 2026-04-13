"""Email adapter bootstrap.

Single entry point that instantiates every email adapter and
registers it with ``AdapterRegistry``. Mirrors the LLM /
Shopify / search / shipping bootstraps so the controller can
call all five at startup with the same idempotency guarantees.

Usage::

    from core.adapters.email.bootstrap import register_all
    register_all()

Both email adapters require an API key; there is no no-key
default (unlike DDGS or Ollama). Operators must wire at least
one of ``BREVO_API_KEY`` / ``RESEND_API_KEY`` before the brain
can actually send mail. Adapters whose key is unset still
register; the smart router simply skips them via
``is_configured()``.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .brevo import BrevoAdapter
from .klaviyo import KlaviyoAdapter
from .resend import ResendAdapter
from .sendgrid import SendGridAdapter

logger = get_logger("adapters.email.bootstrap")


_EMAIL_ADAPTER_CLASSES = (
    BrevoAdapter,
    KlaviyoAdapter,
    ResendAdapter,
    SendGridAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every email adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map.
    """
    reg = registry or get_registry()
    status: dict[str, bool] = {}

    for cls in _EMAIL_ADAPTER_CLASSES:
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
        "Email adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
