"""Hypothesis engine — predict, register, test, resolve.

ShopAI currently learns *passively* — an outcome arrives, memory
updates. A more scientific brain *predicts first*: it says
"I think raising price by 10% will cut CVR by ≤ 5%; let's see".
When the outcome arrives, the prediction is scored and the
brain's confidence in the underlying model is updated.

This module formalises that loop:

  1. ``predict(subject, kpi, direction, magnitude, horizon_days,
      rationale)`` — register a falsifiable hypothesis.
  2. The store records the *baseline* KPI at registration time.
  3. After ``horizon_days``, ``resolve(hypothesis_id, observed)``
     scores it: ``confirmed`` | ``partial`` | ``refuted`` |
     ``inconclusive``.
  4. Brain's calibration tracker folds confirmed / refuted counts
     into a Beta posterior per rationale-category — cheap, global
     "how often am I right" estimate.

Key properties:

  • Every hypothesis is *falsifiable* at creation — it must name a
    direction + magnitude + horizon.
  • The brain can auto-generate a hypothesis from any decision by
    calling ``hypothesise_from_decision(decision, expected_kpi)``.
  • Aging: unresolved > ``2 × horizon_days`` are auto-marked
    ``stale`` and excluded from calibration.

Persistence: ``data/hypotheses.db`` SQLite, WAL mode. Resolver
writes a ``category=hypothesis score=3.5`` memory row per
resolution so retrieval surfaces them in debates.
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

from utils.logger import get_logger


logger = get_logger("brain.hypothesis")

_DB_PATH = Path("data/hypotheses.db")

Direction = Literal["up", "down", "flat"]
Verdict = Literal["confirmed", "partial", "refuted",
                  "inconclusive", "stale", "pending"]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS hypotheses (
    id              TEXT PRIMARY KEY,
    created_at      REAL NOT NULL,
    subject         TEXT NOT NULL,
    kpi             TEXT NOT NULL,
    direction       TEXT NOT NULL,
    magnitude_pct   REAL NOT NULL,
    horizon_days    INTEGER NOT NULL,
    baseline        REAL NOT NULL,
    rationale       TEXT,
    rationale_tag   TEXT,
    resolved_at     REAL,
    observed        REAL,
    verdict         TEXT DEFAULT 'pending',
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_subject ON hypotheses(subject);
CREATE INDEX IF NOT EXISTS idx_verdict ON hypotheses(verdict);
CREATE INDEX IF NOT EXISTS idx_tag ON hypotheses(rationale_tag);
"""


@dataclass
class Hypothesis:
    id: str
    created_at: float
    subject: str
    kpi: str
    direction: Direction
    magnitude_pct: float
    horizon_days: int
    baseline: float
    rationale: str = ""
    rationale_tag: str = ""
    resolved_at: float | None = None
    observed: float | None = None
    verdict: Verdict = "pending"
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "subject": self.subject,
            "kpi": self.kpi,
            "direction": self.direction,
            "magnitude_pct": round(self.magnitude_pct, 3),
            "horizon_days": self.horizon_days,
            "baseline": round(self.baseline, 4),
            "rationale": self.rationale,
            "rationale_tag": self.rationale_tag,
            "resolved_at": self.resolved_at,
            "observed": (round(self.observed, 4)
                          if self.observed is not None else None),
            "verdict": self.verdict,
            "notes": self.notes,
        }

    @property
    def is_overdue(self) -> bool:
        if self.verdict != "pending":
            return False
        age_s = time.time() - self.created_at
        return age_s > self.horizon_days * 86_400

    @property
    def is_stale(self) -> bool:
        if self.verdict != "pending":
            return False
        age_s = time.time() - self.created_at
        return age_s > 2 * self.horizon_days * 86_400


@dataclass
class CalibrationSummary:
    tag: str
    confirmed: int = 0
    partial: int = 0
    refuted: int = 0
    inconclusive: int = 0
    total_resolved: int = 0
    # Beta(α, β) posterior over "prediction correct" probability
    posterior_alpha: float = 1.0
    posterior_beta: float = 1.0

    @property
    def hit_rate(self) -> float:
        if self.total_resolved == 0:
            return 0.5    # prior
        return self.posterior_alpha / (
            self.posterior_alpha + self.posterior_beta
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "confirmed": self.confirmed,
            "partial": self.partial,
            "refuted": self.refuted,
            "inconclusive": self.inconclusive,
            "total_resolved": self.total_resolved,
            "hit_rate": round(self.hit_rate, 3),
            "posterior_alpha": round(self.posterior_alpha, 2),
            "posterior_beta": round(self.posterior_beta, 2),
        }


