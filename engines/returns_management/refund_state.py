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
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_PATH = Path("data") / "refund_state.json"

# W962-45: spanning lock for get_state's auto-resume +
# pause/resume. Concurrent operator resume + auto-resume
# would race otherwise.
_LOCK = threading.RLock()


@dataclass
class RefundPauseState:
    paused: bool = False
    reason: str = ""
    paused_at: float = 0.0
    auto_resume_after: float = 0.0  # 0 = no auto-resume


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load() -> RefundPauseState:
    """W962-55: fail-closed on corruption. Refund is real-money;
    treating an unparseable state file as "not paused" would
    let real-money refunds resume firing. Instead remain
    paused with a synthetic reason so the applier loop skips
    until the operator inspects + clears."""
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
        logger.warning(
            "refund_state contains non-dict JSON; "
            "FAIL-CLOSED to paused=True until operator clears",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "refund_state load raised %s; FAIL-CLOSED to "
            "paused=True until operator inspects + clears",
            exc,
        )
    return RefundPauseState(
        paused=True,
        reason="auto_paused_corrupt_state_file",
        paused_at=time.time(),
        auto_resume_after=0.0,
    )


def _save(state: RefundPauseState) -> None:
    """W962-45: atomic write via temp + os.replace so a crash
    mid-write can't leave a corrupt JSON file."""
    if _is_test_environment():
        return
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_PATH.with_suffix(
            _STATE_PATH.suffix + f".tmp.{os.getpid()}"
        )
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=2)
        os.replace(tmp, _STATE_PATH)
    except Exception as exc:  # noqa: BLE001
        logger.debug("refund_state save raised: %s", exc)


def get_state() -> RefundPauseState:
    """Read the current pause state. Honors ``auto_resume_after``
    -- when set + when the deadline has passed, transparently
    flips the state back to unpaused."""
    # W962-45: span the read+auto-resume+save so concurrent
    # pause/resume can't slip in.
    with _LOCK:
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
    with _LOCK:
        _save(state)
    return state


def resume() -> RefundPauseState:
    """Operator-initiated unpause."""
    state = RefundPauseState()  # all defaults = unpaused
    with _LOCK:
        _save(state)
    return state
