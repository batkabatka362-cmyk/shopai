"""Episode retriever — rich situation retrieval over episodic memory.

The existing ``episodic_memory`` stores per-decision outcomes. This
module is the *query side*: given a query situation, return the top-k
most relevant past *episodes* (not just cases) ranked by similarity
and recency, filtered by tags or outcome.

An *Episode* bundles a full mini-timeline:

    (id, situation, timeline, tags, outcome_sign, ts, source)

where ``timeline`` is an ordered list of terse event summaries. So
retrieval returns something readable — "here's what happened the last
5 times you launched an audio product under $30" — not raw blobs.

Pure stdlib, SQLite-persisted, deterministic. Complements
case_based_reasoner (atomic case KNN) by trading per-feature fidelity
for narrative context.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.episode_retriever")


OutcomeSign = Literal["win", "loss", "mixed", "unknown"]


@dataclass
class EpisodeEvent:
    kind: str
    summary: str
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "ts": self.ts,
        }


@dataclass
class Episode:
    id: str
    situation: dict[str, Any]
    timeline: list[EpisodeEvent] = field(default_factory=list)
    tags: tuple[str, ...] = ()
    outcome_sign: OutcomeSign = "unknown"
    ts: float = 0.0
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "situation": dict(self.situation),
            "timeline": [e.as_dict() for e in self.timeline],
            "tags": list(self.tags),
            "outcome_sign": self.outcome_sign,
            "ts": self.ts,
            "source": self.source,
        }


@dataclass
class Match:
    episode: Episode
    similarity: float
    recency_weight: float
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "episode": self.episode.as_dict(),
            "similarity": round(self.similarity, 4),
            "recency_weight": round(self.recency_weight, 4),
            "score": round(self.score, 4),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id            TEXT PRIMARY KEY,
    situation     TEXT NOT NULL DEFAULT '{}',
    timeline      TEXT NOT NULL DEFAULT '[]',
    tags_csv      TEXT NOT NULL DEFAULT '',
    outcome_sign  TEXT NOT NULL DEFAULT 'unknown',
    ts            REAL NOT NULL,
    source        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ep_ts ON episodes(ts);
CREATE INDEX IF NOT EXISTS idx_ep_outcome ON episodes(outcome_sign);
"""


# ── Similarity helpers ────────────────────────────────────

def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _similarity(
    a: dict[str, Any], b: dict[str, Any],
    scales: dict[str, float],
) -> float:
    keys = set(a.keys()) | set(b.keys())
    if not keys:
        return 0.0
    total = 0.0
    for k in keys:
        va, vb = a.get(k), b.get(k)
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


def _compute_scales(
    episodes: list[Episode],
) -> dict[str, float]:
    per_key: dict[str, list[float]] = {}
    for ep in episodes:
        for k, v in ep.situation.items():
            if _is_number(v):
                per_key.setdefault(k, []).append(float(v))
    scales: dict[str, float] = {}
    for k, vs in per_key.items():
        if not vs:
            continue
        hi, lo = max(vs), min(vs)
        scales[k] = hi - lo if hi > lo else max(abs(hi), 1.0)
    return scales


# ── Engine ────────────────────────────────────────────────

