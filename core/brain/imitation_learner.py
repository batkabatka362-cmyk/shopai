"""Imitation learner — learn from observed successful sequences.

Classic brain learning is *outcome-driven*: the brain ran action A,
saw outcome O, and updated beliefs. Imitation learning adds a second
channel: the brain sees *someone else* (or its own historical log)
execute a successful sequence and extracts the shape for reuse —
**without** having to re-run it.

Input: a demonstration with:

  • situation_fingerprint — dict of canonical fields describing
    the initial state (e.g. {"niche":"pet","aov":"$40-$60"})
  • action_sequence — ordered list of actions (dicts)
  • outcome_quality — 0..1 how successful
  • source — "self" | "peer_store" | "public_case_study"

Output: ``ImitationTemplate`` — signature, canonical sequence,
count_observed, avg_quality, last_seen_ts. Templates with low
diversity (same actions repeated N times) gain confidence; templates
where one action gets swapped out get *variant* entries so the
library captures the canonical *and* the acceptable alternatives.

``match(situation)`` finds the best-matching template by Jaccard over
situation keys.

Pure stdlib, SQLite-persisted, deterministic.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.imitation_learner")


@dataclass
class ImitationTemplate:
    id: str
    signature: str
    situation_fields: dict[str, Any]
    action_sequence: list[dict[str, Any]]
    count_observed: int
    total_quality: float
    source_counts: dict[str, int]
    first_seen_ts: float
    last_seen_ts: float

    @property
    def avg_quality(self) -> float:
        return (
            self.total_quality / self.count_observed
            if self.count_observed > 0 else 0.0
        )

    @property
    def dominant_source(self) -> str:
        if not self.source_counts:
            return ""
        return max(
            self.source_counts.items(), key=lambda kv: kv[1],
        )[0]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "signature": self.signature,
            "situation_fields": dict(self.situation_fields),
            "action_sequence": [
                dict(a) for a in self.action_sequence
            ],
            "count_observed": self.count_observed,
            "avg_quality": round(self.avg_quality, 4),
            "dominant_source": self.dominant_source,
            "source_counts": dict(self.source_counts),
            "first_seen_ts": self.first_seen_ts,
            "last_seen_ts": self.last_seen_ts,
        }


@dataclass
class MatchResult:
    template: ImitationTemplate
    similarity: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "template": self.template.as_dict(),
            "similarity": round(self.similarity, 4),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS imitation_templates (
    id                TEXT PRIMARY KEY,
    signature         TEXT NOT NULL UNIQUE,
    situation_json    TEXT NOT NULL,
    sequence_json     TEXT NOT NULL,
    count_observed    INTEGER NOT NULL,
    total_quality     REAL NOT NULL,
    source_counts_json TEXT NOT NULL,
    first_seen_ts     REAL NOT NULL,
    last_seen_ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_imi_sig
    ON imitation_templates(signature);
"""


