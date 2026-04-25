"""Data housekeeper — periodic maintenance of brain SQLite stores.

Every sprint added another SQLite file under ``data/`` — at this
point 15+ stores (memory, goals, skills, world_model, reward,
hypotheses, surprise, epistemic, self_improvement, ontology,
habits, policy_library, benchmarks, trust, subgoals, …).

None of them got maintenance. Over time:

  • file sizes bloat as autoincrement ids outpace vacuums.
  • old rows below relevance thresholds linger.
  • WAL files hang around.
  • checkpoint archives accumulate without rotation.

DataHousekeeper runs a weekly sweep:

  • VACUUM every registered DB.
  • Prune rows older than per-table retention caps with low score.
  • Rotate checkpoint archives beyond ``keep_checkpoints`` count.
  • Report disk reclaimed + row counts before/after.

Every action is deterministic and idempotent. Never touches
production secrets. Runs safely even when a DB is missing.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("memory.housekeeper")


_DEFAULT_TARGETS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("data/memory_intelligence.db", {
        "table": "memories",
        "keep_days": 180,
        "score_floor": 1.5,
    }),
    ("data/world_model.db", {"table": "cells"}),
    ("data/reward_model.db", {"table": "feature_counts"}),
    ("data/hypotheses.db", {"table": "hypotheses"}),
    ("data/surprise.db", {"table": "surprises"}),
    ("data/epistemic.db", {"table": "cells"}),
    ("data/self_improvement.db", {"table": "proposals"}),
    ("data/ontology.db", {"table": "triples"}),
    ("data/habits.db", {"table": "habits"}),
    ("data/policy_library.db", {"table": "policies"}),
    ("data/benchmarks.db", {"table": "runs"}),
    ("data/trust.db", {"table": "sources"}),
    ("data/subgoals.db", {"table": "subgoals"}),
    ("data/goal_agenda.db", {"table": "goals"}),
    ("data/skills.db", {"table": "skills"}),
    ("data/preference_elicitation.db", {"table": "queries"}),
)


@dataclass
class TableReport:
    db: str
    table: str
    rows_before: int
    rows_after: int
    bytes_before: int
    bytes_after: int
    error: str = ""

    @property
    def rows_pruned(self) -> int:
        return max(0, self.rows_before - self.rows_after)

    @property
    def bytes_reclaimed(self) -> int:
        return max(0, self.bytes_before - self.bytes_after)

    def as_dict(self) -> dict[str, Any]:
        return {
            "db": self.db,
            "table": self.table,
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "rows_pruned": self.rows_pruned,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "bytes_reclaimed": self.bytes_reclaimed,
            "error": self.error,
        }


@dataclass
class HousekeepingReport:
    started_at: float
    elapsed_ms: float
    tables: list[TableReport] = field(default_factory=list)
    checkpoints_pruned: int = 0
    total_bytes_reclaimed: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "tables": [t.as_dict() for t in self.tables],
            "checkpoints_pruned": self.checkpoints_pruned,
            "total_bytes_reclaimed": self.total_bytes_reclaimed,
        }


# ── Housekeeper ─────────────────────────────────────────────

class DataHousekeeper:
    def __init__(
        self,
        targets: Iterable[tuple[str, dict[str, Any]]] | None = None,
        checkpoint_dir: Path | str = "data/checkpoints",
        keep_checkpoints: int = 10,
    ) -> None:
        self._targets = list(targets) if targets is not None \
            else list(_DEFAULT_TARGETS)
        self._checkpoint_dir = Path(checkpoint_dir)
        self._keep_checkpoints = int(keep_checkpoints)

    # ── Orchestration ──────────────────────────────────────

    def run(self) -> HousekeepingReport:
        started = time.time()
        start = time.monotonic()
        report = HousekeepingReport(started_at=started, elapsed_ms=0.0)

        for rel_path, opts in self._targets:
            tr = self._process_table(rel_path, opts)
            report.tables.append(tr)
            report.total_bytes_reclaimed += tr.bytes_reclaimed

        report.checkpoints_pruned = self._prune_checkpoints()
        report.elapsed_ms = (time.monotonic() - start) * 1000
        return report

    # ── Per-table processing ───────────────────────────────

    def _process_table(
        self, rel_path: str, opts: dict[str, Any],
    ) -> TableReport:
        path = Path(rel_path)
        table = opts.get("table", "")
        if not path.exists():
            return TableReport(
                db=str(path), table=table,
                rows_before=0, rows_after=0,
                bytes_before=0, bytes_after=0,
                error="missing",
            )
        bytes_before = path.stat().st_size
        rows_before = 0
        rows_after = 0
        err = ""
        try:
            conn = sqlite3.connect(str(path))
            try:
                rows_before = _count(conn, table)
                self._prune_table(conn, table, opts)
                rows_after = _count(conn, table)
                conn.execute("VACUUM")
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            err = f"{type(exc).__name__}: {exc}"
            logger.warning("housekeep %s: %s", rel_path, exc)
        bytes_after = path.stat().st_size if path.exists() else 0
        return TableReport(
            db=str(path), table=table,
            rows_before=rows_before, rows_after=rows_after,
            bytes_before=bytes_before, bytes_after=bytes_after,
            error=err,
        )

    @staticmethod
    def _prune_table(
        conn: sqlite3.Connection, table: str, opts: dict[str, Any],
    ) -> int:
        if not table:
            return 0
        keep_days = opts.get("keep_days")
        score_floor = opts.get("score_floor")
        if keep_days is None and score_floor is None:
            return 0
        cutoff = time.time() - float(keep_days) * 86_400 \
            if keep_days else None
        columns = _columns(conn, table)
        where: list[str] = []
        params: list[Any] = []
        # Pick the best available timestamp column.
        ts_col = next(
            (c for c in ("timestamp", "created_at", "last_seen",
                          "last_update")
              if c in columns), None,
        )
        if cutoff is not None and ts_col:
            where.append(f"{ts_col} < ?")
            params.append(cutoff)
        if score_floor is not None and "score" in columns:
            where.append("score < ?")
            params.append(float(score_floor))
        if not where:
            return 0
        query = f"DELETE FROM {table} WHERE " + " AND ".join(where)
        try:
            cur = conn.execute(query, tuple(params))
            conn.commit()
            return cur.rowcount or 0
        except sqlite3.Error as exc:
            logger.debug("prune failed on %s: %s", table, exc)
            return 0

    # ── Checkpoints ────────────────────────────────────────

    def _prune_checkpoints(self) -> int:
        if not self._checkpoint_dir.exists():
            return 0
        archives = sorted(
            self._checkpoint_dir.glob("*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        pruned = 0
        for arch in archives[self._keep_checkpoints:]:
            try:
                arch.unlink()
                meta = arch.with_suffix("").with_suffix(".json")
                if meta.exists():
                    meta.unlink()
                pruned += 1
            except OSError as exc:
                logger.debug("could not prune %s: %s", arch, exc)
        return pruned


# ── Helpers ────────────────────────────────────────────────

def _count(conn: sqlite3.Connection, table: str) -> int:
    if not table:
        return 0
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
        return {r[1] for r in rows}
    except sqlite3.Error:
        return set()
