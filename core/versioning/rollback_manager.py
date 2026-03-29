"""RollbackManager — safe engine rollback with state preservation."""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("versioning.rollback")


class RollbackManager:
    """Manages safe rollbacks with state snapshots. Never deletes data."""

    def __init__(self) -> None:
        self._snapshots: dict[str, list[dict[str, Any]]] = {}

    def snapshot(self, component: str, state: dict[str, Any], label: str = "") -> str:
        """Take a snapshot of component state before changes."""
        snap_id = f"snap_{int(time.time() * 1000)}"
        entry = {
            "snap_id": snap_id,
            "component": component,
            "state": copy.deepcopy(state),
            "label": label,
            "timestamp": time.time(),
        }
        self._snapshots.setdefault(component, []).append(entry)
        if len(self._snapshots[component]) > 50:
            self._snapshots[component] = self._snapshots[component][-50:]
        return snap_id

    def rollback(self, component: str, snap_id: str | None = None) -> dict[str, Any] | None:
        """Rollback to a snapshot. Returns the state, does NOT apply it."""
        snaps = self._snapshots.get(component, [])
        if not snaps:
            return None

        if snap_id:
            target = next((s for s in snaps if s["snap_id"] == snap_id), None)
        else:
            target = snaps[-1]  # Latest

        if target:
            logger.info("Rollback state retrieved for %s (snap=%s)", component, target["snap_id"])
            return copy.deepcopy(target["state"])
        return None

    def list_snapshots(self, component: str) -> list[dict[str, str]]:
        return [
            {"snap_id": s["snap_id"], "label": s["label"], "timestamp": s["timestamp"]}
            for s in self._snapshots.get(component, [])
        ]

    def get_diff(self, component: str, snap_id_a: str, snap_id_b: str) -> dict[str, Any]:
        """Compare two snapshots."""
        snaps = {s["snap_id"]: s["state"] for s in self._snapshots.get(component, [])}
        a = snaps.get(snap_id_a, {})
        b = snaps.get(snap_id_b, {})

        added = {k: b[k] for k in b if k not in a}
        removed = {k: a[k] for k in a if k not in b}
        changed = {k: {"old": a[k], "new": b[k]} for k in a if k in b and a[k] != b[k]}

        return {"added": added, "removed": removed, "changed": changed}
