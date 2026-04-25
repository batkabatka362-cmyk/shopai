"""Episode summariser — compress a decision episode into one paragraph.

A decision episode is the bundle of (situation, options considered,
chosen action, outcome, supporting evidence). Stored raw, it balloons
the database; surfaced raw, owners drown in detail. The summariser
produces a single-paragraph ``EpisodeSummary`` keeping the essentials
and stamps it for Obsidian/vault mirroring.

Fields captured:

  • title           — short slug ("$20/day ad launch on pet-food SKU")
  • situation_terms — 3-5 canonical descriptors of the start state
  • winning_action  — one-sentence description of the chosen action
  • alternatives    — 0-3 one-sentence descriptions of rejected options
  • outcome         — "win" | "loss" | "mixed" | "pending"
  • lesson          — one-sentence takeaway (or empty)
  • evidence_keys   — pointers back to raw memory records

Summaries are deterministic given inputs (no LLM). Owners pin the
most instructive ones for the vault. Pure stdlib, SQLite-persisted.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("memory.episode_summarizer")


Outcome = Literal["win", "loss", "mixed", "pending"]


@dataclass
class EpisodeSummary:
    id: str
    title: str
    situation_terms: tuple[str, ...]
    winning_action: str
    alternatives: tuple[str, ...]
    outcome: Outcome
    lesson: str
    evidence_keys: tuple[str, ...]
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "situation_terms": list(self.situation_terms),
            "winning_action": self.winning_action,
            "alternatives": list(self.alternatives),
            "outcome": self.outcome,
            "lesson": self.lesson,
            "evidence_keys": list(self.evidence_keys),
            "ts": self.ts,
        }

    def as_paragraph(self) -> str:
        bits = [self.title + "."]
        if self.situation_terms:
            bits.append(
                "Situation: "
                + ", ".join(self.situation_terms) + "."
            )
        bits.append("Took: " + self.winning_action + ".")
        if self.alternatives:
            bits.append(
                "Declined: "
                + "; ".join(self.alternatives) + "."
            )
        bits.append(f"Outcome: {self.outcome}.")
        if self.lesson:
            bits.append("Lesson: " + self.lesson)
        return " ".join(bits)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS episode_summaries (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    situation_json      TEXT NOT NULL,
    winning_action      TEXT NOT NULL,
    alternatives_json   TEXT NOT NULL,
    outcome             TEXT NOT NULL,
    lesson              TEXT NOT NULL,
    evidence_json       TEXT NOT NULL,
    ts                  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ep_ts
    ON episode_summaries(ts);
CREATE INDEX IF NOT EXISTS idx_ep_outcome
    ON episode_summaries(outcome);
"""


def _slugify(text: str, *, max_len: int = 60) -> str:
    text = text.strip()
    if not text:
        return "episode"
    clean = re.sub(r"\s+", " ", text)
    if len(clean) > max_len:
        clean = clean[: max_len - 1] + "…"
    return clean


def _top_terms(
    situation: dict[str, Any], limit: int = 5,
) -> tuple[str, ...]:
    pairs: list[str] = []
    for k in sorted(situation.keys()):
        v = situation[k]
        if isinstance(v, (int, float)):
            pairs.append(f"{k}={v}")
        else:
            pairs.append(f"{k}={v}")
        if len(pairs) >= limit:
            break
    return tuple(pairs)


def _classify_outcome(
    score: float | None,
) -> Outcome:
    if score is None:
        return "pending"
    if score >= 0.7:
        return "win"
    if score <= 0.3:
        return "loss"
    return "mixed"


class EpisodeSummariser:
    def __init__(
        self, db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._summaries: dict[str, EpisodeSummary] = {}
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
                "SELECT id, title, situation_json, "
                "winning_action, alternatives_json, outcome, "
                "lesson, evidence_json, ts "
                "FROM episode_summaries",
            ):
                try:
                    sit = tuple(json.loads(row[2]))
                    alts = tuple(json.loads(row[4]))
                    ev = tuple(json.loads(row[7]))
                except (json.JSONDecodeError, ValueError):
                    continue
                self._summaries[row[0]] = EpisodeSummary(
                    id=row[0],
                    title=row[1],
                    situation_terms=sit,
                    winning_action=row[3],
                    alternatives=alts,
                    outcome=row[5],
                    lesson=row[6] or "",
                    evidence_keys=ev,
                    ts=float(row[8]),
                )

    def _persist(self, s: EpisodeSummary) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO episode_summaries("
            "  id, title, situation_json, winning_action, "
            "  alternatives_json, outcome, lesson, "
            "  evidence_json, ts"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                s.id, s.title,
                json.dumps(list(s.situation_terms)),
                s.winning_action,
                json.dumps(list(s.alternatives)),
                s.outcome, s.lesson,
                json.dumps(list(s.evidence_keys)),
                s.ts,
            ),
        )
        self._conn.commit()

    # ── Summarise ────────────────────────────────────────

    def summarise(
        self,
        *,
        title_hint: str,
        situation: dict[str, Any] | None = None,
        winning_action: str,
        alternatives: Iterable[str] = (),
        outcome_score: float | None = None,
        lesson: str = "",
        evidence_keys: Iterable[str] = (),
        ts: float | None = None,
    ) -> EpisodeSummary:
        if not winning_action:
            raise ValueError("winning_action required")
        if not title_hint:
            raise ValueError("title_hint required")
        timestamp = float(ts if ts is not None else time.time())
        summary = EpisodeSummary(
            id=uuid.uuid4().hex,
            title=_slugify(title_hint),
            situation_terms=_top_terms(situation or {}),
            winning_action=winning_action.strip(),
            alternatives=tuple(
                str(a).strip() for a in alternatives if a
            )[:3],
            outcome=_classify_outcome(outcome_score),
            lesson=(lesson or "").strip(),
            evidence_keys=tuple(
                str(e) for e in evidence_keys if e
            ),
            ts=timestamp,
        )
        with self._lock:
            self._summaries[summary.id] = summary
            self._persist(summary)
        return summary

    # ── Queries ──────────────────────────────────────────

    def get(self, summary_id: str) -> EpisodeSummary | None:
        with self._lock:
            return self._summaries.get(summary_id)

    def recent(
        self, *, limit: int = 20,
    ) -> list[EpisodeSummary]:
        with self._lock:
            items = list(self._summaries.values())
        items.sort(key=lambda s: -s.ts)
        return items[: max(1, int(limit))]

    def by_outcome(self, outcome: Outcome) -> list[EpisodeSummary]:
        with self._lock:
            return [
                s for s in self._summaries.values()
                if s.outcome == outcome
            ]

    def wins(self) -> list[EpisodeSummary]:
        return self.by_outcome("win")

    def losses(self) -> list[EpisodeSummary]:
        return self.by_outcome("loss")

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_outcome: dict[str, int] = {}
            for s in self._summaries.values():
                by_outcome[s.outcome] = (
                    by_outcome.get(s.outcome, 0) + 1
                )
            return {
                "total": len(self._summaries),
                "by_outcome": by_outcome,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._summaries)
            self._summaries.clear()
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM episode_summaries",
                )
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
