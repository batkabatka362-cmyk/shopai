"""shipping_alert pause state (Wave 757). Thin template wrapper."""
from __future__ import annotations

from pathlib import Path

from core.automation.pause_state import (
    PauseState,
    get_state as _get_state,
    is_paused as _is_paused,
    pause as _pause,
    resume as _resume,
)


_STATE_PATH = Path("data") / "shipping_alert_state.json"


def get_state() -> PauseState:
    return _get_state(_STATE_PATH)


def is_paused() -> bool:
    return _is_paused(_STATE_PATH)


def pause(
    *, reason: str, auto_resume_after: float = 0.0,
) -> PauseState:
    return _pause(
        _STATE_PATH,
        reason=reason,
        auto_resume_after=auto_resume_after,
    )


def resume() -> PauseState:
    return _resume(_STATE_PATH)
