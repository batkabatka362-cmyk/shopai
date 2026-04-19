"""Experiment manager — allocate A/B traffic, track uplift, promote winners.

The hypothesis engine lets us *declare* a prediction. uplift_estimator
lets us *measure* a treatment effect. experiment_manager ties them
together into a full A/B workflow:

  1. register(name, variants)      — e.g. ("control", "free_shipping")
  2. allocate(name, unit_id)       — deterministically hash a unit
                                      (customer / order) to a variant
  3. observe(name, unit_id, outcome)— record the outcome per unit
  4. status(name)                  — per-variant means + significant
                                      winner from uplift_estimator
  5. promote(name)                 — declare winner as the default
                                      variant when significance met

Allocation is pure-hash (sha1 of unit_id + experiment name), so the
same unit always lands in the same variant — deterministic and
stateless across cycles.

Promotion requires: ≥ ``min_samples`` per variant AND significant
uplift. Reject otherwise; caller can keep the experiment running.

Pure stdlib. SQLite-persisted. No LLM.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal


ExperimentStatus = Literal["running", "promoted", "stopped"]


@dataclass
class Experiment:
    name: str
    variants: tuple[str, ...]
    outcome_key: str
    status: ExperimentStatus
    promoted_variant: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "variants": list(self.variants),
            "outcome_key": self.outcome_key,
            "status": self.status,
            "promoted_variant": self.promoted_variant,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ExperimentStatusReport:
    name: str
    status: ExperimentStatus
    per_variant: dict[str, dict[str, float]] = field(
        default_factory=dict,
    )
    leader: str = ""
    uplift: float = 0.0
    significant: bool = False
    n_total: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "per_variant": {
                k: {kk: round(vv, 4) for kk, vv in v.items()}
                for k, v in self.per_variant.items()
            },
            "leader": self.leader,
            "uplift": round(self.uplift, 4),
            "significant": self.significant,
            "n_total": self.n_total,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    name             TEXT PRIMARY KEY,
    variants         TEXT NOT NULL,
    outcome_key      TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'running',
    promoted_variant TEXT NOT NULL DEFAULT '',
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS experiment_observations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment TEXT NOT NULL,
    unit_id    TEXT NOT NULL,
    variant    TEXT NOT NULL,
    outcome    REAL NOT NULL,
    ts         REAL NOT NULL,
    UNIQUE(experiment, unit_id)
);
CREATE INDEX IF NOT EXISTS idx_exp_obs_var
    ON experiment_observations(experiment, variant);
"""


def _hash_to_index(experiment_name: str, unit_id: str, n: int) -> int:
    """Deterministic uniform-ish bucketing by sha1 of combined key."""
    if n <= 0:
        return 0
    h = hashlib.sha1(
        f"{experiment_name}:{unit_id}".encode("utf-8"),
    ).hexdigest()
    return int(h[:8], 16) % n


