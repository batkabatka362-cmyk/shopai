"""Competence model — Bayesian inventory of task-class win rate.

Subsystems accumulate win/loss records, but the brain has no
overarching answer to *"what am I good at, what am I bad at?"*.
CompetenceModel aggregates per-task-class outcomes from arbitrary
callers, calibrates stated confidence against observed accuracy, and
exposes three core queries:

  • competence(task_class)  — Beta-posterior mean success rate
  • confidence_gap()        — global stated vs observed calibration
  • should_defer(task_class, threshold) — is this class below the bar?

Callers record every task attempt:

    cm.record(
        task_class="kill_bad_ad",
        success=True,
        stated_confidence=0.8,
    )

Over time the model also flags *confident-but-wrong* patterns (stated
0.9, observed 0.4) — metacognitive bias.

Complements the outward-looking ``metacognition.reflect()``: that one
asks "is the *system* healthy?"; this one asks "am *I* qualified for
this specific task class?".

Pure stdlib. SQLite-persisted. Deterministic.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Competence:
    task_class: str
    uses: int
    wins: int
    prior_alpha: float
    prior_beta: float
    stated_confidence_sum: float
    stated_confidence_n: int
    last_ts: float

    @property
    def success_rate(self) -> float:
        a = self.prior_alpha + self.wins
        b = self.prior_beta + (self.uses - self.wins)
        denom = a + b
        return a / denom if denom > 0 else 0.5

    @property
    def mean_stated_confidence(self) -> float:
        if self.stated_confidence_n == 0:
            return 0.5
        return self.stated_confidence_sum / self.stated_confidence_n

    @property
    def calibration_error(self) -> float:
        return self.mean_stated_confidence - self.success_rate

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_class": self.task_class,
            "uses": self.uses,
            "wins": self.wins,
            "success_rate": round(self.success_rate, 4),
            "mean_stated_confidence": round(
                self.mean_stated_confidence, 4,
            ),
            "calibration_error": round(self.calibration_error, 4),
            "last_ts": self.last_ts,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS competence (
    task_class             TEXT PRIMARY KEY,
    uses                   INTEGER NOT NULL DEFAULT 0,
    wins                   INTEGER NOT NULL DEFAULT 0,
    prior_alpha            REAL NOT NULL DEFAULT 1.0,
    prior_beta             REAL NOT NULL DEFAULT 1.0,
    stated_confidence_sum  REAL NOT NULL DEFAULT 0.0,
    stated_confidence_n    INTEGER NOT NULL DEFAULT 0,
    last_ts                REAL NOT NULL DEFAULT 0
);
"""


class CompetenceModel:
    def __init__(
        self, db_path: str | Path = "data/competence_model.db",
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

    def _ensure(
        self, task_class: str,
        prior_alpha: float = 1.0, prior_beta: float = 1.0,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO competence"
                "(task_class, prior_alpha, prior_beta) VALUES (?,?,?)",
                (task_class, float(prior_alpha), float(prior_beta)),
            )
            self._conn.commit()

    def record(
        self,
        task_class: str,
        success: bool,
        stated_confidence: float | None = None,
    ) -> None:
        if not task_class:
            raise ValueError("task_class required")
        self._ensure(task_class)
        add_conf = (
            float(stated_confidence)
            if stated_confidence is not None else 0.0
        )
        n_conf = 1 if stated_confidence is not None else 0
        with self._lock:
            self._conn.execute(
                "UPDATE competence SET "
                "uses = uses + 1, "
                "wins = wins + ?, "
                "stated_confidence_sum = stated_confidence_sum + ?, "
                "stated_confidence_n = stated_confidence_n + ?, "
                "last_ts = ? "
                "WHERE task_class = ?",
                (
                    1 if success else 0,
                    add_conf, n_conf, time.time(), task_class,
                ),
            )
            self._conn.commit()

    def _row_to_competence(
        self, task_class: str, row: tuple[Any, ...],
    ) -> Competence:
        return Competence(
            task_class=task_class,
            uses=int(row[0]), wins=int(row[1]),
            prior_alpha=float(row[2]), prior_beta=float(row[3]),
            stated_confidence_sum=float(row[4]),
            stated_confidence_n=int(row[5]),
            last_ts=float(row[6]),
        )

    def competence(self, task_class: str) -> Competence:
        with self._lock:
            row = self._conn.execute(
                "SELECT uses, wins, prior_alpha, prior_beta, "
                "stated_confidence_sum, stated_confidence_n, last_ts "
                "FROM competence WHERE task_class=?",
                (task_class,),
            ).fetchone()
        if row is None:
            return Competence(
                task_class=task_class, uses=0, wins=0,
                prior_alpha=1.0, prior_beta=1.0,
                stated_confidence_sum=0.0, stated_confidence_n=0,
                last_ts=0.0,
            )
        return self._row_to_competence(task_class, row)

    def should_defer(
        self,
        task_class: str,
        threshold: float = 0.6,
        min_support: int = 5,
    ) -> bool:
        """True when observed success_rate is below threshold AND we have
        enough evidence to trust it. Novel task classes defer by default."""
        c = self.competence(task_class)
        if c.uses < min_support:
            return True
        return c.success_rate < threshold

    def rank(
        self,
        min_support: int = 3,
        order: str = "success_rate",
    ) -> list[Competence]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT task_class, uses, wins, prior_alpha, prior_beta, "
                "stated_confidence_sum, stated_confidence_n, last_ts "
                "FROM competence WHERE uses >= ?",
                (int(min_support),),
            ).fetchall()
        cs = [
            self._row_to_competence(r[0], r[1:])
            for r in rows
        ]
        if order == "calibration_error":
            cs.sort(key=lambda c: -abs(c.calibration_error))
        else:
            cs.sort(key=lambda c: -c.success_rate)
        return cs

    def strengths_weaknesses(
        self,
        *, top_n: int = 5, min_support: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        ranked = self.rank(min_support=min_support, order="success_rate")
        return {
            "strengths": [c.as_dict() for c in ranked[:top_n]],
            "weaknesses": [c.as_dict() for c in ranked[-top_n:][::-1]],
        }

    def confidence_gap(
        self, min_support: int = 5,
    ) -> dict[str, Any]:
        ranked = self.rank(min_support=min_support)
        if not ranked:
            return {"mean_abs_gap": 0.0, "global_bias": 0.0, "n": 0}
        weights = [c.uses for c in ranked]
        total = sum(weights) or 1
        mean_abs = sum(
            abs(c.calibration_error) * c.uses for c in ranked
        ) / total
        global_bias = sum(
            c.calibration_error * c.uses for c in ranked
        ) / total
        return {
            "mean_abs_gap": round(mean_abs, 4),
            "global_bias": round(global_bias, 4),
            "n": len(ranked),
        }

    def summary(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), SUM(uses), SUM(wins) FROM competence",
            ).fetchone()
        total_classes = int(row[0] or 0)
        total_uses = int(row[1] or 0)
        total_wins = int(row[2] or 0)
        global_rate = (
            total_wins / total_uses if total_uses > 0 else 0.5
        )
        return {
            "task_classes": total_classes,
            "total_uses": total_uses,
            "global_success_rate": round(global_rate, 4),
            "confidence_gap": self.confidence_gap(),
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
