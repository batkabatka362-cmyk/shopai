"""Preference elicitation — ask the owner active questions.

reward_model (v8-D1) learns preferences passively from up/down
votes. self_prompt (v8-D3) asks questions *about the store*.
Neither actively surfaces disambiguating questions to the owner
when the brain's uncertain about their preference itself.

When ethics_gate soft-blocks, when two candidates score within
5%, when a new niche has no preference data at all — the right
move is usually "ask the owner one crisp question and record
the answer" rather than guess.

PreferenceElicitation generates pairwise A-vs-B queries when the
brain's decision is close, logs the owner's answer, and feeds
the result back into the reward model as a stronger-than-usual
signal (weight 2 × normal up-vote).

  build_pairwise_query(candidates, reason)
      → Query(options, rationale)
  record_answer(query_id, choice)
      → persists + folds into reward_model
  pending(limit)
      → active queries waiting for owner

Also offers:

  • triage(decisions, threshold)
      Scan a batch of close-margin decisions and emit a prioritised
      list of elicitation queries.

Persistence: ``data/preference_elicitation.db``. Integrates with
reward_model (optional) when available. Zero LLM.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


_DB_PATH = Path("data/preference_elicitation.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    options     TEXT NOT NULL,
    rationale   TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    answer      TEXT,
    answered_at REAL
);
CREATE INDEX IF NOT EXISTS idx_status
    ON queries(status, created_at DESC);
"""


@dataclass
class Option:
    id: str                      # stable option id
    label: str
    features: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label,
            "features": self.features, "score": round(self.score, 3),
        }


@dataclass
class Query:
    id: str
    created_at: float
    options: list[Option]
    rationale: str
    status: str = "pending"
    answer: str | None = None
    answered_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "options": [o.as_dict() for o in self.options],
            "rationale": self.rationale,
            "status": self.status,
            "answer": self.answer,
            "answered_at": self.answered_at,
        }


# ── Engine ──────────────────────────────────────────────────

class PreferenceElicitation:
    def __init__(
        self,
        db_path: Path | str | None = None,
        reward_recorder: Callable[[dict[str, Any], float], None] | None = None,
    ) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._reward = reward_recorder
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Build ───────────────────────────────────────────────

    def build_pairwise_query(
        self,
        options: list[Option] | list[dict[str, Any]],
        rationale: str = "",
    ) -> Query:
        """Two-option comparison. Store the query as pending so the
        owner can answer via CLI / dashboard later."""
        opts = [_coerce_option(o) for o in options]
        if len(opts) < 2:
            raise ValueError("need at least 2 options")
        qid = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO queries (id, created_at, options, "
                "rationale, status) VALUES (?,?,?,?, 'pending')",
                (qid, now,
                 json.dumps([o.as_dict() for o in opts]),
                 rationale),
            )
            conn.commit()
        return Query(
            id=qid, created_at=now, options=opts,
            rationale=rationale, status="pending",
        )

    # ── Answer ──────────────────────────────────────────────

    def record_answer(
        self,
        query_id: str,
        chosen_option_id: str,
        weight: float = 2.0,
    ) -> Query | None:
        """Owner picks one option. The chosen option's features are
        folded into the reward model (if wired) with an elevated
        weight — explicit preference is stronger than organic votes."""
        q = self.get(query_id)
        if q is None or q.status != "pending":
            return None
        chosen = next(
            (o for o in q.options if o.id == chosen_option_id), None,
        )
        if chosen is None:
            raise ValueError(
                f"option {chosen_option_id!r} not in query {query_id!r}",
            )
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE queries SET status='answered', answer=?, "
                "answered_at=? WHERE id=?",
                (chosen_option_id, now, query_id),
            )
            conn.commit()
        q.status = "answered"
        q.answer = chosen_option_id
        q.answered_at = now
        # Fold into reward model if one was injected
        if self._reward is not None:
            # Positive for chosen, negative for the others — classic
            # preference-pair signal.
            self._reward(chosen.features, float(weight))
            for other in q.options:
                if other.id != chosen_option_id:
                    self._reward(other.features, -float(weight) / 2)
        return q

    # ── Queries ─────────────────────────────────────────────

    def get(self, query_id: str) -> Query | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, created_at, options, rationale, status, "
                "answer, answered_at FROM queries WHERE id=?",
                (query_id,),
            ).fetchone()
        return _row_to_query(row) if row else None

    def pending(self, limit: int = 20) -> list[Query]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, options, rationale, status, "
                "answer, answered_at FROM queries "
                "WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [_row_to_query(r) for r in rows]

    def recent_answers(self, limit: int = 20) -> list[Query]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, options, rationale, status, "
                "answer, answered_at FROM queries "
                "WHERE status='answered' "
                "ORDER BY answered_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [_row_to_query(r) for r in rows]

    # ── Triage ──────────────────────────────────────────────

    def triage(
        self,
        close_decisions: Iterable[dict[str, Any]],
        margin_threshold: float = 0.05,
    ) -> list[Query]:
        """Given a batch of candidate decisions (each carrying
        ``options: [Option, ...]`` and per-option ``score``), emit
        queries only for those where the top-2 options are within
        ``margin_threshold`` of each other."""
        out: list[Query] = []
        for d in close_decisions:
            options = [_coerce_option(o) for o in d.get("options", [])]
            if len(options) < 2:
                continue
            ranked = sorted(options, key=lambda o: -o.score)
            top, second = ranked[0], ranked[1]
            top_score = max(1e-6, abs(top.score))
            if (top.score - second.score) / top_score > margin_threshold:
                continue
            rationale = d.get(
                "rationale",
                f"top-2 within {margin_threshold:.0%} "
                f"({top.score:.3f} vs {second.score:.3f})",
            )
            out.append(self.build_pairwise_query(
                [top, second], rationale=rationale,
            ))
        return out


def _coerce_option(o: Option | dict[str, Any]) -> Option:
    if isinstance(o, Option):
        return o
    return Option(
        id=str(o.get("id", uuid.uuid4().hex)),
        label=str(o.get("label", o.get("id", "?"))),
        features=dict(o.get("features", {})),
        score=float(o.get("score", 0.0)),
    )


def _row_to_query(row: tuple) -> Query:
    options_raw = row[2] or "[]"
    try:
        opts = [
            Option(
                id=o["id"], label=o["label"],
                features=o.get("features", {}),
                score=float(o.get("score", 0)),
            )
            for o in json.loads(options_raw)
        ]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        opts = []
    return Query(
        id=row[0],
        created_at=float(row[1] or 0),
        options=opts,
        rationale=row[3] or "",
        status=row[4] or "pending",
        answer=row[5],
        answered_at=row[6],
    )
