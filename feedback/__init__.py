"""feedback/ — outcome + attribution + closed-loop telemetry.

Per docs/FOLDER_REORG_PLAN.md Phase 2. Gathers the modules
that together implement §4b.B "Closed-loop telemetry" discipline.

Physical modules live under core/attribution, core/learning,
core/bridge/agentic_storefront, and core/adapters/triplewhale.
"""
from __future__ import annotations

try:
    from core.attribution.outcome_recorder import (  # noqa: F401
        OutcomeEvent,
        OutcomeRecorder,
    )
except Exception:  # noqa: BLE001
    OutcomeEvent = None      # type: ignore[assignment]
    OutcomeRecorder = None   # type: ignore[assignment]

try:
    from core.bridge.agentic_storefront import (  # noqa: F401
        AgenticStorefrontBridge,
        get_agentic_bridge,
    )
except Exception:  # noqa: BLE001
    AgenticStorefrontBridge = None    # type: ignore[assignment]
    get_agentic_bridge = None         # type: ignore[assignment]

try:
    from core.integration.engine_outcome_bus import (  # noqa: F401
        EngineOutcome,
        EngineOutcomeBus,
        get_engine_outcome_bus,
    )
except Exception:  # noqa: BLE001
    EngineOutcome = None               # type: ignore[assignment]
    EngineOutcomeBus = None            # type: ignore[assignment]
    get_engine_outcome_bus = None      # type: ignore[assignment]


__all__ = [
    "AgenticStorefrontBridge",
    "EngineOutcome",
    "EngineOutcomeBus",
    "OutcomeEvent",
    "OutcomeRecorder",
    "get_agentic_bridge",
    "get_engine_outcome_bus",
]