class EpisodeRetriever:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        half_life_days: float = 14.0,
    ) -> None:
        if half_life_days <= 0:
            raise ValueError("half_life_days must be positive")
        self._lock = threading.Lock()
        self._half_life_s = float(half_life_days) * 86_400.0
        self._episodes: dict[str, Episode] = {}
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
                "SELECT id, situation, timeline, tags_csv, "
                "outcome_sign, ts, source FROM episodes",
            ):
                try:
                    situation = json.loads(row[1] or "{}")
                    timeline_raw = json.loads(row[2] or "[]")
                except (json.JSONDecodeError, ValueError):
                    continue
                tags = tuple(
                    t for t in (row[3] or "").split(",") if t
                )
                timeline = [
                    EpisodeEvent(
                        kind=str(ev.get("kind", "")),
                        summary=str(ev.get("summary", "")),
                        ts=float(ev.get("ts", 0.0) or 0.0),
                    )
                    for ev in timeline_raw
                    if isinstance(ev, dict)
                ]
                self._episodes[row[0]] = Episode(
                    id=row[0], situation=situation,
                    timeline=timeline, tags=tags,
                    outcome_sign=row[4],
                    ts=float(row[5]),
                    source=row[6] or "",
                )

    # ── Record ───────────────────────────────────────────

    def record(
        self,
        situation: dict[str, Any],
        timeline: Iterable[EpisodeEvent] | Iterable[dict[str, Any]] = (),
        *,
        tags: Iterable[str] = (),
        outcome_sign: OutcomeSign = "unknown",
        source: str = "",
        episode_id: str | None = None,
    ) -> Episode:
        if outcome_sign not in ("win", "loss", "mixed", "unknown"):
            raise ValueError(
                "outcome_sign must be win|loss|mixed|unknown",
            )
        eid = episode_id or uuid.uuid4().hex
        events: list[EpisodeEvent] = []
        for ev in timeline or ():
            if isinstance(ev, EpisodeEvent):
                events.append(ev)
            elif isinstance(ev, dict):
                events.append(EpisodeEvent(
                    kind=str(ev.get("kind", "")),
                    summary=str(ev.get("summary", "")),
                    ts=float(ev.get("ts", 0.0) or 0.0),
                ))
        tag_tuple = tuple(
            str(t).strip() for t in tags if str(t).strip()
        )
        ep = Episode(
            id=eid,
            situation=dict(situation or {}),
            timeline=events,
            tags=tag_tuple,
            outcome_sign=outcome_sign,
            ts=time.time(),
            source=str(source),
        )
        with self._lock:
            self._episodes[eid] = ep
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO episodes("
                    "  id, situation, timeline, tags_csv, "
                    "  outcome_sign, ts, source"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        ep.id,
                        json.dumps(ep.situation, sort_keys=True),
                        json.dumps(
                            [e.as_dict() for e in ep.timeline],
                        ),
                        ",".join(ep.tags),
                        ep.outcome_sign,
                        ep.ts,
                        ep.source,
                    ),
                )
                self._conn.commit()
        return ep

    # ── Retrieval ────────────────────────────────────────

    def _recency_weight(self, ts: float, now: float) -> float:
        age = max(0.0, now - ts)
        return 0.5 ** (age / self._half_life_s)

    def _filtered(
        self,
        tags: Iterable[str] = (),
        outcome_sign: OutcomeSign | None = None,
    ) -> list[Episode]:
        tag_set = {str(t) for t in tags if str(t)}
        with self._lock:
            eps = list(self._episodes.values())
        out: list[Episode] = []
        for ep in eps:
            if tag_set and not tag_set.issubset(set(ep.tags)):
                continue
            if outcome_sign is not None and ep.outcome_sign != outcome_sign:
                continue
            out.append(ep)
        return out

    def find_similar(
        self,
        query_situation: dict[str, Any],
        *,
        k: int = 5,
        tags: Iterable[str] = (),
        outcome_sign: OutcomeSign | None = None,
        now: float | None = None,
    ) -> list[Match]:
        pool = self._filtered(tags=tags, outcome_sign=outcome_sign)
        if not pool:
            return []
        scales = _compute_scales(pool)
        now = now if now is not None else time.time()
        matches: list[Match] = []
        for ep in pool:
            sim = _similarity(query_situation, ep.situation, scales)
            rw = self._recency_weight(ep.ts, now)
            matches.append(Match(
                episode=ep, similarity=sim,
                recency_weight=rw,
                score=sim * rw,
            ))
        matches.sort(key=lambda m: -m.score)
        return matches[:max(1, int(k))]

    def recent(
        self,
        *,
        k: int = 10,
        tags: Iterable[str] = (),
        outcome_sign: OutcomeSign | None = None,
    ) -> list[Episode]:
        pool = self._filtered(tags=tags, outcome_sign=outcome_sign)
        pool.sort(key=lambda e: -e.ts)
        return pool[:max(1, int(k))]

    def by_outcome(
        self,
        outcome_sign: OutcomeSign,
        *,
        k: int = 5,
        tags: Iterable[str] = (),
    ) -> list[Episode]:
        return self.recent(
            k=k, tags=tags, outcome_sign=outcome_sign,
        )

    # ── Maintenance ──────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            eps = list(self._episodes.values())
        by_outcome: dict[str, int] = {}
        for e in eps:
            by_outcome[e.outcome_sign] = (
                by_outcome.get(e.outcome_sign, 0) + 1
            )
        all_tags: set[str] = set()
        for e in eps:
            all_tags.update(e.tags)
        return {
            "total": len(eps),
            "by_outcome": by_outcome,
            "distinct_tags": len(all_tags),
        }

    def prune_before(self, cutoff_ts: float) -> int:
        with self._lock:
            drop = [
                eid for eid, ep in self._episodes.items()
                if ep.ts < cutoff_ts
            ]
            for eid in drop:
                del self._episodes[eid]
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM episodes WHERE ts < ?",
                    (float(cutoff_ts),),
                )
                self._conn.commit()
        return len(drop)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
