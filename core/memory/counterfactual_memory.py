"""Counterfactual memory — 'what if we'd done X' stored as first-class data.

counterfactual_simulator rolls out hypothetical action sequences for
decision-time reasoning. Afterward, those rollouts are thrown away.
This module keeps them: every *what-if* we considered becomes a
persistent record the brain can retrieve and compare against actual
outcomes to learn from unchosen paths.

Data model:

    Counterfactual(
      id,
      context,             # world state at decision time
      chosen_action,       # the action we actually took
      alternative_action,  # the action we did NOT take
      simulated_outcome,   # predicted outcome if we had
      actual_outcome,      # what actually happened (later)
      regret,              # actual - simulated (higher ⇒ alt was better)
      ts,
      tags,
    )

Queries:

    find_similar(context) → top-k by situation similarity
    top_regrets(k) → top-k largest regrets (we should have…)
    attach_actual(id, outcome) → close the loop for a stored item

SQLite-persisted, pure stdlib, deterministic.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("memory.counterfactual_memory")


@dataclass
class Counterfactual:
    id: str
    context: dict[str, Any]
    chosen_action: str
    alternative_action: str
    simulated_outcome: float
    actual_outcome: float | None = None
    ts: float = 0.0
    tags: tuple[str, ...] = ()
    note: str = ""

    @property
    def regret(self) -> float | None:
        if self.actual_outcome is None:
            return None
        return float(self.simulated_outcome - self.actual_outcome)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "context": dict(self.context),
            "chosen_action": self.chosen_action,
            "alternative_action": self.alternative_action,
            "simulated_outcome": round(self.simulated_outcome, 4),
            "actual_outcome": (
                round(self.actual_outcome, 4)
                if self.actual_outcome is not None else None
            ),
            "regret": (
                round(self.regret, 4) if self.regret is not None else None
            ),
            "ts": self.ts,
            "tags": list(self.tags),
            "note": self.note,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS counterfactuals (
    id                 TEXT PRIMARY KEY,
    context            TEXT NOT NULL DEFAULT '{}',
    chosen_action      TEXT NOT NULL,
    alternative_action TEXT NOT NULL,
    simulated_outcome  REAL NOT NULL,
    actual_outcome     REAL,
    ts                 REAL NOT NULL,
    tags_csv           TEXT NOT NULL DEFAULT '',
    note               TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_cf_ts ON counterfactuals(ts);
"""


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _similarity(
    a: dict[str, Any], b: dict[str, Any],
    scales: dict[str, float],
) -> float:
    keys = set(a.keys()) | set(b.keys())
    if not keys:
        return 0.0
    total = 0.0
    for k in keys:
        va, vb = a.get(k), b.get(k)
        if va is None or vb is None:
            total += 0.5
            continue
        if _is_number(va) and _is_number(vb):
            scale = scales.get(k, 1.0) or 1.0
            diff = abs(float(va) - float(vb)) / scale
            total += max(0.0, 1.0 - min(1.0, diff))
        else:
            total += 1.0 if str(va) == str(vb) else 0.0
    return total / len(keys)


def _compute_scales(
    items: list[Counterfactual],
) -> dict[str, float]:
    per_key: dict[str, list[float]] = {}
    for it in items:
        for k, v in it.context.items():
            if _is_number(v):
                per_key.setdefault(k, []).append(float(v))
    scales: dict[str, float] = {}
    for k, vs in per_key.items():
        if not vs:
            continue
        hi, lo = max(vs), min(vs)
        scales[k] = hi - lo if hi > lo else max(abs(hi), 1.0)
    return scales


