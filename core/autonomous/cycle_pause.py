"""Operator pause / resume control for the autonomous cycle.

In addition to the live pause STATE (single file with the
current pause window), pause / resume / extend events are
appended to ``data/cycle_pause_history.json`` so operators
can audit "how often is the cycle paused?" + "what's the
total downtime?".


Operators need to halt the loop for maintenance,
investigation, or just because something looks wrong. Cron
runs the cycle every 30 minutes; manually editing
``/etc/cron.d/shopai`` is fragile. Setting an env var
doesn't persist across cron invocations.

This module is the operator's pause switch. A small JSON
file at ``data/cycle_pause.json`` carries
``{paused_until_at, reason}``. The cycle handler checks
at start; if ``paused_until_at > now``, it skips every
phase and returns a "paused" summary.

Pattern J: writes short-circuit under pytest.

Public surface
--------------
- ``pause(until_at, reason="")`` -> bool.
- ``resume()`` -> bool.
- ``is_paused()`` -> bool.
- ``get_pause_state()`` -> dict.
- ``clear()`` -- operator escape hatch.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_PAUSE_PATH = Path(
    os.environ.get(
        "SHOPAI_CYCLE_PAUSE_PATH",
        "data/cycle_pause.json",
    )
)

_PAUSE_HISTORY_PATH = Path(
    os.environ.get(
        "SHOPAI_CYCLE_PAUSE_HISTORY_PATH",
        "data/cycle_pause_history.json",
    )
)

_MAX_HISTORY = 1000


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> dict[str, Any]:
    try:
        if not _PAUSE_PATH.exists():
            return {}
        with _PAUSE_PATH.open(
            "r", encoding="utf-8",
        ) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "cycle_pause: load failed (%s)", exc,
        )
        return {}


def _atomic_write(data: dict[str, Any]) -> None:
    try:
        _PAUSE_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "cycle_pause: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".cycle_pause_",
            suffix=".json",
            dir=str(_PAUSE_PATH.parent),
        )
        try:
            with os.fdopen(
                fd, "w", encoding="utf-8",
            ) as f:
                json.dump(
                    data, f, indent=2, default=str,
                )
            os.replace(temp_path_str, _PAUSE_PATH)
        except Exception:
            try:
                os.unlink(temp_path_str)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.debug(
            "cycle_pause: write failed (%s)", exc,
        )


def _load_history() -> list[dict[str, Any]]:
    try:
        if not _PAUSE_HISTORY_PATH.exists():
            return []
        with _PAUSE_HISTORY_PATH.open(
            "r", encoding="utf-8",
        ) as f:
            data = json.load(f)
        if isinstance(data, list):
            return [
                e for e in data if isinstance(e, dict)
            ]
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "cycle_pause history: load failed (%s)", exc,
        )
        return []


def _write_history(entries: list[dict[str, Any]]) -> None:
    try:
        _PAUSE_HISTORY_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "cycle_pause history: mkdir failed (%s)",
            exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".cycle_pause_hist_",
            suffix=".json",
            dir=str(_PAUSE_HISTORY_PATH.parent),
        )
        try:
            with os.fdopen(
                fd, "w", encoding="utf-8",
            ) as f:
                json.dump(
                    entries, f, indent=2, default=str,
                )
            os.replace(
                temp_path_str, _PAUSE_HISTORY_PATH,
            )
        except Exception:
            try:
                os.unlink(temp_path_str)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.debug(
            "cycle_pause history: write failed (%s)",
            exc,
        )


def _append_history_event(
    *,
    kind: str,
    reason: str = "",
    paused_until_at: float | None = None,
) -> None:
    """Best-effort history append. Pattern J guard
    short-circuits. Never raises."""
    if _is_test_environment():
        return
    try:
        entries = _load_history()
        entries.append({
            "kind": kind,  # pause | resume | extend
            "reason": reason,
            "paused_until_at": paused_until_at,
            "recorded_at": time.time(),
        })
        if len(entries) > _MAX_HISTORY:
            entries = entries[-_MAX_HISTORY:]
        _write_history(entries)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cycle_pause history append raised: %s", exc,
        )


def pause_history(
    *,
    since_seconds: int = 86400 * 30,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Newest-first list of pause/resume/extend events."""
    now = now if now is not None else time.time()
    cutoff = now - since_seconds
    raw = _load_history()
    events: list[dict[str, Any]] = []
    for r in raw:
        ts = float(r.get("recorded_at", 0) or 0)
        if ts < cutoff:
            continue
        events.append(r)
    events.reverse()
    events.sort(
        key=lambda e: -float(
            e.get("recorded_at", 0) or 0,
        ),
    )
    return events


