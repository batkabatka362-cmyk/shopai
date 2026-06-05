"""Canonical persistence helpers for the empire-AGI loop.

Two patterns are duplicated across 24+ engine modules:

  1. Pattern J test-environment guard:
       def _is_test_environment() -> bool:
           if os.environ.get("SHOPAI_FORCE_PRODUCTION_WRITES",
                              "").lower() in ("1", "true", "yes"):
               return False
           return bool(os.environ.get("PYTEST_CURRENT_TEST"))

  2. Atomic JSON write:
       fd, tmp = tempfile.mkstemp(prefix=..., dir=parent)
       os.close(fd)
       with open(tmp, "w") as f:
           json.dump(entries, f, indent=2, default=str)
       os.replace(tmp, str(path))

W963-92 hoists both into this module so future engineers
implement them ONCE. Pattern CC audits that W963-session
modules use these helpers instead of redefining.

Public API:
  is_test_environment()       Pattern J guard
  atomic_write_json(path, x)  atomic JSON write
  load_json_list(path)        tolerant load (returns [])
  load_json_dict(path)        tolerant load (returns {})
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def is_test_environment() -> bool:
    """The canonical Pattern J guard.

    Returns True when running under pytest AND
    SHOPAI_FORCE_PRODUCTION_WRITES is not set. Engines that
    write to persistent storage should short-circuit on
    this so test runs don't pollute production data.

    Examples:
        if is_test_environment():
            return False
        atomic_write_json(path, payload)

    Override during tests that need to exercise the write
    path:
        monkeypatch.setenv("SHOPAI_FORCE_PRODUCTION_WRITES", "1")
        # OR
        with patch("core.agi.persistence.is_test_environment",
                   return_value=False):
            ...
    """
    if os.environ.get(
        "SHOPAI_FORCE_PRODUCTION_WRITES", "",
    ).lower() in ("1", "true", "yes"):
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def atomic_write_json(
    path: Path | str,
    data: Any,
    *,
    indent: int | None = 2,
) -> bool:
    """Atomically write JSON-serialisable data to path.

    Uses tempfile.mkstemp + os.replace so a crash mid-write
    cannot leave a half-written file. Creates the parent
    directory if missing.

    Returns True on success, False on OSError. Never raises:
    persistence is best-effort by design (a write failure
    shouldn't propagate up into the cycle controller).

    Note: caller is responsible for the Pattern J guard.
    This function WILL write under pytest if called.
    """
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent) or ".",
        )
        os.close(fd)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, default=str)
        os.replace(tmp, str(target))
        return True
    except (OSError, ValueError) as exc:
        # ValueError covers Windows-specific cases like NUL
        # characters in the path; OSError covers permission
        # / disk-full / parent-doesn't-exist.
        logger.debug(
            "atomic_write_json(%s) raised: %s",
            target, exc,
        )
        return False


def atomic_write_text(
    path: Path | str,
    body: str,
) -> bool:
    """Atomically write text content to path. Same
    invariants as atomic_write_json but for non-JSON
    formats (e.g. .env files, plain logs).

    Returns True on success, False on OSError / ValueError.
    Never raises.
    """
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent) or ".",
        )
        os.close(fd)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, str(target))
        return True
    except (OSError, ValueError) as exc:
        logger.debug(
            "atomic_write_text(%s) raised: %s",
            target, exc,
        )
        return False


def load_json_list(
    path: Path | str,
) -> list[dict[str, Any]]:
    """Tolerant JSON-list loader.

    Returns [] when:
      - file does not exist
      - file is unreadable (OSError)
      - file contains malformed JSON
      - file's JSON top-level isn't a list

    Filters non-dict entries from the list (defensive
    against schema drift).
    """
    target = Path(path)
    if not target.exists():
        return []
    try:
        with target.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [
                d for d in data if isinstance(d, dict)
            ]
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "load_json_list(%s) raised: %s",
            target, exc,
        )
    return []


def load_json_dict(
    path: Path | str,
) -> dict[str, Any]:
    """Tolerant JSON-dict loader.

    Returns {} on any error / non-dict top-level.
    """
    target = Path(path)
    if not target.exists():
        return {}
    try:
        with target.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "load_json_dict(%s) raised: %s",
            target, exc,
        )
    return {}