# ── Engine ──────────────────────────────────────────────────

class HypothesisEngine:
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

    # ── Registration ────────────────────────────────────────

    def predict(
        self,
        subject: str,
        kpi: str,
        direction: Direction,
        magnitude_pct: float,
        horizon_days: int,
        baseline: float,
        rationale: str = "",
        rationale_tag: str = "",
    ) -> Hypothesis:
        if direction not in ("up", "down", "flat"):
            raise ValueError(f"bad direction {direction!r}")
        if horizon_days <= 0:
            raise ValueError("horizon_days must be > 0")
        h = Hypothesis(
            id=uuid.uuid4().hex,
            created_at=time.time(),
            subject=subject.strip(),
            kpi=kpi.strip(),
            direction=direction,
            magnitude_pct=float(magnitude_pct),
            horizon_days=int(horizon_days),
            baseline=float(baseline),
            rationale=rationale.strip(),
            rationale_tag=rationale_tag.strip(),
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO hypotheses "
                "(id, created_at, subject, kpi, direction, "
                " magnitude_pct, horizon_days, baseline, "
                " rationale, rationale_tag, verdict) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (h.id, h.created_at, h.subject, h.kpi, h.direction,
                 h.magnitude_pct, h.horizon_days, h.baseline,
                 h.rationale, h.rationale_tag, "pending"),
            )
            conn.commit()
        return h

    # ── Resolution ──────────────────────────────────────────

    def resolve(
        self,
        hypothesis_id: str,
        observed: float,
        notes: str = "",
    ) -> Hypothesis:
        h = self.get(hypothesis_id)
        if h is None:
            raise KeyError(f"unknown hypothesis {hypothesis_id!r}")
        verdict = self._verdict_for(h, observed)
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE hypotheses SET resolved_at=?, observed=?, "
                "verdict=?, notes=? WHERE id=?",
                (time.time(), float(observed), verdict, notes,
                 hypothesis_id),
            )
            conn.commit()
        h.resolved_at = time.time()
        h.observed = float(observed)
        h.verdict = verdict
        h.notes = notes
        self._emit_memory(h)
        return h

    @staticmethod
    def _verdict_for(h: Hypothesis, observed: float) -> Verdict:
        if h.baseline == 0:
            # Can't compute a % delta without a baseline.
            if h.direction == "flat":
                return "confirmed" if observed == 0 else "refuted"
            return "inconclusive"
        delta_pct = (observed - h.baseline) / abs(h.baseline) * 100.0
        if h.direction == "up":
            if delta_pct >= h.magnitude_pct:
                return "confirmed"
            if delta_pct >= 0.5 * h.magnitude_pct:
                return "partial"
            return "refuted"
        if h.direction == "down":
            if delta_pct <= -h.magnitude_pct:
                return "confirmed"
            if delta_pct <= -0.5 * h.magnitude_pct:
                return "partial"
            return "refuted"
        # flat
        if abs(delta_pct) <= h.magnitude_pct:
            return "confirmed"
        if abs(delta_pct) <= 2 * h.magnitude_pct:
            return "partial"
        return "refuted"

    # ── Maintenance ─────────────────────────────────────────

    def mark_stale(self) -> int:
        """Expire hypotheses whose horizon has elapsed 2× without a
        resolve call. Returns the number newly marked stale."""
        cutoff = time.time()
        count = 0
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, horizon_days FROM hypotheses "
                "WHERE verdict='pending'"
            ).fetchall()
            for hid, created_at, horizon_days in rows:
                if (cutoff - created_at) > 2 * horizon_days * 86_400:
                    conn.execute(
                        "UPDATE hypotheses SET verdict='stale' WHERE id=?",
                        (hid,),
                    )
                    count += 1
            conn.commit()
        return count

    # ── Queries ─────────────────────────────────────────────

    def get(self, hypothesis_id: str) -> Hypothesis | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM hypotheses WHERE id=?",
                (hypothesis_id,),
            ).fetchone()
        return _row_to_hypothesis(row) if row else None

    def list_pending(self, subject: str | None = None) -> list[Hypothesis]:
        with self._connect() as conn:
            if subject:
                rows = conn.execute(
                    "SELECT * FROM hypotheses WHERE verdict='pending' "
                    "AND subject=? ORDER BY created_at",
                    (subject,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM hypotheses WHERE verdict='pending' "
                    "ORDER BY created_at"
                ).fetchall()
        return [_row_to_hypothesis(r) for r in rows]

    def list_overdue(self) -> list[Hypothesis]:
        cutoff = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM hypotheses WHERE verdict='pending'"
            ).fetchall()
        out = []
        for r in rows:
            h = _row_to_hypothesis(r)
            if (cutoff - h.created_at) > h.horizon_days * 86_400:
                out.append(h)
        return out

    def calibration(
        self,
        tag: str | None = None,
    ) -> CalibrationSummary:
        """Return hit-rate posterior for a rationale tag (or global if
        tag is None)."""
        with self._connect() as conn:
            q = ("SELECT verdict FROM hypotheses WHERE verdict IN "
                 "('confirmed','partial','refuted','inconclusive')")
            params: tuple = ()
            if tag:
                q += " AND rationale_tag=?"
                params = (tag,)
            rows = conn.execute(q, params).fetchall()
        c = CalibrationSummary(tag=tag or "*")
        for (v,) in rows:
            if v == "confirmed":
                c.confirmed += 1
            elif v == "partial":
                c.partial += 1
            elif v == "refuted":
                c.refuted += 1
            elif v == "inconclusive":
                c.inconclusive += 1
        c.total_resolved = c.confirmed + c.partial + c.refuted + c.inconclusive
        # Beta update: partial counts as 0.5 win, inconclusive counts
        # as no update. Start from prior Beta(1,1) = uniform.
        c.posterior_alpha = 1.0 + c.confirmed + 0.5 * c.partial
        c.posterior_beta = 1.0 + c.refuted + 0.5 * c.partial
        return c

    # ── Memory hook ────────────────────────────────────────

    def _emit_memory(self, h: Hypothesis) -> None:
        try:
            from core.memory.unified_memory import get_unified_memory
            mi = get_unified_memory().get_memory_intelligence()
            mi.create(
                category="hypothesis",
                content=h.as_dict(),
                action=f"resolved_{h.verdict}",
                score=3.5,
                tags=["hypothesis", h.verdict,
                      f"subject:{h.subject}",
                      *(["tag:" + h.rationale_tag]
                        if h.rationale_tag else [])],
            )
        except Exception as exc:
            logger.debug("hypothesis event emit failed: %s", exc)


