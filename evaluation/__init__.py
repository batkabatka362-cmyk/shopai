"""evaluation/ — testing, simulation, verification, calibration.

Per docs/FOLDER_REORG_PLAN.md Phase 2. Groups the modules that
answer the question "is this decision good?" before or after
it ships.

Pytest suite lives in ``tests/`` (flat); the facade here
re-exports runtime evaluation primitives only.
"""
from __future__ import annotations

try:
    from simulation.launch_simulator import (  # noqa: F401
        LaunchCandidate,
        LaunchProjection,
        simulate_launch,
    )
except Exception:  # noqa: BLE001
    LaunchCandidate = None      # type: ignore[assignment]
    LaunchProjection = None     # type: ignore[assignment]
    simulate_launch = None      # type: ignore[assignment]

try:
    from execution.verify.post_write_verifier import (  # noqa: F401
        DriftReport,
        VerifyConfig,
        verify_write,
    )
except Exception:  # noqa: BLE001
    DriftReport = None          # type: ignore[assignment]
    VerifyConfig = None         # type: ignore[assignment]
    verify_write = None         # type: ignore[assignment]

try:
    from core.brain.world_model_calibration import (  # noqa: F401
        CalibratedPrediction,
        WorldModelCalibration,
        get_world_model_calibration,
    )
except Exception:  # noqa: BLE001
    CalibratedPrediction = None         # type: ignore[assignment]
    WorldModelCalibration = None        # type: ignore[assignment]
    get_world_model_calibration = None  # type: ignore[assignment]


__all__ = [
    "CalibratedPrediction",
    "DriftReport",
    "LaunchCandidate",
    "LaunchProjection",
    "VerifyConfig",
    "WorldModelCalibration",
    "get_world_model_calibration",
    "simulate_launch",
    "verify_write",
]
