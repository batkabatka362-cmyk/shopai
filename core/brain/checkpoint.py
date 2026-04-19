"""Brain checkpoint — versioned snapshots of brain state.

An AGI-adjacent brain is a mess of SQLite tables (goals, skills,
hypotheses, world_model, reward_model, epistemic, self_improvement,
ontology, …). A single bad cycle can poison multiple tables at
once: a miscoded rule promotes, a mis-fired learning loop shifts
weights, and by the time the owner notices the damage is spread.

BrainCheckpointer takes a *snapshot* of the brain's critical
stores to a single versioned tarball, lets the owner restore from
any snapshot, and keeps an auto-rotating bounded history.

Scope (covered by default):

  • data/memory_intelligence.db
  • data/goal_agenda.db
  • data/skills.db
  • data/world_model.db
  • data/reward_model.db
  • data/hypotheses.db
  • data/surprise.db
  • data/epistemic.db
  • data/self_improvement.db
  • data/ontology.db
  • data/compound_tools.json
  • data/kb.sqlite (if present)

snapshot(label, note?) → Snapshot handle
list_snapshots() → list of Snapshot handles
restore(snapshot_id) → returns the files restored
prune(keep_last) → bounded rotation so old snapshots don't
    consume unbounded disk

Snapshots are stored in ``data/checkpoints/`` as
``<unix>-<label>.tar.gz`` plus a metadata JSON sidecar so the
dashboard can show a timeline.

Safety:

  • Restore *refuses* to overwrite a store that was modified after
    the checkpoint was taken unless ``force=True`` — prevents
    silent rollback of fresh observations.
  • Restore writes a pre-restore backup first, so a bad rollback
    is itself reversible.
  • Never touches ``.env``, credentials, or anything outside
    ``data/``.

Pure stdlib (tarfile + json + pathlib). No LLM.
"""
from __future__ import annotations

import json
import shutil
import tarfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_ROOT = Path("data")
_CHECKPOINT_DIR = _ROOT / "checkpoints"

# Files included in a default snapshot. Paths are relative to _ROOT.
DEFAULT_TARGETS: tuple[str, ...] = (
    "memory_intelligence.db",
    "goal_agenda.db",
    "skills.db",
    "world_model.db",
    "reward_model.db",
    "hypotheses.db",
    "surprise.db",
    "epistemic.db",
    "self_improvement.db",
    "ontology.db",
    "compound_tools.json",
    "kb.sqlite",
)


@dataclass
class Snapshot:
    id: str
    created_at: float
    label: str
    note: str
    archive_path: Path
    targets: list[str] = field(default_factory=list)
    meta_path: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "label": self.label,
            "note": self.note,
            "archive_path": str(self.archive_path),
            "targets": self.targets,
        }


@dataclass
class RestoreResult:
    snapshot_id: str
    restored: list[str]
    skipped: list[str]
    backup_path: Path | None
    forced: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "restored": self.restored,
            "skipped": self.skipped,
            "backup_path": (str(self.backup_path)
                             if self.backup_path else None),
            "forced": self.forced,
        }


# ── Checkpointer ────────────────────────────────────────────

