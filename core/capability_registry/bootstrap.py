"""Bootstrap entry point -- call ``ensure_registered()`` once
to populate the registry with every batch.

Why a separate bootstrap module
-------------------------------
Capability registrations live in batch files
(``_register_<batch>.py``) so the registry can grow without
inflating any single file. The bootstrap module is the
single seam where Claude / autonomous loop / CLI ensures
the registry is hydrated before querying.

Idempotent: calling ``ensure_registered()`` twice is safe.
Registration overwrites by name, so reloading a batch file
(e.g. during pytest's module-level fixture rebuilds) doesn't
duplicate entries.
"""
from __future__ import annotations

import logging

from .registry import get_registry

logger = logging.getLogger(__name__)

_BOOTSTRAPPED: bool = False


def ensure_registered() -> None:
    """Populate the registry with all known batches. Safe to
    call repeatedly -- only the first call does work.

    Adding a new batch:
      1. Create ``_register_<name>.py`` with a top-level
         ``register_all()`` function.
      2. Import + call it inside this function.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    try:
        from . import _register_launch_chain
        _register_launch_chain.register_all()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "capability_registry: launch_chain batch raised: %s",
            exc,
        )

    try:
        from . import _register_engines
        _register_engines.register_all()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "capability_registry: engines batch raised: %s",
            exc,
        )

    try:
        from . import _register_marketing
        _register_marketing.register_all()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "capability_registry: marketing batch raised: %s",
            exc,
        )

    try:
        from . import _register_analytics
        _register_analytics.register_all()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "capability_registry: analytics batch raised: %s",
            exc,
        )

    try:
        from . import _register_audits
        _register_audits.register_all()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "capability_registry: audits batch raised: %s",
            exc,
        )

    try:
        from . import _register_external
        _register_external.register_all()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "capability_registry: external batch raised: %s",
            exc,
        )

    _BOOTSTRAPPED = True


def reset_for_tests() -> None:
    """Test-only hook: wipe the registry + the bootstrapped
    flag so the next ``ensure_registered()`` call rebuilds
    from scratch.
    """
    global _BOOTSTRAPPED
    get_registry().clear()
    _BOOTSTRAPPED = False
