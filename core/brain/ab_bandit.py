"""A/B bandit — Thompson sampling multi-armed allocation.

The hypothesis engine registers predictions; the policy library
tracks a single running success rate. Neither *allocates live
traffic* between competing variants with a well-known exploration
strategy. Without that, owners have to run A/B tests in third-
party tools and hand-copy winners.

ABBandit stores one or more *experiments*, each with named arms.
Every arm carries a Beta(α, β) posterior over success probability.

APIs:

  create(experiment_id, arm_ids, prior_alpha=1, prior_beta=1)
  assign(experiment_id) → arm_id (Thompson-sampled)
  record(experiment_id, arm_id, success)
  leader(experiment_id)     → arm with highest posterior mean
  significance(experiment_id) → probability the leader is best,
                                computed via Monte Carlo sampling
  archive(experiment_id, winner_id)   → finalise + stop serving

Thompson sampling chooses the arm whose Beta draw is highest —
proven optimal regret bound for independent arm means.

Persistence: ``data/ab_bandit.db``. Thread-safe, zero LLM,
deterministic under a seeded RNG for tests.
"""
from __future__ import annotations

import math
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_DB_PATH = Path("data/ab_bandit.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    winner_id   TEXT,
    ended_at    REAL
);
CREATE TABLE IF NOT EXISTS arms (
    experiment_id TEXT NOT NULL,
    arm_id        TEXT NOT NULL,
    alpha         REAL NOT NULL DEFAULT 1.0,
    beta          REAL NOT NULL DEFAULT 1.0,
    assignments   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (experiment_id, arm_id)
);
"""


@dataclass
class Arm:
    arm_id: str
    alpha: float
    beta: float
    assignments: int = 0

    @property
    def mean(self) -> float:
        total = self.alpha + self.beta
        return self.alpha / total if total > 0 else 0.5

    @property
    def samples(self) -> int:
        return int((self.alpha - 1) + (self.beta - 1))

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm_id,
            "alpha": round(self.alpha, 2),
            "beta": round(self.beta, 2),
            "assignments": self.assignments,
            "samples": self.samples,
            "mean": round(self.mean, 3),
        }


@dataclass
class Experiment:
    id: str
    created_at: float
    arms: list[Arm] = field(default_factory=list)
    status: str = "active"
    winner_id: str | None = None
    ended_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "status": self.status,
            "winner_id": self.winner_id,
            "ended_at": self.ended_at,
            "arms": [a.as_dict() for a in self.arms],
        }

    def arm(self, arm_id: str) -> Arm | None:
        for a in self.arms:
            if a.arm_id == arm_id:
                return a
        return None


# ── Bandit ──────────────────────────────────────────────────

class ABBandit:
    def __init__(
        self,
        db_path: Path | str | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── CRUD ───────────────────────────────────────────────

    def create(
        self,
        experiment_id: str,
        arm_ids: Iterable[str],
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> Experiment:
        experiment_id = experiment_id.strip()
        if not experiment_id:
            raise ValueError("experiment_id required")
        arm_ids = list(arm_ids)
        if len(arm_ids) < 2:
            raise ValueError("need at least 2 arms")
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO experiments "
                "(id, created_at, status, winner_id, ended_at) "
                "VALUES (?,?, 'active', NULL, NULL)",
                (experiment_id, now),
            )
            # Recreating an experiment wipes prior arms so the arm
            # set is exactly what the caller specified.
            conn.execute(
                "DELETE FROM arms WHERE experiment_id=?",
                (experiment_id,),
            )
            for aid in arm_ids:
                conn.execute(
                    "INSERT OR REPLACE INTO arms "
                    "(experiment_id, arm_id, alpha, beta, assignments) "
                    "VALUES (?, ?, ?, ?, 0)",
                    (experiment_id, aid, float(prior_alpha),
                     float(prior_beta)),
                )
            conn.commit()
        return self.get(experiment_id)

    def get(self, experiment_id: str) -> Experiment | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, created_at, status, winner_id, ended_at "
                "FROM experiments WHERE id=?",
                (experiment_id,),
            ).fetchone()
            if not row:
                return None
            arm_rows = conn.execute(
                "SELECT arm_id, alpha, beta, assignments FROM arms "
                "WHERE experiment_id=? ORDER BY arm_id",
                (experiment_id,),
            ).fetchall()
        return Experiment(
            id=row[0],
            created_at=float(row[1]),
            status=row[2] or "active",
            winner_id=row[3],
            ended_at=row[4],
            arms=[
                Arm(arm_id=r[0], alpha=float(r[1]),
                     beta=float(r[2]), assignments=int(r[3]))
                for r in arm_rows
            ],
        )

    # ── Assignment ──────────────────────────────────────────

    def assign(self, experiment_id: str) -> str | None:
        exp = self.get(experiment_id)
        if exp is None or exp.status != "active" or not exp.arms:
            return None
        # Thompson: draw one sample per arm, pick arg-max.
        samples = [
            (a.arm_id, self._rng.betavariate(max(1e-6, a.alpha),
                                               max(1e-6, a.beta)))
            for a in exp.arms
        ]
        chosen_id = max(samples, key=lambda kv: kv[1])[0]
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE arms SET assignments = assignments + 1 "
                "WHERE experiment_id=? AND arm_id=?",
                (experiment_id, chosen_id),
            )
            conn.commit()
        return chosen_id

    # ── Outcome ────────────────────────────────────────────

    def record(
        self, experiment_id: str, arm_id: str, success: bool,
    ) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE arms SET "
                "  alpha = alpha + ?, "
                "  beta  = beta + ? "
                "WHERE experiment_id=? AND arm_id=?",
                (1 if success else 0, 0 if success else 1,
                 experiment_id, arm_id),
            )
            conn.commit()
            return cur.rowcount > 0

    # ── Inference ──────────────────────────────────────────

    def leader(self, experiment_id: str) -> Arm | None:
        exp = self.get(experiment_id)
        if exp is None or not exp.arms:
            return None
        return max(exp.arms, key=lambda a: a.mean)

    def significance(
        self,
        experiment_id: str,
        *,
        draws: int = 2000,
    ) -> dict[str, float]:
        """Monte Carlo estimate: P(arm_i has highest mean).

        Returns arm_id → probability the arm is best."""
        exp = self.get(experiment_id)
        if exp is None or not exp.arms:
            return {}
        wins: dict[str, int] = {a.arm_id: 0 for a in exp.arms}
        for _ in range(int(draws)):
            best_id = None
            best_val = -1.0
            for a in exp.arms:
                v = self._rng.betavariate(
                    max(1e-6, a.alpha), max(1e-6, a.beta),
                )
                if v > best_val:
                    best_val, best_id = v, a.arm_id
            if best_id is not None:
                wins[best_id] += 1
        total = sum(wins.values()) or 1
        return {k: round(v / total, 3) for k, v in wins.items()}

    # ── Lifecycle ──────────────────────────────────────────

    def archive(
        self, experiment_id: str, winner_id: str | None = None,
    ) -> bool:
        exp = self.get(experiment_id)
        if exp is None:
            return False
        winner = winner_id or (self.leader(experiment_id)
                                  or exp.arms[0]).arm_id
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE experiments SET "
                "  status='archived', winner_id=?, ended_at=? "
                "WHERE id=?",
                (winner, time.time(), experiment_id),
            )
            conn.commit()
        return True

    def active_experiments(self) -> list[Experiment]:
        with self._connect() as conn:
            ids = conn.execute(
                "SELECT id FROM experiments WHERE status='active'"
            ).fetchall()
        return [self.get(r[0]) for r in ids if r[0]]
