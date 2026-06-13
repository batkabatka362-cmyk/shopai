"""Marketing budget pause state (Wave 111).

When Wave 111's health analyzer detects a degrading marketing
loop (low ROAS, high failed-mutation rate), it writes a pause
flag that the Wave 112 ``budget_applier`` reads at the top of
its loop.

While paused:
  - budget_applier skips every campaign with status="paused"
  - record_ad_spend_event still logs each skip (operator sees
    the pause's effect via `shopai marketing-status`)
  - operator clears via `shopai marketing-resume`

Mirrors ``engines/returns_management/refund_state.py`` for
pattern consistency.
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

_STATE_PATH = Path("data") / "budget_state.json"

# W962-45: spanning lock for get_state's auto-resume +
# pause/resume races.
_LOCK = threading.RLock()


@dataclass
class BudgetPauseState:
    paused: bool = False
    reason: str = ""
    paused_at: float = 0.0
    auto_resume_after: float = 0.0


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load() -> BudgetPauseState:
    """W962-55: fail-closed on corruption. Budget mutations are
    real-money; unparseable state file -> remain paused until
    operator inspects + clears."""
    if not _STATE_PATH.exists():
        return BudgetPauseState()
    try:
        with _STATE_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return BudgetPauseState(
                paused=bool(raw.get("paused", False)),
                reason=str(raw.get("reason", "") or ""),
                paused_at=float(raw.get("paused_at", 0) or 0),
                auto_resume_after=float(
                    raw.get("auto_resume_after", 0) or 0,
                ),
            )
        logger.warning(
            "budget_state contains non-dict JSON; "
            "FAIL-CLOSED to paused=True until operator clears",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "budget_state load raised %s; FAIL-CLOSED to "
            "paused=True until operator inspects + clears",
            exc,
        )
    return BudgetPauseState(
        paused=True,
        reason="auto_paused_corrupt_state_file",
        paused_at=time.time(),
        auto_resume_after=0.0,
    )


def _save(state: BudgetPauseState) -> None:
    """W962-45: atomic write via temp + os.replace."""
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
        logger.debug("budget_state save raised: %s", exc)


def get_state() -> BudgetPauseState:
    """Read pause state. Honors auto_resume_after deadlines."""
    # W962-45: span auto-resume read-modify-write.
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
    return get_state().paused


def pause(
    *,
    reason: str,
    auto_resume_after: float = 0.0,
) -> BudgetPauseState:
    state = BudgetPauseState(
        paused=True,
        reason=reason,
        paused_at=time.time(),
        auto_resume_after=auto_resume_after,
    )
    with _LOCK:
        _save(state)
    return state


def resume() -> BudgetPauseState:
    state = BudgetPauseState()
    with _LOCK:
        _save(state)
    return state