class CounterfactualMemory:
    def __init__(
        self, db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, Counterfactual] = {}
        self._conn: sqlite3.Connection | None = None
        if db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(path), check_same_thread=False,
            )
            with self._lock:
                self._conn.execute("PRAGMA busy_timeout=5000")
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.executescript(_SCHEMA)
                self._conn.commit()
            self._load()

    def _load(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            for row in self._conn.execute(
                "SELECT id, context, chosen_action, alternative_action, "
                "simulated_outcome, actual_outcome, ts, tags_csv, note "
                "FROM counterfactuals",
            ):
                try:
                    ctx = json.loads(row[1] or "{}")
                except (json.JSONDecodeError, ValueError):
                    continue
                self._items[row[0]] = Counterfactual(
                    id=row[0],
                    context=ctx,
                    chosen_action=row[2],
                    alternative_action=row[3],
                    simulated_outcome=float(row[4]),
                    actual_outcome=(
                        float(row[5]) if row[5] is not None else None
                    ),
                    ts=float(row[6]),
                    tags=tuple(
                        t for t in (row[7] or "").split(",") if t
                    ),
                    note=row[8] or "",
                )

    # ── Record ───────────────────────────────────────────

    def record(
        self,
        *,
        context: dict[str, Any],
        chosen_action: str,
        alternative_action: str,
        simulated_outcome: float,
        tags: Iterable[str] = (),
        note: str = "",
    ) -> Counterfactual:
        if not chosen_action:
            raise ValueError("chosen_action required")
        if not alternative_action:
            raise ValueError("alternative_action required")
        cf = Counterfactual(
            id=uuid.uuid4().hex,
            context=dict(context or {}),
            chosen_action=str(chosen_action),
            alternative_action=str(alternative_action),
            simulated_outcome=float(simulated_outcome),
            actual_outcome=None,
            ts=time.time(),
            tags=tuple(
                str(t).strip() for t in tags if str(t).strip()
            ),
            note=str(note),
        )
        with self._lock:
            self._items[cf.id] = cf
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO counterfactuals("
                    "  id, context, chosen_action, alternative_action, "
                    "  simulated_outcome, actual_outcome, ts, "
                    "  tags_csv, note"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        cf.id,
                        json.dumps(cf.context, sort_keys=True),
                        cf.chosen_action,
                        cf.alternative_action,
                        cf.simulated_outcome,
                        None,
                        cf.ts,
                        ",".join(cf.tags),
                        cf.note,
                    ),
                )
                self._conn.commit()
        return cf

    def attach_actual(
        self, counterfactual_id: str, actual_outcome: float,
    ) -> bool:
        with self._lock:
            item = self._items.get(counterfactual_id)
            if item is None:
                return False
            item.actual_outcome = float(actual_outcome)
            if self._conn is not None:
                self._conn.execute(
                    "UPDATE counterfactuals "
                    "SET actual_outcome=? WHERE id=?",
                    (float(actual_outcome), counterfactual_id),
                )
                self._conn.commit()
        return True

    def remove(self, counterfactual_id: str) -> bool:
        with self._lock:
            present = counterfactual_id in self._items
            self._items.pop(counterfactual_id, None)
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM counterfactuals WHERE id=?",
                    (counterfactual_id,),
                )
                self._conn.commit()
        return present

    # ── Query ────────────────────────────────────────────

    def get(self, counterfactual_id: str) -> Counterfactual | None:
        return self._items.get(counterfactual_id)

    def find_similar(
        self,
        query_context: dict[str, Any],
        *,
        k: int = 5,
        tags: Iterable[str] = (),
    ) -> list[tuple[Counterfactual, float]]:
        tag_set = {str(t) for t in tags if t}
        with self._lock:
            pool = list(self._items.values())
        if tag_set:
            pool = [
                it for it in pool
                if tag_set.issubset(set(it.tags))
            ]
        if not pool:
            return []
        scales = _compute_scales(pool)
        scored = [
            (it, _similarity(query_context, it.context, scales))
            for it in pool
        ]
        scored.sort(key=lambda kv: -kv[1])
        return scored[: max(1, int(k))]

    def top_regrets(
        self, *, k: int = 5,
    ) -> list[Counterfactual]:
        """Counterfactuals where the alternative would have beaten
        the chosen action by the largest margin."""
        with self._lock:
            pool = [
                it for it in self._items.values()
                if it.actual_outcome is not None
            ]
        pool.sort(key=lambda it: -(it.regret or 0.0))
        return pool[: max(1, int(k))]

    def realised_regret(self) -> dict[str, Any]:
        """Aggregate regret stats over closed counterfactuals."""
        with self._lock:
            closed = [
                it for it in self._items.values()
                if it.actual_outcome is not None
            ]
        if not closed:
            return {
                "n_closed": 0,
                "mean_regret": 0.0,
                "max_regret": 0.0,
            }
        regrets = [float(it.regret or 0.0) for it in closed]
        return {
            "n_closed": len(closed),
            "mean_regret": round(sum(regrets) / len(regrets), 4),
            "max_regret": round(max(regrets), 4),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._items)
            closed = sum(
                1 for it in self._items.values()
                if it.actual_outcome is not None
            )
        return {
            "total": total,
            "closed": closed,
            "open": total - closed,
        }

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
