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
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# W962-21 race fix: serialise per-path read-modify-write
# (auto-resume + pause + resume can race with each other
# and with parallel domain probes).
_PATH_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_MUTEX = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve()) if path.exists() else str(path)
    with _LOCKS_MUTEX:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


@dataclass
class PauseState:
    paused: bool = False
    reason: str = ""
    paused_at: float = 0.0
    auto_resume_after: float = 0.0


def is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def load_state(path: Path) -> PauseState:
    """Load + return the pause state.

    W962-55 fail-closed semantics: if the file is MISSING, the
    domain has never been paused -> return PauseState() with
    paused=False (correct default). But if the file EXISTS and
    fails to parse, we cannot know whether the operator paused
    or auto-pause bridge fired -- treating it as unpaused
    would let real-money mutations resume. Instead return
    paused=True with a synthetic reason so the applier loop
    skips until the operator inspects + clears.

    Pre-fix corruption silently un-paused. With atomic writes
    (W962-21) corruption from crashes is rare, but external
    tampering, disk failure, or pre-W962-21 partial writes
    are still real failure modes. Fail-closed treats the
    uncertain state as safer-not-riskier."""
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
        # Non-dict raw -> treat as corrupted
        logger.warning(
            "pause_state %s contains non-dict JSON %r; "
            "FAIL-CLOSED to paused=True until operator clears",
            path, type(raw).__name__,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "pause_state %s load raised %s; FAIL-CLOSED to "
            "paused=True until operator inspects + clears",
            path, exc,
        )
    return PauseState(
        paused=True,
        reason="auto_paused_corrupt_state_file",
        paused_at=time.time(),
        auto_resume_after=0.0,
    )


def save_state(path: Path, state: PauseState) -> None:
    if is_test_environment():
        return
    # W962-21: atomic write — temp file in the same directory
    # then os.replace. A crash mid-write no longer leaves a
    # partial JSON file that load_state would reject.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError as exc:
                # fsync failures are best-effort; the
                # os.replace() that follows is still atomic.
                # Logging at debug to keep the Wave 11
                # no-bare-except-pass policy happy.
                logger.debug(
                    "pause_state fsync failed: %s", exc,
                )
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pause_state save raised: %s", exc)


def get_state(path: Path) -> PauseState:
    """Read pause state. Auto-resume clears the flag when the
    deadline has passed + persists the cleared state."""
    with _lock_for(path):
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
    with _lock_for(path):
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
    with _lock_for(path):
        state = PauseState()
        save_state(path, state)
        return state
