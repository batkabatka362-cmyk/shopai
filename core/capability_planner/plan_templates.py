"""Plan templates -- named, savable goal recipes.

Operators run the same goals over and over: "make this store
launchable", "investigate degradation", "daily routine".
Typing the goal each time is repetitive AND the wording
matters for the planner's substring match.

This module is the persistence layer for named plan
templates. Operators save a goal once, run it by name
thereafter.

Public surface
--------------
- ``PlanTemplate`` dataclass.
- ``save_template(name, goal, description="")`` -- write.
- ``load_template(name)`` -> ``PlanTemplate | None``.
- ``list_templates()`` -> list[PlanTemplate].
- ``delete_template(name)`` -> bool.

Pattern J + atomic + fail-open + dict storage (keyed by
name). Same shape as the other persistent modules in this
package.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# W962-48: spanning lock for concurrent save+delete.
_LOCK = threading.RLock()


_TEMPLATES_PATH = Path(
    os.environ.get(
        "SHOPAI_PLAN_TEMPLATES_PATH",
        "data/plan_templates.json",
    )
)

_MAX_TEMPLATES = 100  # Bounded; operators don't need 1000s


@dataclass
class PlanTemplate:
    name: str
    goal: str
    description: str = ""
    created_at: float = 0.0


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> dict[str, Any]:
    try:
        if not _TEMPLATES_PATH.exists():
            return {}
        with _TEMPLATES_PATH.open(
            "r", encoding="utf-8",
        ) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "plan_templates: load failed (%s)", exc,
        )
        return {}


def _atomic_write(data: dict[str, Any]) -> None:
    try:
        _TEMPLATES_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "plan_templates: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".plan_templates_",
            suffix=".json",
            dir=str(_TEMPLATES_PATH.parent),
        )
        try:
            with os.fdopen(
                fd, "w", encoding="utf-8",
            ) as f:
                json.dump(
                    data, f, indent=2, default=str,
                )
            os.replace(temp_path_str, _TEMPLATES_PATH)
        except Exception:
            try:
                os.unlink(temp_path_str)
            except OSError as cleanup_exc:
                logger.debug(
                    "temp cleanup failed: %s", cleanup_exc,
                )
            raise
    except OSError as exc:
        logger.debug(
            "plan_templates: write failed (%s)", exc,
        )


def save_template(
    name: str,
    goal: str,
    *,
    description: str = "",
) -> bool:
    """Save a template by name. Overwrites if name exists.
    Returns True on write, False on test-env / invalid /
    I/O error / cap exceeded."""
    if not name or not goal:
        return False
    if _is_test_environment():
        return False
    # W962-48: lock-spanning load+modify+save.
    with _LOCK:
        data = _load_raw()
        if name not in data and len(data) >= _MAX_TEMPLATES:
            logger.debug(
                "plan_templates: cap %d reached, refusing",
                _MAX_TEMPLATES,
            )
            return False
        data[name] = {
            "name": name,
            "goal": goal,
            "description": description or "",
            "created_at": (
                data.get(name, {}).get("created_at")
                or time.time()
            ),
        }
        _atomic_write(data)
    return True


def load_template(name: str) -> PlanTemplate | None:
    """Read a template by name. None if missing."""
    if not name:
        return None
    data = _load_raw()
    row = data.get(name)
    if not isinstance(row, dict):
        return None
    return PlanTemplate(
        name=str(row.get("name", name)),
        goal=str(row.get("goal", "") or ""),
        description=str(row.get("description", "") or ""),
        created_at=float(row.get("created_at", 0) or 0),
    )


def list_templates() -> list[PlanTemplate]:
    """Return all templates, sorted by name."""
    data = _load_raw()
    out: list[PlanTemplate] = []
    for name in sorted(data.keys()):
        row = data[name]
        if not isinstance(row, dict):
            continue
        out.append(PlanTemplate(
            name=str(row.get("name", name)),
            goal=str(row.get("goal", "") or ""),
            description=str(row.get("description", "") or ""),
            created_at=float(
                row.get("created_at", 0) or 0,
            ),
        ))
    return out


def delete_template(name: str) -> bool:
    """Remove a template. Returns True when a row was
    removed, False on missing / test-env / I/O error."""
    if not name:
        return False
    if _is_test_environment():
        return False
    # W962-48: lock-spanning load+modify+save.
    with _LOCK:
        data = _load_raw()
        if name not in data:
            return False
        del data[name]
        _atomic_write(data)
    return True


def clear() -> None:
    if _is_test_environment():
        return
    if _TEMPLATES_PATH.exists():
        try:
            _TEMPLATES_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "plan_templates: unlink raised: %s", exc,
            )


def _reset_for_tests(path: Path | None = None) -> None:
    global _TEMPLATES_PATH
    if path is not None:
        _TEMPLATES_PATH = path
