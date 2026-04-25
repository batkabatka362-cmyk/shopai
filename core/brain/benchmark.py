"""Self-benchmark — measure the brain's own capability over time.

The brain has grown 70+ modules across 10 sprints, but nothing
tracks whether it's actually *getting smarter*. Without a
benchmark suite:

  • regressions in retrieval accuracy go unnoticed
  • gains from self-improvement proposals can't be quantified
  • the owner can't answer "is this brain worth what it costs?"

BrainBenchmark runs a set of named capability tasks, scores each
pass/fail (or 0-1 for graded), timestamps the run, and persists
results so the dashboard can draw a growth-over-time line.

Built-in capability tasks (deterministic, self-contained, no
production dependency):

  sentiment_accuracy    — classify a small fixed corpus
  intent_accuracy       — intent labels on the same corpus
  analogy_map           — core/brain/analogy map_score fidelity
  world_model_recall    — train/eval split on a toy trajectory
  rule_conflict_pick    — conflict_resolver chooses correctly on
                           a seeded contradiction
  bayesnet_inference    — known-answer marginal P query
  attribution_sanity    — last-click attributes last touch
  anticipation_signal   — trend extrapolation catches a crossing
  ethics_block          — deceptive anchor hard-blocks
  surprise_outlier      — 4σ event flagged

Plus an ``add_task(name, fn)`` hook so feature sprints can
register their own.

Run: ``engine.run_all()`` → BenchmarkReport
Persist: ``engine.persist(report)`` writes to
``data/benchmarks.db``. history() plots growth.

Zero external deps. Targets are ~20 light tests so the run
completes in <1 second.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


_DB_PATH = Path("data/benchmarks.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    label       TEXT,
    overall     REAL NOT NULL,
    details     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_created ON runs(created_at DESC);
"""


@dataclass
class TaskResult:
    name: str
    score: float                   # 0..1
    detail: str = ""
    duration_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 3),
            "detail": self.detail,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass
class BenchmarkReport:
    id: str
    created_at: float
    tasks: list[TaskResult] = field(default_factory=list)

    @property
    def overall(self) -> float:
        if not self.tasks:
            return 0.0
        return round(
            statistics.mean(t.score for t in self.tasks), 3,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "overall": self.overall,
            "tasks": [t.as_dict() for t in self.tasks],
        }


# ── Built-in tasks ─────────────────────────────────────────

def _safe(score: float) -> float:
    return max(0.0, min(1.0, float(score)))


def task_sentiment_accuracy() -> TaskResult:
    from core.brain import sentiment
    corpus = [
        ("I love this product, amazing quality!", "positive"),
        ("Terrible experience, worst purchase ever.", "negative"),
        ("The package arrived today.", "neutral"),
    ]
    right = 0
    for text, expected in corpus:
        if sentiment.analyse(text).sentiment_label == expected:
            right += 1
    return TaskResult(
        name="sentiment_accuracy",
        score=_safe(right / len(corpus)),
        detail=f"{right}/{len(corpus)}",
    )


def task_intent_accuracy() -> TaskResult:
    from core.brain import sentiment
    corpus = [
        ("product arrived broken, need a refund", "complaint"),
        ("How do I reset my password?", "question"),
        ("please unsubscribe me from your list", "unsubscribe"),
    ]
    right = sum(
        1 for text, expected in corpus
        if sentiment.intent(text) == expected
    )
    return TaskResult(
        name="intent_accuracy",
        score=_safe(right / len(corpus)),
        detail=f"{right}/{len(corpus)}",
    )


def task_bayesnet_inference() -> TaskResult:
    from core.brain import bayesnet
    net = bayesnet.BayesNet()
    net.add("niche", ["a", "b"], prior={"a": 0.5, "b": 0.5})
    net.add(
        "sale", ["yes", "no"], parents=["niche"],
        cpt={("a",): {"yes": 0.8, "no": 0.2},
             ("b",): {"yes": 0.2, "no": 0.8}},
    )
    # P(sale=yes) = 0.5
    p = net.query(target="sale", target_value="yes")
    score = 1.0 if abs(p - 0.5) < 0.01 else 0.0
    return TaskResult(
        name="bayesnet_inference", score=score,
        detail=f"P(sale=yes)={p:.3f}",
    )


def task_rule_conflict_pick() -> TaskResult:
    from core.brain import conflict_resolver as cr
    a = {"id": "A", "fires": 20, "wins": 18,
         "provenance": "owner_demo"}
    b = {"id": "B", "fires": 20, "wins": 4,
         "provenance": "mined"}
    res = cr.resolve(a, b)
    score = 1.0 if res.winner_id == "A" else 0.0
    return TaskResult(
        name="rule_conflict_pick", score=score,
        detail=f"winner={res.winner_id}",
    )


def task_attribution_sanity() -> TaskResult:
    from core.brain import attribution as at
    j = at.Journey(
        journey_id="j",
        touches=[
            at.Touch(channel="meta", timestamp=1),
            at.Touch(channel="email", timestamp=2),
        ],
        conversion_value=100.0,
    )
    credits = at.last_click(j)
    score = 1.0 if credits.get("email") == 1.0 else 0.0
    return TaskResult(
        name="attribution_sanity", score=score,
        detail=f"credits={credits}",
    )


