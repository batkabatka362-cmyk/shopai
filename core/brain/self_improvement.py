"""Self-improvement loop — the brain proposes its own config tunes.

Metacognition (v3) scores how the brain is doing. Self-prompt (v8)
asks questions. Neither translates the answers into *actionable
changes to the brain's own configuration*. This module closes
that gap.

At each cycle, SelfImprovementEngine inspects recent performance
signals and emits ``Proposal`` entries describing concrete config
changes it thinks would help:

  • threshold tune    — "kill threshold raised from 1.5 to 1.7
                         because niche=audio consistently refunds
                         at 1.5-1.6 range"
  • skill priority    — "skill content.email_copy has 9/10 win
                         rate but hasn't been used in 14 days;
                         raise priority"
  • rule retirement   — "rule R-123 has fired 40× with 25% success;
                         mark for retirement"
  • add missing rule  — "kills in fashion/premium all had
                         margin_band=thin; consider codifying"
  • alpha adjust      — "reward model's kpi_weight=0.5 but the
                         preference term now dominates; lower α
                         to 0.3"

Every proposal carries a ``severity`` (suggest | propose |
auto_apply_if_toggled), a ``reversibility`` (always True by
design — proposals must be trivially rollback-able), and a
``rationale`` with the supporting numbers. The owner / daemon
decides what to apply.

Persistence: ``data/self_improvement.db`` — proposals + outcomes
so the engine can learn which of its proposals actually helped.
Pure Python, zero LLM.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


Severity = Literal["suggest", "propose", "auto_apply_if_toggled"]


_DB_PATH = Path("data/self_improvement.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    kind        TEXT NOT NULL,
    target      TEXT NOT NULL,
    before_json TEXT,
    after_json  TEXT,
    severity    TEXT NOT NULL DEFAULT 'suggest',
    rationale   TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    applied_at  REAL,
    outcome_score REAL
);
CREATE INDEX IF NOT EXISTS idx_status ON proposals(status, created_at DESC);
"""


@dataclass
class Proposal:
    id: str
    created_at: float
    kind: str
    target: str
    before: Any
    after: Any
    severity: Severity
    rationale: str
    status: str = "pending"        # pending | applied | rejected | expired
    applied_at: float | None = None
    outcome_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "kind": self.kind,
            "target": self.target,
            "before": self.before,
            "after": self.after,
            "severity": self.severity,
            "rationale": self.rationale,
            "status": self.status,
            "applied_at": self.applied_at,
            "outcome_score": self.outcome_score,
        }


@dataclass
class Signals:
    """Cycle-scoped snapshot the engine inspects. Caller populates
    what it has; missing fields default to safe neutrals."""
    niche_kill_outcomes: list[dict[str, Any]] = field(default_factory=list)
    skill_usage: list[dict[str, Any]] = field(default_factory=list)
    rule_performance: list[dict[str, Any]] = field(default_factory=list)
    missing_rule_clusters: list[dict[str, Any]] = field(default_factory=list)
    reward_model_stats: dict[str, Any] = field(default_factory=dict)


# ── Engine ──────────────────────────────────────────────────

