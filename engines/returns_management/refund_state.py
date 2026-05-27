"""Refund pause state (Wave 103).

When Wave 103's health analyzer detects a degraded refund
loop (high adapter_failed rate, fraud_risk_too_high spike,
etc.), it writes a pause flag to ``data/refund_state.json``
that the Wave 101 ``refund_applier`` reads at the top of its
loop.

While paused:
  - refund_applier skips every row with ``status=paused``
  - record_refund still logs each skip (operator sees the
    pause's effect via ``shopai refund-status``)
  - operator clears the flag via ``shopai refund-resume``
    (CLI flips the flag back off)

Pattern matches the alert-quarantine state machine from PR
#294: env-gated bridge writes; operator-driven release.
Same JSON-backed persistence as alert_history.json + the
attribution snapshot store.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_PATH = Path("data") / "refund_state.json"


@dataclass
class RefundPauseState:
    paused: bool = False
    reason: str = ""
    paused_at: float = 0.0
    auto_resume_after: float = 0.0  # 0 = no auto-resume


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load() -> RefundPauseState:
    if not _STATE_PATH.exists():
        return RefundPauseState()
    try:
        with _STATE_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return RefundPauseState(
                paused=bool(raw.get("paused", False)),
                reason=str(raw.get("reason", "") or ""),
                paused_at=float(raw.get("paused_at", 0) or 0),
                auto_resume_after=float(
                    raw.get("auto_resume_after", 0) or 0,
                ),
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("refund_state load raised: %s", exc)
    return RefundPauseState()


def _save(state: RefundPauseState) -> None:
    if _is_test_environment():
        return
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=2)
    except Exception as exc:  # noqa: BLE001
        logger.debug("refund_state save raised: %s", exc)


def get_state() -> RefundPauseState:
    """Read the current pause state. Honors ``auto_resume_after``
    -- when set + when the deadline has passed, transparently
    flips the state back to unpaused."""
    state = _load()
    if (
        state.paused
        and state.auto_resume_after > 0
        and time.time() >= state.auto_resume_after
    ):
        state.paused = False
        state.reason = ""
        state.paused_at = 0.0
        state.auto_resume_after = 0.0
        _save(state)
    return state


def is_paused() -> bool:
    """Convenience accessor used by refund_applier at the top
    of its loop."""
    return get_state().paused


def pause(
    *,
    reason: str,
    auto_resume_after: float = 0.0,
) -> RefundPauseState:
    """Set the pause flag. ``auto_resume_after`` is an absolute
    epoch -- when set, the flag clears automatically after that
    deadline. 0 = no auto-resume (operator must clear)."""
    state = RefundPauseState(
        paused=True,
        reason=reason,
        paused_at=time.time(),
        auto_resume_after=auto_resume_after,
    )
    _save(state)
    return state


def resume() -> RefundPauseState:
    """Operator-initiated unpause."""
    state = RefundPauseState()  # all defaults = unpaused
    _save(state)
    return state
