"""Operator housekeeping: prune old events from every
autonomous-loop history file.

Long-running deployments accumulate history events. The
1000-event cap on each file prevents unbounded growth but
operators may want stricter retention -- e.g., "keep only
the last 90 days" -- both for disk economy and for keeping
trend analyses focused on relevant data.

This module provides the prune operation across every
known history file in one call.

Pattern J: writes short-circuit under pytest. Tests that
need to exercise the prune patch ``_is_test_environment``
to ``False``.

Public surface
--------------
- ``prune_all(older_than_days, dry_run)`` -> dict.
- ``audit_history_age()`` -> per-file age stats.
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


# (label, env_var, default_path, shape)
_HISTORY_FILES: list[tuple[str, str, str, str]] = [
    (
        "cycle_history",
        "SHOPAI_CYCLE_HISTORY_PATH",
        "data/cycle_history.json",
        "list",
    ),
    (
        "cycle_alert_history",
        "SHOPAI_CYCLE_ALERT_HISTORY_PATH",
        "data/cycle_alert_history.json",
        "list",
    ),
    (
        "cycle_pause_history",
        "SHOPAI_CYCLE_PAUSE_HISTORY_PATH",
        "data/cycle_pause_history.json",
        "list",
    ),
    (
        "auto_demote_history",
        "SHOPAI_AUTO_DEMOTE_HISTORY_PATH",
        "data/auto_demote_history.json",
        "list",
    ),
    (
        "auto_promote_history",
        "SHOPAI_AUTO_PROMOTE_HISTORY_PATH",
        "data/auto_promote_history.json",
        "list",
    ),
    (
        "auto_relax_history",
        "SHOPAI_AUTO_RELAX_HISTORY_PATH",
        "data/auto_relax_history.json",
        "list",
    ),
    (
        "transfer_history",
        "SHOPAI_TRANSFER_HISTORY_PATH",
        "data/transfer_history.json",
        "list",
    ),
    (
        "cycle_revenue_history",
        "SHOPAI_CYCLE_REVENUE_HISTORY_PATH",
        "data/cycle_revenue_history.json",
        "list",
    ),
    (
        "plan_history",
        "SHOPAI_PLAN_HISTORY_PATH",
        "data/plan_history.json",
        "list",
    ),
    (
        "engine_health_history",
        "SHOPAI_ENGINE_HEALTH_HISTORY_PATH",
        "data/engine_health_history.json",
        "list",
    ),
    (
        "health_score_history",
        "SHOPAI_HEALTH_SCORE_HISTORY_PATH",
        "data/health_score_history.json",
        "list",
    ),
    (
        "alert_history",
        "SHOPAI_ALERT_HISTORY_PATH",
        "data/alert_history.json",
        "list",
    ),
]


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


# W962-74: map prune labels to the owning module's lock so the
# prune read+write happens INSIDE that module's _LOCK / _HISTORY_LOCK.
# Pre-fix, prune_all read each file outside the owning module's
# lock and wrote via os.replace -- a recorder could append a new
# event between the read and the write, and the prune's
# kept-list (missing the just-appended event) would wipe it.
# These imports are deferred (called inside _label_lock) so this
# module can still load without circular-import drama.
def _label_lock(label: str):
    """Return a context manager that holds the owning module's
    lock for the duration of the prune of ``label``. Falls back
    to a no-op context manager when the lock can't be resolved
    (e.g. a label without a corresponding module yet)."""
    import contextlib
    try:
        if label == "cycle_history":
            from core.autonomous import cycle_history as _m
            return _m._LOCK
        if label == "cycle_alert_history":
            from core.autonomous import cycle_alert_history as _m
            return _m._LOCK
        if label == "cycle_pause_history":
            from core.autonomous import cycle_pause as _m
            return _m._LOCK
        if label == "auto_demote_history":
            from core.capability_planner import auto_demote_history as _m
            return _m._LOCK
        if label == "auto_promote_history":
            from core.capability_planner import auto_promote_history as _m
            return _m._LOCK
        if label == "auto_relax_history":
            from core.autonomous import auto_relax_history as _m
            return _m._LOCK
        if label == "transfer_history":
            from core.autonomous import transfer_history as _m
            return _m._LOCK
        if label == "cycle_revenue_history":
            from core.autonomous import cycle_revenue_history as _m
            return _m._LOCK
        if label == "plan_history":
            from core.capability_planner import plan_history as _m
            return _m._HISTORY_LOCK
        if label == "engine_health_history":
            from core.approval import engine_health_history as _m
            return _m._LOCK
        if label == "health_score_history":
            from core.autonomous import health_score_history as _m
            return _m._LOCK
        if label == "alert_history":
            from core.approval import alert_history as _m
            return _m._LOCK
    except (ImportError, AttributeError) as exc:
        logger.debug(
            "history_cleanup: lock import for %s failed (%s)",
            label, exc,
        )
    # Best-effort no-op when the owning module's lock isn't
    # discoverable.
    return contextlib.nullcontext()


def _resolve_path(env_var: str, default: str) -> Path:
    return Path(os.environ.get(env_var, default))


def _atomic_write_list(
    path: Path, entries: list[dict[str, Any]],
) -> None:
    try:
        path.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "history_cleanup: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".history_cleanup_",
            suffix=".json",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(
                fd, "w", encoding="utf-8",
            ) as f:
                json.dump(
                    entries, f, indent=2, default=str,
                )
            os.replace(temp_path_str, path)
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
            "history_cleanup: write failed (%s)", exc,
        )


def prune_all(
    *,
    older_than_days: int,
    dry_run: bool = True,
    now: float | None = None,
) -> dict[str, Any]:
    """Walk every history file. For each, count + optionally
    remove events older than ``older_than_days``.

    Args:
        older_than_days: Events with ``recorded_at`` older
            than (now - days*86400) are eligible to prune.
        dry_run: When True (default), reports counts
            without writing.
        now: Override timestamp for testing.

    Returns:
        {
          "older_than_days": int,
          "dry_run": bool,
          "files": [
            {label, path, total, kept, pruned,
             pruned_size_bytes, error},
            ...
          ],
          "total_pruned": int,
        }
    """
    now = now if now is not None else time.time()
    cutoff = now - max(0, int(older_than_days)) * 86400.0

    out: dict[str, Any] = {
        "older_than_days": older_than_days,
        "dry_run": dry_run,
        "files": [],
        "total_pruned": 0,
    }

    apply_writes = (
        not dry_run and not _is_test_environment()
    )

    for label, env, default_path, shape in _HISTORY_FILES:
        path = _resolve_path(env, default_path)
        entry: dict[str, Any] = {
            "label": label,
            "path": str(path),
            "total": 0,
            "kept": 0,
            "pruned": 0,
            "pruned_size_bytes": 0,
            "error": None,
        }
        try:
            if not path.exists():
                # No file = nothing to prune; still
                # listed so the audit shows all known
                # paths.
                out["files"].append(entry)
                continue
            # W962-74: read + write under the owning module's
            # lock. Pre-fix, a concurrent recorder thread could
            # append a new event after our read but before our
            # os.replace, silently wiping the just-recorded
            # event.
            with _label_lock(label):
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    entry["error"] = (
                        f"unexpected shape "
                        f"{type(data).__name__}"
                    )
                    out["files"].append(entry)
                    continue
                entry["total"] = len(data)
                kept: list[dict[str, Any]] = []
                pruned_count = 0
                for row in data:
                    if not isinstance(row, dict):
                        kept.append(row)
                        continue
                    ts = float(
                        row.get("recorded_at", 0) or 0,
                    )
                    if ts < cutoff:
                        pruned_count += 1
                    else:
                        kept.append(row)
                entry["kept"] = len(kept)
                entry["pruned"] = pruned_count
                # Estimate the pruned byte size as
                # proportional to row count -- not exact, but
                # gives the operator a sense of scale.
                try:
                    total_size = path.stat().st_size
                    entry["pruned_size_bytes"] = int(
                        total_size * pruned_count
                        / max(1, entry["total"]),
                    )
                except OSError as exc:
                    logger.debug(
                        "history_cleanup: stat failed (%s)", exc,
                    )

                if pruned_count > 0 and apply_writes:
                    _atomic_write_list(path, kept)
                out["total_pruned"] += pruned_count
        except json.JSONDecodeError as exc:
            entry["error"] = f"json_decode: {exc}"
        except OSError as exc:
            entry["error"] = f"os_error: {exc}"

        out["files"].append(entry)
    return out
