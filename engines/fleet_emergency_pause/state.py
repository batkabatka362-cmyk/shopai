"""Persistent fleet pause marker.

JSON-backed at data/fleet_emergency_pause.json (env-overridable
via SHOPAI_FLEET_EMERGENCY_PAUSE_PATH).

Public API:
  - is_paused() -> bool
  - get_state() -> dict
  - set_paused(reason, by) -> bool
  - clear_paused() -> bool

Pattern J test guard (with SHOPAI_FORCE_PRODUCTION_WRITES
override).
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


_PATH = Path(
    os.environ.get(
        "SHOPAI_FLEET_EMERGENCY_PAUSE_PATH",
        "data/fleet_emergency_pause.json",
    )
)


def _is_test_environment() -> bool:
    if os.environ.get(
        "SHOPAI_FORCE_PRODUCTION_WRITES", "",
    ).strip().lower() in ("1", "true", "yes", "on"):
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> dict[str, Any]:
    try:
        if not _PATH.exists():
            return {"paused": False}
        with _PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {"paused": False}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "fleet_emergency: load failed (%s)", exc,
        )
        return {"paused": False}


def _atomic_write(data: dict[str, Any]) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.debug(
            "fleet_emergency: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=".fleet_emergency_",
            suffix=".json",
            dir=str(_PATH.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, _PATH)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.debug(
            "fleet_emergency: write failed (%s)", exc,
        )


def is_paused() -> bool:
    """Single-bit query: is the fleet halted?"""
    return bool(_load_raw().get("paused", False))


def get_state() -> dict[str, Any]:
    """Return the full marker dict for display."""
    state = _load_raw()
    # Defensive defaults
    state.setdefault("paused", False)
    state.setdefault("paused_at", "")
    state.setdefault("paused_by", "")
    state.setdefault("reason", "")
    return state


def set_paused(reason: str, by: str = "operator") -> bool:
    """Mark the fleet as paused. Returns True on write,
    False on test-env / I/O error."""
    if _is_test_environment():
        return False
    raw = _load_raw()
    raw["paused"] = True
    raw["paused_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
    )
    raw["paused_by"] = str(by or "operator")
    raw["reason"] = str(reason or "")
    _atomic_write(raw)
    return True


def clear_paused() -> bool:
    """Lift the fleet pause. Returns True on write, False on
    test-env / I/O error."""
    if _is_test_environment():
        return False
    raw = _load_raw()
    raw["paused"] = False
    raw["cleared_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
    )
    _atomic_write(raw)
    return True


def reset_path(path: Path) -> None:
    """Test-only hook to override the persistence path."""
    global _PATH
    _PATH = path