def _row_to_hypothesis(row: tuple) -> Hypothesis:
    return Hypothesis(
        id=row[0],
        created_at=float(row[1]),
        subject=row[2],
        kpi=row[3],
        direction=row[4],
        magnitude_pct=float(row[5]),
        horizon_days=int(row[6]),
        baseline=float(row[7]),
        rationale=row[8] or "",
        rationale_tag=row[9] or "",
        resolved_at=row[10],
        observed=row[11],
        verdict=row[12] or "pending",
        notes=row[13] or "",
    )


# ── Convenience ─────────────────────────────────────────────

def hypothesise_from_decision(
    decision: dict[str, Any],
    expected_kpi: str,
    baseline: float,
    horizon_days: int = 7,
) -> Hypothesis:
    """Every decision the brain makes implies a prediction. Wrap the
    verdict + expected direction into a registered hypothesis so the
    outcome can score it."""
    verdict = (decision.get("verdict") or "").lower()
    direction: Direction
    if verdict in ("scale", "buy", "raise", "promote", "launch"):
        direction, mag = "up", 10.0
    elif verdict in ("kill", "cut", "lower", "demote"):
        direction, mag = "down", 10.0
    else:
        direction, mag = "flat", 5.0
    return engine().predict(
        subject=str(decision.get("subject") or decision.get("id") or "?"),
        kpi=expected_kpi,
        direction=direction,
        magnitude_pct=mag,
        horizon_days=horizon_days,
        baseline=baseline,
        rationale=decision.get("rationale", ""),
        rationale_tag=decision.get("rationale_tag", verdict),
    )


# ── Singleton ────────────────────────────────────────────────

_ENGINE_LOCK = threading.Lock()
_ENGINE: HypothesisEngine | None = None


def engine() -> HypothesisEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = HypothesisEngine()
    return _ENGINE
