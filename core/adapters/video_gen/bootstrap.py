"""Video generation adapter bootstrap.

Registers every video_gen adapter in the process-wide registry.
Safe to call repeatedly (replace=True ensures hot-reload on
key rotation). Unconfigured adapters stay registered so the
router can enumerate them for the operator dashboard but are
skipped when resolving capabilities (the registry sort puts
configured adapters first, unconfigured last).
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .higgsfield import HiggsfieldAdapter
from .pexels import PexelsAdapter
from .pixabay import PixabayAdapter
from .replicate import ReplicateAdapter

logger = get_logger("adapters.video_gen.bootstrap")


_VIDEO_GEN_ADAPTER_CLASSES = (
    PexelsAdapter,
    PixabayAdapter,
    HiggsfieldAdapter,
    ReplicateAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every video_gen adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map so callers
    can log / report how many video sources the process has
    active credentials for.
    """
    reg = registry if registry is not None else get_registry()
    status: dict[str, bool] = {}

    for cls in _VIDEO_GEN_ADAPTER_CLASSES:
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
        "Video-gen adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