class ExperimentManager:
    def __init__(
        self, db_path: str | Path = "data/experiments.db",
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Registration ─────────────────────────────────────

    def register(
        self,
        name: str,
        variants: Iterable[str],
        outcome_key: str = "conversion",
    ) -> Experiment:
        variants = tuple(dict.fromkeys(v for v in variants if v))
        if not name:
            raise ValueError("experiment name required")
        if len(variants) < 2:
            raise ValueError("need at least 2 variants")
        if not outcome_key:
            raise ValueError("outcome_key required")
        now = time.time()
        with self._lock:
            existing = self._conn.execute(
                "SELECT name FROM experiments WHERE name=?",
                (name,),
            ).fetchone()
            if existing is not None:
                raise ValueError(
                    f"experiment {name!r} already registered",
                )
            self._conn.execute(
                "INSERT INTO experiments("
                "  name, variants, outcome_key, status, "
                "  promoted_variant, created_at, updated_at"
                ") VALUES (?, ?, ?, 'running', '', ?, ?)",
                (
                    name, "|".join(variants), outcome_key,
                    now, now,
                ),
            )
            self._conn.commit()
        return Experiment(
            name=name, variants=variants,
            outcome_key=outcome_key, status="running",
            created_at=now, updated_at=now,
        )

    def get(self, name: str) -> Experiment | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT name, variants, outcome_key, status, "
                "promoted_variant, created_at, updated_at "
                "FROM experiments WHERE name=?",
                (name,),
            ).fetchone()
        if row is None:
            return None
        return Experiment(
            name=row[0],
            variants=tuple(s for s in str(row[1]).split("|") if s),
            outcome_key=row[2],
            status=row[3], promoted_variant=row[4],
            created_at=float(row[5]),
            updated_at=float(row[6]),
        )

    def stop(self, name: str) -> None:
        self._set_status(name, "stopped")

    def _set_status(
        self,
        name: str, status: ExperimentStatus,
        promoted_variant: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE experiments SET status=?, "
                "promoted_variant=?, updated_at=? WHERE name=?",
                (status, promoted_variant, time.time(), name),
            )
            self._conn.commit()

    # ── Allocation ───────────────────────────────────────

    def allocate(self, name: str, unit_id: str) -> str:
        exp = self.get(name)
        if exp is None:
            raise ValueError(f"unknown experiment {name!r}")
        if exp.status == "promoted" and exp.promoted_variant:
            return exp.promoted_variant
        if exp.status == "stopped":
            return exp.variants[0] if exp.variants else ""
        idx = _hash_to_index(name, unit_id, len(exp.variants))
        return exp.variants[idx]

    # ── Observation ──────────────────────────────────────

    def observe(
        self,
        name: str, unit_id: str,
        outcome: float,
    ) -> str:
        """Record outcome for a unit. Returns the variant (so the
        caller can log it without re-hashing)."""
        exp = self.get(name)
        if exp is None:
            raise ValueError(f"unknown experiment {name!r}")
        variant = self.allocate(name, unit_id)
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO experiment_observations"
                "(experiment, unit_id, variant, outcome, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, unit_id, variant, float(outcome), time.time()),
            )
            self._conn.commit()
        return variant

    # ── Status + promotion ───────────────────────────────

    def status(self, name: str) -> ExperimentStatusReport:
        exp = self.get(name)
        if exp is None:
            raise ValueError(f"unknown experiment {name!r}")
        per: dict[str, dict[str, float]] = {}
        total = 0
        for v in exp.variants:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT outcome FROM experiment_observations "
                    "WHERE experiment=? AND variant=?",
                    (name, v),
                ).fetchall()
            values = [float(r[0]) for r in rows]
            n = len(values)
            mean = sum(values) / n if n > 0 else 0.0
            var = (
                sum((x - mean) ** 2 for x in values) / (n - 1)
                if n > 1 else 0.0
            )
            per[v] = {"n": n, "mean": mean, "variance": var}
            total += n

        leader = ""
        uplift = 0.0
        significant = False
        if len(exp.variants) >= 2:
            # Leader = variant with highest mean; compare vs first variant
            # treated as control (or the variant called "control" if it
            # exists).
            control = "control" if "control" in exp.variants else exp.variants[0]
            leader_cand = max(
                exp.variants, key=lambda v: per[v]["mean"],
            )
            if leader_cand != control:
                t = per[leader_cand]
                c = per[control]
                uplift = t["mean"] - c["mean"]
                if t["n"] > 1 and c["n"] > 1:
                    import math
                    se = math.sqrt(
                        t["variance"] / t["n"]
                        + c["variance"] / c["n"],
                    )
                    half = 1.96 * se
                    if uplift > 0 and uplift - half > 0:
                        significant = True
                    elif uplift < 0 and uplift + half < 0:
                        significant = True
                leader = leader_cand
            else:
                leader = control

        return ExperimentStatusReport(
            name=name, status=exp.status,
            per_variant=per,
            leader=leader, uplift=uplift,
            significant=significant, n_total=total,
        )

    def promote(
        self,
        name: str,
        *,
        min_samples_per_variant: int = 100,
    ) -> bool:
        """Promote if significance + enough samples. Returns whether
        the promotion fired."""
        exp = self.get(name)
        if exp is None:
            raise ValueError(f"unknown experiment {name!r}")
        if exp.status != "running":
            return False
        rep = self.status(name)
        if not rep.significant:
            return False
        if any(
            v.get("n", 0) < min_samples_per_variant
            for v in rep.per_variant.values()
        ):
            return False
        # Significant and powered — promote the leader.
        self._set_status(
            name, "promoted", promoted_variant=rep.leader,
        )
        return True

    # ── Queries + maintenance ────────────────────────────

    def list_experiments(self) -> list[Experiment]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM experiments",
            ).fetchall()
        return [exp for exp in (self.get(r[0]) for r in rows) if exp is not None]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_status = dict(self._conn.execute(
                "SELECT status, COUNT(*) FROM experiments "
                "GROUP BY status",
            ).fetchall())
            obs = int(self._conn.execute(
                "SELECT COUNT(*) FROM experiment_observations",
            ).fetchone()[0])
        return {
            "by_status": {k: int(v) for k, v in by_status.items()},
            "total_observations": obs,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
