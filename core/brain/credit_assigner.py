"""Credit assigner — when revenue arrives, who gets credit?

Every cycle emits decisions and eventually outcomes (orders, refunds,
churn). Without credit assignment, every rule and every engine gets
uniform up-votes from every positive outcome, so the learning signal
is mush. The credit assigner attributes an outcome to the decisions
that preceded it, weighted by:

  • Recency — exponential half-life; recent decisions get more weight
  • Attribution hints — a decision can declare the KPI it's trying
    to influence, which multiplies its weight for that KPI
  • Saturation — the sum of weights is normalised to 1 so we don't
    over-credit when many decisions preceded one outcome

API:

    ca = CreditAssigner(half_life_s=3 * 86400)
    ca.note_decision(decision_id="d1", ts=t1,
                      claimed_kpis=["revenue", "cvr"])
    ca.note_outcome(outcome_id="o1", kpi="revenue",
                     value=100.0, ts=t2)
    credits = ca.credits_for(outcome_id="o1")
    # → {"d1": 100.0} when d1 is the only candidate

Persistence is optional — SQLite-backed if db_path is provided.
Pure stdlib, deterministic.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class DecisionRec:
    id: str
    ts: float
    claimed_kpis: tuple[str, ...] = ()
    weight_multiplier: float = 1.0


@dataclass
class OutcomeRec:
    id: str
    kpi: str
    value: float
    ts: float


@dataclass
class CreditReport:
    outcome_id: str
    kpi: str
    value: float
    credits: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "kpi": self.kpi,
            "value": round(self.value, 4),
            "credits": {
                k: round(v, 4) for k, v in self.credits.items()
            },
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id                 TEXT PRIMARY KEY,
    ts                 REAL NOT NULL,
    claimed_kpis       TEXT NOT NULL DEFAULT '',
    weight_multiplier  REAL NOT NULL DEFAULT 1.0
);
CREATE TABLE IF NOT EXISTS outcomes (
    id    TEXT PRIMARY KEY,
    kpi   TEXT NOT NULL,
    value REAL NOT NULL,
    ts    REAL NOT NULL
);
"""