class BrainCheckpointer:
    def __init__(
        self,
        root: Path | str | None = None,
        checkpoint_dir: Path | str | None = None,
        targets: Iterable[str] | None = None,
    ) -> None:
        self._root = Path(root) if root else _ROOT
        self._dir = (Path(checkpoint_dir) if checkpoint_dir
                      else self._root / "checkpoints")
        self._targets = list(targets) if targets else list(DEFAULT_TARGETS)
        self._lock = threading.RLock()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._root.mkdir(parents=True, exist_ok=True)

    # ── Create ──────────────────────────────────────────────

    def snapshot(
        self, label: str = "manual", note: str = "",
    ) -> Snapshot:
        ts = time.time()
        safe = "".join(c if c.isalnum() or c in "-_" else "_"
                        for c in label)
        # Include fractional seconds so rapid successive snapshots
        # don't collide on id.
        sid = f"{ts:.3f}-{safe or 'snapshot'}".replace(".", "_")
        archive = self._dir / f"{sid}.tar.gz"
        meta = self._dir / f"{sid}.json"
        included: list[str] = []
        with self._lock:
            with tarfile.open(archive, "w:gz") as tar:
                for rel in self._targets:
                    abs_path = self._root / rel
                    if abs_path.exists() and abs_path.is_file():
                        tar.add(abs_path, arcname=rel)
                        included.append(rel)
            payload = {
                "id": sid,
                "created_at": time.time(),
                "label": label,
                "note": note,
                "targets": included,
            }
            meta.write_text(json.dumps(payload, indent=2, default=str),
                             encoding="utf-8")
        return Snapshot(
            id=sid,
            created_at=payload["created_at"],
            label=label,
            note=note,
            archive_path=archive,
            targets=included,
            meta_path=meta,
        )

    # ── List ────────────────────────────────────────────────

    def list_snapshots(self) -> list[Snapshot]:
        out: list[Snapshot] = []
        for meta in sorted(self._dir.glob("*.json")):
            try:
                payload = json.loads(meta.read_text())
            except (json.JSONDecodeError, ValueError):
                continue
            archive = self._dir / f"{payload['id']}.tar.gz"
            if not archive.exists():
                continue
            out.append(Snapshot(
                id=payload["id"],
                created_at=float(payload.get("created_at", 0)),
                label=payload.get("label", ""),
                note=payload.get("note", ""),
                archive_path=archive,
                targets=list(payload.get("targets", [])),
                meta_path=meta,
            ))
        # Newest first
        out.sort(key=lambda s: -s.created_at)
        return out

    def get(self, snapshot_id: str) -> Snapshot | None:
        for s in self.list_snapshots():
            if s.id == snapshot_id:
                return s
        return None

    # ── Restore ────────────────────────────────────────────

    def restore(
        self, snapshot_id: str, force: bool = False,
    ) -> RestoreResult:
        snap = self.get(snapshot_id)
        if snap is None:
            raise KeyError(f"unknown snapshot {snapshot_id!r}")
        restored: list[str] = []
        skipped: list[str] = []
        backup: Path | None = None
        with self._lock:
            # 1. Freshness check: skip files modified after the snapshot
            safe_to_restore: list[str] = []
            for rel in snap.targets:
                live = self._root / rel
                if live.exists() and live.stat().st_mtime > snap.created_at:
                    if force:
                        safe_to_restore.append(rel)
                    else:
                        skipped.append(rel)
                        continue
                else:
                    safe_to_restore.append(rel)
            # 2. Pre-restore backup of current state (only if we're
            #    actually about to restore something).
            if safe_to_restore:
                backup = self.snapshot(
                    label=f"pre_restore_of_{snap.id}",
                    note=f"auto backup before restoring {snap.id}",
                ).archive_path
            # 3. Extract only the safe_to_restore files
            with tarfile.open(snap.archive_path, "r:gz") as tar:
                for rel in safe_to_restore:
                    try:
                        tar.extract(rel, path=self._root)
                        restored.append(rel)
                    except KeyError:
                        skipped.append(rel)
        return RestoreResult(
            snapshot_id=snap.id,
            restored=restored,
            skipped=skipped,
            backup_path=backup,
            forced=force,
        )

    # ── Rotation ───────────────────────────────────────────

    def prune(self, keep_last: int = 10) -> int:
        snaps = self.list_snapshots()
        to_delete = snaps[keep_last:]
        with self._lock:
            for s in to_delete:
                try:
                    s.archive_path.unlink(missing_ok=True)
                    if s.meta_path:
                        s.meta_path.unlink(missing_ok=True)
                except OSError:
                    continue
        return len(to_delete)

    # ── Introspection ─────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        snaps = self.list_snapshots()
        total_bytes = 0
        for s in snaps:
            try:
                total_bytes += s.archive_path.stat().st_size
            except OSError:
                continue
        return {
            "count": len(snaps),
            "total_bytes": total_bytes,
            "newest_id": snaps[0].id if snaps else None,
            "oldest_id": snaps[-1].id if snaps else None,
        }


# ── Singleton ────────────────────────────────────────────────

_CP_LOCK = threading.Lock()
_CP: BrainCheckpointer | None = None


def checkpointer() -> BrainCheckpointer:
    global _CP
    if _CP is None:
        with _CP_LOCK:
            if _CP is None:
                _CP = BrainCheckpointer()
    return _CP