class SelfImprovementEngine:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Detection passes ────────────────────────────────────

    def detect(self, signals: Signals) -> list[Proposal]:
        proposals: list[Proposal] = []
        proposals.extend(self._threshold_tune(signals))
        proposals.extend(self._skill_priority(signals))
        proposals.extend(self._rule_retirement(signals))
        proposals.extend(self._missing_rule(signals))
        proposals.extend(self._alpha_adjust(signals))
        # Persist every proposal
        for p in proposals:
            self._persist(p)
        return proposals

    # ── Rules ──────────────────────────────────────────────

    def _threshold_tune(self, s: Signals) -> list[Proposal]:
        out: list[Proposal] = []
        for entry in s.niche_kill_outcomes:
            niche = entry.get("niche")
            current = float(entry.get("current_threshold", 0))
            refund_roas = entry.get("refund_roas_band", [])
            if not niche or current <= 0 or not refund_roas:
                continue
            # If refunds cluster above the current threshold, raise it
            lo = float(refund_roas[0])
            hi = float(refund_roas[1]) if len(refund_roas) > 1 else lo
            if lo > current and hi < current * 1.3:
                new = round(hi + 0.1, 2)
                out.append(self._mk_proposal(
                    kind="threshold_tune",
                    target=f"niche:{niche}:kill_threshold",
                    before=current, after=new,
                    severity="propose",
                    rationale=(f"refunds in {niche} cluster at ROAS "
                               f"{lo:.2f}-{hi:.2f}, above current "
                               f"threshold {current:.2f}"),
                ))
        return out

    def _skill_priority(self, s: Signals) -> list[Proposal]:
        out: list[Proposal] = []
        for sk in s.skill_usage:
            name = sk.get("name")
            wins = int(sk.get("wins", 0))
            uses = int(sk.get("uses", 0))
            days_idle = float(sk.get("days_since_use", 0))
            current_prio = float(sk.get("priority", 1.0))
            if not name or uses < 3:
                continue
            win_rate = wins / uses
            if win_rate >= 0.8 and days_idle >= 10:
                # Strong skill sitting idle — raise priority
                new = round(min(2.0, current_prio * 1.3), 2)
                if new > current_prio:
                    out.append(self._mk_proposal(
                        kind="skill_priority",
                        target=f"skill:{name}",
                        before=current_prio, after=new,
                        severity="propose",
                        rationale=(f"skill '{name}' has {wins}/{uses} "
                                   f"win rate but idle {int(days_idle)}d"),
                    ))
            elif win_rate < 0.3 and uses >= 10:
                new = round(max(0.1, current_prio * 0.5), 2)
                out.append(self._mk_proposal(
                    kind="skill_priority",
                    target=f"skill:{name}",
                    before=current_prio, after=new,
                    severity="propose",
                    rationale=(f"skill '{name}' has only {wins}/{uses} "
                               "win rate"),
                ))
        return out

    def _rule_retirement(self, s: Signals) -> list[Proposal]:
        out: list[Proposal] = []
        for r in s.rule_performance:
            rid = r.get("id")
            fires = int(r.get("fires", 0))
            successes = int(r.get("successes", 0))
            if fires < 20:
                continue
            success_rate = successes / fires
            if success_rate < 0.3:
                out.append(self._mk_proposal(
                    kind="rule_retirement",
                    target=f"rule:{rid}",
                    before={"status": "active"},
                    after={"status": "retired"},
                    severity="propose",
                    rationale=(f"rule {rid} fired {fires}× with "
                               f"{success_rate:.0%} success"),
                ))
        return out

    def _missing_rule(self, s: Signals) -> list[Proposal]:
        out: list[Proposal] = []
        for c in s.missing_rule_clusters:
            feature = c.get("feature")
            count = int(c.get("count", 0))
            outcome = c.get("outcome")
            if not feature or count < 5 or outcome is None:
                continue
            out.append(self._mk_proposal(
                kind="missing_rule",
                target=f"feature:{feature}",
                before=None,
                after={"codify": feature, "outcome": outcome,
                       "evidence": count},
                severity="suggest",
                rationale=(f"{count} events matched feature {feature} "
                           f"and outcome={outcome}; consider codifying"),
            ))
        return out

    def _alpha_adjust(self, s: Signals) -> list[Proposal]:
        rm = s.reward_model_stats or {}
        pref = float(rm.get("preference_weight_share", 0.0))
        alpha = rm.get("kpi_weight")
        if alpha is None:
            return []
        alpha = float(alpha)
        # If preferences dominate hugely, lower alpha (give more weight
        # to explicit KPI). If KPI dominates despite plenty of data,
        # raise alpha the other way.
        if pref >= 0.85 and alpha > 0.3:
            new = round(alpha * 0.7, 2)
            return [self._mk_proposal(
                kind="alpha_adjust",
                target="reward_model.kpi_weight",
                before=alpha, after=new,
                severity="suggest",
                rationale=(f"preference term dominates ({pref:.0%}); "
                           "lower α so KPI retains influence"),
            )]
        if pref <= 0.15 and alpha < 0.8:
            new = round(min(0.9, alpha * 1.3), 2)
            return [self._mk_proposal(
                kind="alpha_adjust",
                target="reward_model.kpi_weight",
                before=alpha, after=new,
                severity="suggest",
                rationale=(f"preference term contributes only {pref:.0%}; "
                           "raise α so KPI dominates"),
            )]
        return []

    # ── Application ─────────────────────────────────────────

    def apply(self, proposal_id: str) -> bool:
        return self._set_status(proposal_id, "applied",
                                 applied_at=time.time())

    def reject(self, proposal_id: str) -> bool:
        return self._set_status(proposal_id, "rejected")

    def score_outcome(
        self, proposal_id: str, outcome_score: float,
    ) -> bool:
        """Later: did the proposal help? 0..1 score feeds back into
        which proposal kinds are reliable."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE proposals SET outcome_score=? WHERE id=?",
                (float(outcome_score), proposal_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def pending(self, limit: int = 20) -> list[Proposal]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, kind, target, before_json, "
                "after_json, severity, rationale, status, applied_at, "
                "outcome_score FROM proposals WHERE status='pending' "
                "ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [_row_to_proposal(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            by_status = conn.execute(
                "SELECT status, COUNT(*) FROM proposals GROUP BY status"
            ).fetchall()
            avg_scored = conn.execute(
                "SELECT AVG(outcome_score) FROM proposals "
                "WHERE outcome_score IS NOT NULL"
            ).fetchone()
        return {
            "by_status": {s: int(c) for s, c in by_status},
            "avg_outcome_score": (round(float(avg_scored[0]), 3)
                                    if avg_scored and avg_scored[0]
                                    is not None else None),
        }

    # ── Internals ──────────────────────────────────────────

    def _mk_proposal(
        self, *, kind: str, target: str, before: Any, after: Any,
        severity: Severity, rationale: str,
    ) -> Proposal:
        return Proposal(
            id=uuid.uuid4().hex,
            created_at=time.time(),
            kind=kind, target=target,
            before=before, after=after,
            severity=severity, rationale=rationale,
        )

    def _persist(self, p: Proposal) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO proposals "
                "(id, created_at, kind, target, before_json, after_json, "
                " severity, rationale, status) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (p.id, p.created_at, p.kind, p.target,
                 json.dumps(p.before, default=str),
                 json.dumps(p.after, default=str),
                 p.severity, p.rationale, p.status),
            )
            conn.commit()

    def _set_status(
        self, proposal_id: str, status: str,
        applied_at: float | None = None,
    ) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE proposals SET status=?, applied_at=? WHERE id=?",
                (status, applied_at, proposal_id),
            )
            conn.commit()
            return cur.rowcount > 0


def _row_to_proposal(r: tuple) -> Proposal:
    return Proposal(
        id=r[0],
        created_at=float(r[1]),
        kind=r[2],
        target=r[3],
        before=_load(r[4]),
        after=_load(r[5]),
        severity=r[6],
        rationale=r[7] or "",
        status=r[8] or "pending",
        applied_at=r[9],
        outcome_score=r[10],
    )


def _load(s: str | None) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return s
