"""Generic autonomy pause-state machine (Wave 118).

Extracts the pattern from
``engines/returns_management/refund_state.py`` (Wave 103) and
``engines/roas_guardrails/budget_state.py`` (Wave 111): JSON-
backed pause flag with auto_resume_after deadline support.

Each domain provides:
  - A state path (e.g. ``data/inventory_pause_state.json``)

Pattern J guard: writes no-op under ``PYTEST_CURRENT_TEST``.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PauseState:
    paused: bool = False
    reason: str = ""
    paused_at: float = 0.0
    auto_resume_after: float = 0.0


def is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def load_state(path: Path) -> PauseState:
    """Load + return the pause state. Empty default when file
    missing OR corrupt."""
    if not path.exists():
        return PauseState()
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return PauseState(
                paused=bool(raw.get("paused", False)),
                reason=str(raw.get("reason", "") or ""),
                paused_at=float(raw.get("paused_at", 0) or 0),
                auto_resume_after=float(
                    raw.get("auto_resume_after", 0) or 0,
                ),
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("pause_state load raised: %s", exc)
    return PauseState()


def save_state(path: Path, state: PauseState) -> None:
    if is_test_environment():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=2)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pause_state save raised: %s", exc)


def get_state(path: Path) -> PauseState:
    """Read pause state. Auto-resume clears the flag when the
    deadline has passed + persists the cleared state."""
    state = load_state(path)
    if (
        state.paused
        and state.auto_resume_after > 0
        and time.time() >= state.auto_resume_after
    ):
        state.paused = False
        state.reason = ""
        state.paused_at = 0.0
        state.auto_resume_after = 0.0
        save_state(path, state)
    return state


def is_paused(path: Path) -> bool:
    return get_state(path).paused


def pause(
    path: Path,
    *,
    reason: str,
    auto_resume_after: float = 0.0,
) -> PauseState:
    """Set the pause flag."""
    state = PauseState(
        paused=True,
        reason=reason,
        paused_at=time.time(),
        auto_resume_after=auto_resume_after,
    )
    save_state(path, state)
    return state


def resume(path: Path) -> PauseState:
    """Clear the pause flag."""
    state = PauseState()
    save_state(path, state)
    return state