def task_anticipation_signal() -> TaskResult:
    from core.brain import anticipation as an
    xs = [0, 1, 2, 3, 4]
    ys = [3.0, 2.7, 2.4, 2.1, 1.8]
    p = an.extrapolate(
        subject="x", xs=xs, ys=ys,
        threshold=1.5, direction="below",
    )
    score = 1.0 if p is not None else 0.0
    return TaskResult(
        name="anticipation_signal", score=score,
        detail="crossing detected" if score else "missed",
    )


def task_ethics_block() -> TaskResult:
    from core.brain import ethics_gate as eg
    verdict = eg.check({
        "kind": "set_price",
        "price": 29.0,
        "compare_at_price": 299.0,
        "verified_historical_max_price": 50.0,
    })
    score = 1.0 if verdict.status == "hard_block" else 0.0
    return TaskResult(
        name="ethics_block", score=score,
        detail=f"status={verdict.status}",
    )


def task_surprise_outlier() -> TaskResult:
    import tempfile
    from core.brain import surprise as sp
    with tempfile.TemporaryDirectory() as tmp:
        d = sp.SurpriseDetector(Path(tmp) / "s.db")
        for _ in range(5):
            d.observe("x", observed=2.0, expected_mean=2.0,
                       expected_stdev=0.5)
        ev = d.observe("x", observed=5.0, expected_mean=2.0,
                        expected_stdev=0.5)
    score = 1.0 if ev is not None and ev.kind == "outlier" else 0.0
    return TaskResult(
        name="surprise_outlier", score=score,
        detail="outlier flagged" if score else "missed",
    )


def task_working_memory_salience() -> TaskResult:
    from core.brain import working_memory as wm
    m = wm.WorkingMemory(capacity=3)
    m.push("note", {}, score=5.0)
    urgent_id = m.push("urgent", {"x": 1}, urgency=3,
                        owner_relevant=True)
    focus = m.focus(capacity=1)
    score = 1.0 if focus and focus[0].id == urgent_id else 0.0
    return TaskResult(
        name="working_memory_salience", score=score,
        detail="urgent surfaced" if score else "missed",
    )


def task_constraint_solver_basics() -> TaskResult:
    from core.brain import constraint_solver as cs
    items = [
        cs.Item(id="a", marginal_roas=3.0, max_budget=200),
        cs.Item(id="b", marginal_roas=1.5, max_budget=200),
    ]
    alloc = cs.solve(items, total_budget=100)
    score = 1.0 if alloc.get("a").allocated == 100 else 0.0
    return TaskResult(
        name="constraint_solver_basics", score=score,
        detail=f"a={alloc.get('a').allocated}",
    )


_BUILTIN_TASKS: tuple[Callable[[], TaskResult], ...] = (
    task_sentiment_accuracy,
    task_intent_accuracy,
    task_bayesnet_inference,
    task_rule_conflict_pick,
    task_attribution_sanity,
    task_anticipation_signal,
    task_ethics_block,
    task_surprise_outlier,
    task_working_memory_salience,
    task_constraint_solver_basics,
)


# ── Engine ──────────────────────────────────────────────────

class BrainBenchmark:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._tasks: list[Callable[[], TaskResult]] = list(_BUILTIN_TASKS)
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def add_task(self, fn: Callable[[], TaskResult]) -> None:
        self._tasks.append(fn)

    def task_names(self) -> list[str]:
        return [fn.__name__.replace("task_", "") for fn in self._tasks]

    # ── Run ─────────────────────────────────────────────────

    def run_all(self) -> BenchmarkReport:
        report = BenchmarkReport(
            id=uuid.uuid4().hex,
            created_at=time.time(),
        )
        for fn in self._tasks:
            start = time.monotonic()
            try:
                result = fn()
            except Exception as exc:
                result = TaskResult(
                    name=fn.__name__.replace("task_", ""),
                    score=0.0,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            result.duration_ms = (time.monotonic() - start) * 1000
            report.tasks.append(result)
        return report

    # ── Persistence / history ──────────────────────────────

    def persist(
        self, report: BenchmarkReport, label: str = "",
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, created_at, label, overall, "
                "details) VALUES (?,?,?,?,?)",
                (report.id, report.created_at, label, report.overall,
                 json.dumps(report.as_dict(), default=str)),
            )
            conn.commit()

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, label, overall FROM runs "
                "ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            {
                "id": r[0],
                "created_at": float(r[1]),
                "label": r[2] or "",
                "overall": float(r[3]),
            }
            for r in rows
        ]

    def latest(self) -> dict[str, Any] | None:
        hist = self.history(limit=1)
        return hist[0] if hist else None

    def growth(self) -> dict[str, Any] | None:
        """Return {first, latest, delta} if at least 2 runs exist."""
        hist = self.history(limit=1000)
        if len(hist) < 2:
            return None
        latest = hist[0]
        first = hist[-1]
        return {
            "first_overall": first["overall"],
            "latest_overall": latest["overall"],
            "delta": round(latest["overall"] - first["overall"], 3),
            "runs": len(hist),
        }
