"""Operator pause / resume control for the autonomous cycle.

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


def _reset_for_tests(path: Path | None = None) -> None:
    global _PAUSE_PATH
    if path is not None:
        _PAUSE_PATH = path
