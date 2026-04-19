"""Case-based reasoner — learn by recalling similar past situations.

Classical outcome learning asks *"did this action succeed?"* and
bumps a counter. But real decisions don't show up identically twice;
you need to match the *shape* of the situation and reuse what worked.
That's case-based reasoning.

A case is a tuple:

    (situation_features, action, outcome, tags)

situation_features is a flat dict of numeric + categorical attributes
(niche="audio", price=29.99, margin=0.4, stock=12, cpm_range="high").
At decision time, ``recall(query_features, k=5)`` returns the top-k
historically-most-similar cases, weighted by outcome score, so the
caller can ask "what worked last time I saw something like this?".

Similarity:
  • numeric fields  — normalised absolute diff (per-feature scale)
  • categorical     — Jaccard on values (0 if different, 1 if same)
  • missing fields  — neutral contribution (0.5)

Case base is SQLite-persisted (WAL). Pure stdlib. Deterministic.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class Case:
    id: str
    situation: dict[str, Any]
    action: str
    outcome_score: float
    tags: tuple[str, ...] = ()
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "situation": self.situation,
            "action": self.action,
            "outcome_score": round(self.outcome_score, 4),
            "tags": list(self.tags),
            "ts": self.ts,
        }


@dataclass
class Match:
    case: Case
    similarity: float
    weighted_score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.as_dict(),
            "similarity": round(self.similarity, 4),
            "weighted_score": round(self.weighted_score, 4),
        }


# ── Similarity ────────────────────────────────────────────

def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _scale_for(values: list[float]) -> float:
    """Per-feature scale factor — use IQR fallback to max abs, never 0."""
    if not values:
        return 1.0
    vs = sorted(values)
    if len(vs) >= 4:
        q1 = vs[len(vs) // 4]
        q3 = vs[(3 * len(vs)) // 4]
        iqr = q3 - q1
        if iqr > 0:
            return iqr
    spread = max(vs) - min(vs)
    if spread > 0:
        return spread
    return max(abs(vs[0]), 1.0)


def _similarity(
    a: dict[str, Any], b: dict[str, Any],
    scales: dict[str, float],
) -> float:
    """Blend numeric + categorical similarity across shared keys."""
    keys = set(a.keys()) | set(b.keys())
    if not keys:
        return 0.0
    total = 0.0
    for k in keys:
        va = a.get(k)
        vb = b.get(k)
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


# ── Reasoner ──────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id              TEXT PRIMARY KEY,
    situation_json  TEXT NOT NULL,
    action          TEXT NOT NULL,
    outcome_score   REAL NOT NULL,
    tags_json       TEXT NOT NULL,
    ts              REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_ts ON cases(ts);
CREATE INDEX IF NOT EXISTS idx_cases_action ON cases(action);
"""


class CaseBasedReasoner:
    def __init__(self, db_path: str | Path = "data/case_base.db"):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def add(
        self,
        situation: dict[str, Any],
        action: str,
        outcome_score: float,
        tags: Iterable[str] = (),
    ) -> str:
        if not action:
            raise ValueError("action required")
        cid = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO cases VALUES (?,?,?,?,?,?)",
                (
                    cid, json.dumps(situation or {}, sort_keys=True),
                    str(action), float(outcome_score),
                    json.dumps(list(tags)), now,
                ),
            )
            self._conn.commit()
        return cid

    def _all_cases(self) -> list[Case]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, situation_json, action, outcome_score, "
                "tags_json, ts FROM cases",
            ).fetchall()
        out: list[Case] = []
        for r in rows:
            try:
                sit = json.loads(r[1])
                tags = tuple(json.loads(r[4]))
            except (json.JSONDecodeError, ValueError):
                continue
            out.append(Case(
                id=r[0], situation=sit, action=r[2],
                outcome_score=float(r[3]), tags=tags, ts=float(r[5]),
            ))
        return out

    def _numeric_scales(self, cases: list[Case]) -> dict[str, float]:
        per_key: dict[str, list[float]] = {}
        for c in cases:
            for k, v in c.situation.items():
                if _is_number(v):
                    per_key.setdefault(k, []).append(float(v))
        return {k: _scale_for(vs) for k, vs in per_key.items()}

    def recall(
        self,
        query: dict[str, Any],
        k: int = 5,
        *,
        min_similarity: float = 0.0,
        action_filter: str | None = None,
    ) -> list[Match]:
        """Return top-k most similar cases by (similarity × outcome)."""
        cases = self._all_cases()
        if not cases:
            return []
        if action_filter:
            cases = [c for c in cases if c.action == action_filter]
            if not cases:
                return []
        scales = self._numeric_scales(cases)
        matches: list[Match] = []
        for c in cases:
            sim = _similarity(query, c.situation, scales)
            if sim < min_similarity:
                continue
            matches.append(Match(
                case=c, similarity=sim,
                weighted_score=sim * c.outcome_score,
            ))
        matches.sort(key=lambda m: -m.weighted_score)
        return matches[:k]

    def suggest(
        self,
        query: dict[str, Any],
        k: int = 10,
    ) -> dict[str, Any] | None:
        """Aggregate top-k recalls into an action recommendation with
        confidence. Returns None if nothing qualifies."""
        matches = self.recall(query, k=k, min_similarity=0.1)
        if not matches:
            return None
        votes: dict[str, float] = {}
        total = 0.0
        for m in matches:
            w = m.weighted_score
            votes[m.case.action] = votes.get(m.case.action, 0.0) + w
            total += abs(w)
        if total == 0:
            return None
        winner = max(votes.items(), key=lambda kv: kv[1])
        return {
            "action": winner[0],
            "confidence": round(winner[1] / total, 4),
            "support": sum(
                1 for m in matches if m.case.action == winner[0]
            ),
            "mean_similarity": round(
                sum(m.similarity for m in matches) / len(matches), 4,
            ),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM cases",
            ).fetchone()[0]
            actions = self._conn.execute(
                "SELECT action, COUNT(*) FROM cases GROUP BY action",
            ).fetchall()
            mean_score_row = self._conn.execute(
                "SELECT AVG(outcome_score) FROM cases",
            ).fetchone()
        return {
            "total": int(total),
            "by_action": {a: int(n) for a, n in actions},
            "mean_outcome": round(
                float(mean_score_row[0]) if mean_score_row[0] else 0.0,
                4,
            ),
        }

    def prune(self, keep_newest: int = 5_000) -> int:
        """Drop oldest cases beyond the keep window. Returns dropped count."""
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM cases",
            ).fetchone()[0]
            if total <= keep_newest:
                return 0
            drop = total - keep_newest
            self._conn.execute(
                "DELETE FROM cases WHERE id IN ("
                "  SELECT id FROM cases ORDER BY ts ASC LIMIT ?"
                ")",
                (drop,),
            )
            self._conn.commit()
        return int(drop)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