def pause(
    *,
    until_at: float,
    reason: str = "",
) -> bool:
    """Pause the cycle until ``until_at`` (unix timestamp).
    Returns True on write, False on test-env / I/O error."""
    if _is_test_environment():
        return False
    if not until_at or until_at <= 0:
        return False
    _atomic_write({
        "paused_until_at": float(until_at),
        "reason": reason or "",
        "paused_at": time.time(),
    })
    _append_history_event(
        kind="pause",
        reason=reason or "",
        paused_until_at=float(until_at),
    )
    return True


def extend(*, additional_hours: float) -> bool:
    """Extend the existing pause by ``additional_hours``.
    No-op when no active pause. Returns True on write."""
    if _is_test_environment():
        return False
    if additional_hours <= 0:
        return False
    state = get_pause_state()
    if not state.get("active"):
        return False
    new_until = (
        float(state["paused_until_at"])
        + additional_hours * 3600.0
    )
    _atomic_write({
        "paused_until_at": new_until,
        "reason": state.get("reason", ""),
        "paused_at": state.get(
            "paused_at", time.time(),
        ),
    })
    _append_history_event(
        kind="extend",
        reason=state.get("reason", "") or "",
        paused_until_at=new_until,
    )
    return True


def resume() -> bool:
    """Clear the pause file. Returns True when the file
    existed + got removed."""
    if _is_test_environment():
        return False
    if not _PAUSE_PATH.exists():
        return False
    try:
        _PAUSE_PATH.unlink()
        _append_history_event(kind="resume")
        return True
    except OSError as exc:
        logger.debug(
            "cycle_pause: unlink raised: %s", exc,
        )
        return False


def is_paused(
    *,
    now: float | None = None,
) -> bool:
    """True iff a pause is active. Expired pauses (where
    paused_until_at has passed) are treated as inactive."""
    state = get_pause_state(now=now)
    return state.get("active", False)


def get_pause_state(
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Return the current pause state. ``active`` is the
    effective bool; ``paused_until_at`` / ``reason`` /
    ``paused_at`` come from the file when present."""
    now = now if now is not None else time.time()
    data = _load_raw()
    if not data:
        return {
            "active": False,
            "paused_until_at": None,
            "reason": "",
            "paused_at": None,
        }
    until_at = float(
        data.get("paused_until_at", 0) or 0,
    )
    return {
        "active": until_at > now,
        "paused_until_at": until_at,
        "reason": str(data.get("reason", "") or ""),
        "paused_at": float(
            data.get("paused_at", 0) or 0,
        ),
    }


def clear() -> None:
    if _is_test_environment():
        return
    if _PAUSE_PATH.exists():
        try:
            _PAUSE_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "cycle_pause: unlink raised: %s", exc,
            )


def clear_history() -> None:
    """Operator escape hatch -- nuke the pause-history file.
    Pattern J short-circuits under pytest."""
    if _is_test_environment():
        return
    if _PAUSE_HISTORY_PATH.exists():
        try:
            _PAUSE_HISTORY_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "cycle_pause history: unlink raised: %s", exc,
            )


def _reset_for_tests(
    path: Path | None = None,
    *,
    history_path: Path | None = None,
) -> None:
    global _PAUSE_PATH, _PAUSE_HISTORY_PATH
    if path is not None:
        _PAUSE_PATH = path
    if history_path is not None:
        _PAUSE_HISTORY_PATH = history_path