def _canonical_sequence(
    actions: list[dict[str, Any]],
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    """Return (kind_tuple, stripped_sequence).

    Canonical form drops timestamps/ids and keeps {kind, ...args}
    sorted. kind_tuple is used for signature matching.
    """
    kinds: list[str] = []
    stripped: list[dict[str, Any]] = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        kind = str(a.get("kind") or a.get("type") or "")
        kinds.append(kind)
        clean: dict[str, Any] = {}
        for k, v in sorted(a.items()):
            if k in ("ts", "timestamp", "id", "uuid"):
                continue
            clean[k] = v
        stripped.append(clean)
    return tuple(kinds), stripped


def _signature_of(
    situation_fields: dict[str, Any],
    kinds: tuple[str, ...],
) -> str:
    sit = "|".join(
        f"{k}={situation_fields[k]}"
        for k in sorted(situation_fields.keys())
    )
    seq = ">".join(kinds)
    return f"SIT[{sit}]ACT[{seq}]"


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


class ImitationLearner:
    def __init__(
        self, db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._templates: dict[str, ImitationTemplate] = {}
        # keyed by id
        self._by_signature: dict[str, str] = {}   # sig → id
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
                "SELECT id, signature, situation_json, "
                "sequence_json, count_observed, total_quality, "
                "source_counts_json, first_seen_ts, last_seen_ts "
                "FROM imitation_templates",
            ):
                try:
                    situation = json.loads(row[2])
                    sequence = json.loads(row[3])
                    sources = json.loads(row[6])
                except (json.JSONDecodeError, ValueError):
                    continue
                tpl = ImitationTemplate(
                    id=row[0],
                    signature=row[1],
                    situation_fields=situation,
                    action_sequence=sequence,
                    count_observed=int(row[4]),
                    total_quality=float(row[5]),
                    source_counts=sources,
                    first_seen_ts=float(row[7]),
                    last_seen_ts=float(row[8]),
                )
                self._templates[tpl.id] = tpl
                self._by_signature[tpl.signature] = tpl.id

    def _persist(self, tpl: ImitationTemplate) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO imitation_templates("
            "  id, signature, situation_json, sequence_json, "
            "  count_observed, total_quality, source_counts_json, "
            "  first_seen_ts, last_seen_ts"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tpl.id, tpl.signature,
                json.dumps(tpl.situation_fields, sort_keys=True),
                json.dumps(tpl.action_sequence, sort_keys=True),
                tpl.count_observed, tpl.total_quality,
                json.dumps(tpl.source_counts, sort_keys=True),
                tpl.first_seen_ts, tpl.last_seen_ts,
            ),
        )
        self._conn.commit()

    # ── Intake ───────────────────────────────────────────

    def observe(
        self,
        *,
        situation_fields: dict[str, Any],
        action_sequence: list[dict[str, Any]],
        outcome_quality: float,
        source: str = "self",
        ts: float | None = None,
    ) -> ImitationTemplate:
        if not action_sequence:
            raise ValueError("action_sequence required")
        if not 0.0 <= outcome_quality <= 1.0:
            raise ValueError(
                "outcome_quality must be in [0, 1]",
            )
        timestamp = float(ts if ts is not None else time.time())
        kinds, stripped = _canonical_sequence(action_sequence)
        signature = _signature_of(
            dict(situation_fields or {}), kinds,
        )
        src = source or "unknown"
        with self._lock:
            existing_id = self._by_signature.get(signature)
            if existing_id is not None:
                tpl = self._templates[existing_id]
                tpl.count_observed += 1
                tpl.total_quality += float(outcome_quality)
                tpl.source_counts[src] = (
                    tpl.source_counts.get(src, 0) + 1
                )
                tpl.last_seen_ts = timestamp
            else:
                tpl = ImitationTemplate(
                    id=uuid.uuid4().hex,
                    signature=signature,
                    situation_fields=dict(situation_fields or {}),
                    action_sequence=stripped,
                    count_observed=1,
                    total_quality=float(outcome_quality),
                    source_counts={src: 1},
                    first_seen_ts=timestamp,
                    last_seen_ts=timestamp,
                )
                self._templates[tpl.id] = tpl
                self._by_signature[signature] = tpl.id
            self._persist(tpl)
            return tpl

    # ── Match ────────────────────────────────────────────

    def match(
        self,
        situation: dict[str, Any],
        *,
        min_count: int = 1,
        min_quality: float = 0.0,
    ) -> MatchResult | None:
        if not situation:
            return None
        target_keys = {
            f"{k}={v}" for k, v in situation.items()
        }
        best: MatchResult | None = None
        with self._lock:
            templates = list(self._templates.values())
        for tpl in templates:
            if tpl.count_observed < min_count:
                continue
            if tpl.avg_quality < min_quality:
                continue
            tpl_keys = {
                f"{k}={v}" for k, v in tpl.situation_fields.items()
            }
            sim = _jaccard(target_keys, tpl_keys)
            if sim <= 0:
                continue
            if best is None or sim > best.similarity or (
                sim == best.similarity
                and tpl.avg_quality > best.template.avg_quality
            ):
                best = MatchResult(template=tpl, similarity=sim)
        return best

    def top(
        self, *, limit: int = 10,
    ) -> list[ImitationTemplate]:
        with self._lock:
            templates = list(self._templates.values())
        templates.sort(
            key=lambda t: (
                -t.avg_quality, -t.count_observed,
                -t.last_seen_ts,
            ),
        )
        return templates[: max(1, int(limit))]

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_obs = sum(
                t.count_observed for t in self._templates.values()
            )
            return {
                "templates": len(self._templates),
                "total_observations": total_obs,
                "sources": sorted({
                    s
                    for t in self._templates.values()
                    for s in t.source_counts
                }),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._templates)
            self._templates.clear()
            self._by_signature.clear()
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM imitation_templates",
                )
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
