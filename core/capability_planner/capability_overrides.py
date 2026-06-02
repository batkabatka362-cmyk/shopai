"""Operator-declared capability overrides.

The automatic learning layer (plan_history + reliability
leaderboard + degradation detector + quarantine) handles
data-driven signal. This module is the OPERATOR-DRIVEN
counterpart: explicit "this capability is good" / "this
capability is bad" declarations that the planner respects
without waiting for history to accumulate.

Two override types
------------------
- **Promoted**: explicitly recommend. Planner boosts these
  even when the substring matcher misses them. Useful when
  the operator knows a capability fits the niche but the
  registry's keywords don't surface it for their query
  phrasing.
- **Demoted**: explicitly exclude. Planner refuses to seed
  with these. Useful for known-broken-pending-fix
  capabilities without needing to enter the full
  alert_quarantine flow.

Both are persistent (data/capability_overrides.json) and
operator-owned (the autonomous loop never modifies them).

Public surface
--------------
- ``promote(name, reason="")`` -- add a capability to the
  promote list.
- ``demote(name, reason="")`` -- add to the demote list.
- ``clear(name)`` -- remove from both lists.
- ``load_overrides()`` -> CapabilityOverrides instance.
- ``CapabilityOverrides.promoted_names()`` -> set of names.
- ``CapabilityOverrides.demoted_names()`` -> set of names.

The persistence pattern mirrors
``core.approval.alert_history``: single JSON file, atomic
write via temp + rename, fail-open semantics. Pattern J
test-environment guard short-circuits writes (reads still
work).
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

# W962-43: spanning lock for concurrent promote / demote / clear.
# Real exposure: operator + automation flipping the same name.
_LOCK = threading.RLock()


_OVERRIDES_PATH = Path(
    os.environ.get(
        "SHOPAI_CAPABILITY_OVERRIDES_PATH",
        "data/capability_overrides.json",
    )
)


@dataclass
class CapabilityOverride:
    """One operator-declared override.

    ``kind`` is ``"promote"`` or ``"demote"``.
    ``reason`` is a free-form note (operator's explanation).
    ``recorded_at`` is the unix timestamp the override was
    added (for "how stale is this?" auditing).
    """

    name: str
    kind: str  # "promote" | "demote"
    reason: str = ""
    recorded_at: float = 0.0


@dataclass
class CapabilityOverrides:
    """In-memory view of the operator override file.
    Returned by ``load_overrides()``."""

    entries: list[CapabilityOverride] = field(
        default_factory=list,
    )

    def promoted_names(self) -> set[str]:
        return {
            e.name for e in self.entries
            if e.kind == "promote"
        }

    def demoted_names(self) -> set[str]:
        return {
            e.name for e in self.entries
            if e.kind == "demote"
        }

    def is_promoted(self, name: str) -> bool:
        return name in self.promoted_names()

    def is_demoted(self, name: str) -> bool:
        return name in self.demoted_names()

    def get(
        self, name: str,
    ) -> CapabilityOverride | None:
        for e in self.entries:
            if e.name == name:
                return e
        return None


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> list[dict[str, Any]]:
    """Fail-open read. Missing / corrupt -> empty list."""
    try:
        if not _OVERRIDES_PATH.exists():
            return []
        with _OVERRIDES_PATH.open(
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
            "capability_overrides: load failed (%s) "
            "-- returning empty", exc,
        )
        return []


def _atomic_write(entries: list[dict[str, Any]]) -> None:
    """Atomic temp + rename. Fails open on any I/O error."""
    try:
        _OVERRIDES_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "capability_overrides: mkdir failed (%s)",
            exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".cap_overrides_",
            suffix=".json",
            dir=str(_OVERRIDES_PATH.parent),
        )
        try:
            with os.fdopen(
                fd, "w", encoding="utf-8",
            ) as f:
                json.dump(
                    entries, f, indent=2, default=str,
                )
            os.replace(temp_path_str, _OVERRIDES_PATH)
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
            "capability_overrides: write failed (%s)",
            exc,
        )


def load_overrides() -> CapabilityOverrides:
    """Read the on-disk overrides file. Always returns a
    valid CapabilityOverrides instance (possibly empty)."""
    raw = _load_raw()
    entries = []
    for r in raw:
        name = str(r.get("name", "") or "")
        kind = str(r.get("kind", "") or "")
        if not name or kind not in ("promote", "demote"):
            continue
        entries.append(CapabilityOverride(
            name=name,
            kind=kind,
            reason=str(r.get("reason", "") or ""),
            recorded_at=float(
                r.get("recorded_at", 0) or 0,
            ),
        ))
    return CapabilityOverrides(entries=entries)


def _set_override(
    name: str, kind: str, reason: str,
) -> bool:
    """Persist a new or updated override. Returns True on
    write success, False on test-env guard or I/O error.

    Idempotent: if ``name`` already exists with the same
    kind, just update its reason + recorded_at. If with a
    DIFFERENT kind, REPLACES (operator flipping their
    mind).
    """
    if not name or kind not in ("promote", "demote"):
        return False
    if _is_test_environment():
        return False
    # W962-43: span load+strip+append+write.
    with _LOCK:
        entries = _load_raw()
        # Strip any existing entry for this name (both kinds);
        # we add the new one at the end.
        entries = [
            e for e in entries
            if str(e.get("name", "")) != name
        ]
        entries.append({
            "name": name,
            "kind": kind,
            "reason": reason,
            "recorded_at": time.time(),
        })
        _atomic_write(entries)
    return True


def promote(name: str, reason: str = "") -> bool:
    """Add ``name`` to the promote list."""
    return _set_override(name, "promote", reason)


def demote(name: str, reason: str = "") -> bool:
    """Add ``name`` to the demote list."""
    return _set_override(name, "demote", reason)


def clear(name: str) -> bool:
    """Remove ``name`` from BOTH lists. Returns True when
    a row was removed, False when nothing matched or
    test-env / I/O error."""
    if not name or _is_test_environment():
        return False
    # W962-43: span load+strip+write.
    with _LOCK:
        entries = _load_raw()
        before = len(entries)
        entries = [
            e for e in entries
            if str(e.get("name", "")) != name
        ]
        if len(entries) == before:
            return False
        _atomic_write(entries)
    return True


def clear_all() -> None:
    """Operator escape hatch -- wipe every override."""
    if _is_test_environment():
        return
    if _OVERRIDES_PATH.exists():
        try:
            _OVERRIDES_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "capability_overrides: unlink raised: %s",
                exc,
            )


def _reset_for_tests(path: Path | None = None) -> None:
    """Test-only hook to override the persistence path."""
    global _OVERRIDES_PATH
    if path is not None:
        _OVERRIDES_PATH = path