class CreditAssigner:
    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        half_life_s: float = 3 * 86_400.0,
        lookback_s: float = 14 * 86_400.0,
        claimed_boost: float = 2.5,
    ) -> None:
        if half_life_s <= 0 or lookback_s <= 0:
            raise ValueError("half_life_s / lookback_s must be positive")
        if claimed_boost < 1.0:
            raise ValueError("claimed_boost must be ≥ 1")
        self._half_life_s = float(half_life_s)
        self._lookback_s = float(lookback_s)
        self._claimed_boost = float(claimed_boost)
        self._lock = threading.Lock()
        self._decisions: dict[str, DecisionRec] = {}
        self._outcomes: dict[str, OutcomeRec] = {}
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

    # ── Intake ────────────────────────────────────────────

    def note_decision(
        self,
        *,
        decision_id: str | None = None,
        ts: float | None = None,
        claimed_kpis: Iterable[str] = (),
        weight_multiplier: float = 1.0,
    ) -> str:
        did = decision_id or uuid.uuid4().hex
        rec = DecisionRec(
            id=did,
            ts=float(ts if ts is not None else time.time()),
            claimed_kpis=tuple(str(k) for k in claimed_kpis if k),
            weight_multiplier=float(weight_multiplier),
        )
        with self._lock:
            self._decisions[did] = rec
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO decisions"
                    "(id, ts, claimed_kpis, weight_multiplier) "
                    "VALUES (?, ?, ?, ?)",
                    (did, rec.ts,
                     ",".join(rec.claimed_kpis),
                     rec.weight_multiplier),
                )
                self._conn.commit()
        return did

    def note_outcome(
        self,
        *,
        kpi: str,
        value: float,
        outcome_id: str | None = None,
        ts: float | None = None,
    ) -> str:
        if not kpi:
            raise ValueError("kpi required")
        oid = outcome_id or uuid.uuid4().hex
        rec = OutcomeRec(
            id=oid, kpi=str(kpi),
            value=float(value),
            ts=float(ts if ts is not None else time.time()),
        )
        with self._lock:
            self._outcomes[oid] = rec
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO outcomes"
                    "(id, kpi, value, ts) VALUES (?, ?, ?, ?)",
                    (oid, rec.kpi, rec.value, rec.ts),
                )
                self._conn.commit()
        return oid

    # ── Credit math ──────────────────────────────────────

    def _weight(self, dec: DecisionRec, outcome: OutcomeRec) -> float:
        dt = outcome.ts - dec.ts
        if dt < 0 or dt > self._lookback_s:
            return 0.0
        decay = 0.5 ** (dt / self._half_life_s)
        boost = (
            self._claimed_boost
            if outcome.kpi in dec.claimed_kpis else 1.0
        )
        return decay * boost * dec.weight_multiplier

    def credits_for(self, outcome_id: str) -> CreditReport:
        with self._lock:
            outcome = self._outcomes.get(outcome_id)
        if outcome is None:
            return CreditReport(
                outcome_id=outcome_id, kpi="", value=0.0,
            )
        weights: dict[str, float] = {}
        with self._lock:
            for did, dec in self._decisions.items():
                w = self._weight(dec, outcome)
                if w > 0:
                    weights[did] = w
        total = sum(weights.values())
        if total == 0:
            return CreditReport(
                outcome_id=outcome_id,
                kpi=outcome.kpi, value=outcome.value,
            )
        return CreditReport(
            outcome_id=outcome_id,
            kpi=outcome.kpi, value=outcome.value,
            credits={
                did: outcome.value * (w / total)
                for did, w in weights.items()
            },
        )

    def total_credit(self, decision_id: str) -> float:
        total = 0.0
        with self._lock:
            outcomes = list(self._outcomes.values())
        for outcome in outcomes:
            rep = self.credits_for(outcome.id)
            total += rep.credits.get(decision_id, 0.0)
        return total

    def top_decisions(
        self, kpi: str | None = None, limit: int = 10,
    ) -> list[tuple[str, float]]:
        totals: dict[str, float] = {}
        with self._lock:
            outcomes = list(self._outcomes.values())
        for outcome in outcomes:
            if kpi is not None and outcome.kpi != kpi:
                continue
            rep = self.credits_for(outcome.id)
            for did, v in rep.credits.items():
                totals[did] = totals.get(did, 0.0) + v
        ranked = sorted(
            totals.items(), key=lambda kv: -kv[1],
        )
        return ranked[:limit]

    # ── Maintenance ──────────────────────────────────────

    def _load(self) -> None:
        assert self._conn is not None
        with self._lock:
            for row in self._conn.execute(
                "SELECT id, ts, claimed_kpis, weight_multiplier "
                "FROM decisions",
            ):
                self._decisions[row[0]] = DecisionRec(
                    id=row[0], ts=float(row[1]),
                    claimed_kpis=tuple(
                        s for s in str(row[2] or "").split(",") if s
                    ),
                    weight_multiplier=float(row[3]),
                )
            for row in self._conn.execute(
                "SELECT id, kpi, value, ts FROM outcomes",
            ):
                self._outcomes[row[0]] = OutcomeRec(
                    id=row[0], kpi=row[1],
                    value=float(row[2]), ts=float(row[3]),
                )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "decisions": len(self._decisions),
                "outcomes": len(self._outcomes),
                "half_life_s": self._half_life_s,
                "lookback_s": self._lookback_s,
            }

    def prune_before(self, cutoff_ts: float) -> int:
        n = 0
        with self._lock:
            for key in list(self._decisions.keys()):
                if self._decisions[key].ts < cutoff_ts:
                    del self._decisions[key]
                    n += 1
            for key in list(self._outcomes.keys()):
                if self._outcomes[key].ts < cutoff_ts:
                    del self._outcomes[key]
                    n += 1
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM decisions WHERE ts < ?",
                    (float(cutoff_ts),),
                )
                self._conn.execute(
                    "DELETE FROM outcomes WHERE ts < ?",
                    (float(cutoff_ts),),
                )
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
