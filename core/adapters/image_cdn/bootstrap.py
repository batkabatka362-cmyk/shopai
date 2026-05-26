"""Image-CDN adapter bootstrap.

Single entry point that instantiates every image-CDN adapter
and registers it with ``AdapterRegistry``. Mirrors the LLM /
Email / Shopify / search / shipping / payment / image / sms /
scraper / translation bootstraps so the controller can call
all of them at startup with the same idempotency guarantees.

Usage::

    from core.adapters.image_cdn.bootstrap import register_all
    register_all()

ImageKit requires ``IMAGEKIT_PRIVATE_KEY``. The adapter still
registers when the key is unset; the smart router silently
skips it via ``is_configured()`` so the brain transparently
picks a different CDN (or surfaces ``NoAdapterAvailable``
when no adapter satisfies the capability).
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .imagekit import ImageKitAdapter

logger = get_logger("adapters.image_cdn.bootstrap")


_IMAGE_CDN_ADAPTER_CLASSES = (
    ImageKitAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every image-CDN adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map so callers
    (and the controller's startup probe) can warn about missing
    credentials without crashing the process.
    """
    reg = registry if registry is not None else get_registry()
    status: dict[str, bool] = {}

    for cls in _IMAGE_CDN_ADAPTER_CLASSES:
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
        "Image-CDN adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
