"""Concept former — unsupervised event clustering → named concepts.

Facts that repeat with similar shape are *concepts waiting to be
named*. Until now the brain stored events as rows in the experience
ledger but never spotted that half the kill-decisions on audio ads
in the $20-$30 price band are one *kind of thing* worth naming.

Approach — pure-stdlib, deterministic, lightweight:

  1. Each event has a canonical key signature (sorted key=value
     pairs after dropping high-cardinality fields like timestamps
     and ids).
  2. Bucket by signature; any bucket with ≥ ``min_support`` events
     becomes a candidate concept.
  3. For each candidate, compute stability metrics (sample count,
     first/last ts, optional outcome-sign majority) and emit a
     ``FormedConcept``.
  4. Callers can name a formed concept via ``name_concept``; future
     retrievals use the stable id.

This complements ``skill_distiller`` (which looks at (situation,
action, outcome) for skill candidates) and ``analogy_mapper`` (which
matches structural templates) by operating on a *flat* event stream
and finding clusters before any decision is made.

SQLite-persisted, pure stdlib, deterministic.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("memory.concept_former")


_DEFAULT_DROP = (
    "ts", "id", "event_id", "cycle_id",
    "created_at", "updated_at", "uuid",
)


@dataclass
class FormedConcept:
    id: str
    signature: str
    examples_signature: dict[str, Any]
    support: int
    first_ts: float
    last_ts: float
    outcome_sign_counts: dict[str, int] = field(default_factory=dict)
    label: str = ""      # owner-assigned / auto-generated

    @property
    def majority_outcome(self) -> str | None:
        if not self.outcome_sign_counts:
            return None
        return max(
            self.outcome_sign_counts.items(),
            key=lambda kv: kv[1],
        )[0]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "signature": self.signature,
            "examples_signature": dict(self.examples_signature),
            "support": self.support,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "outcome_sign_counts": dict(self.outcome_sign_counts),
            "majority_outcome": self.majority_outcome,
            "label": self.label,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    signature     TEXT NOT NULL,
    fields_json   TEXT NOT NULL,
    outcome_sign  TEXT NOT NULL DEFAULT '',
    ts            REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_sig
    ON observations(signature);
CREATE TABLE IF NOT EXISTS concept_labels (
    id         TEXT PRIMARY KEY,
    signature  TEXT NOT NULL UNIQUE,
    label      TEXT NOT NULL,
    named_at   REAL NOT NULL
);
"""


def _canonicalise(
    fields: dict[str, Any],
    drop_keys: Iterable[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if k in drop_keys:
            continue
        if isinstance(v, float):
            out[k] = round(v, 4)
        else:
            out[k] = v
    return dict(sorted(out.items()))


def _signature_of(canonical_fields: dict[str, Any]) -> str:
    return "|".join(
        f"{k}={_stringify(v)}" for k, v in canonical_fields.items()
    )


def _stringify(v: Any) -> str:
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(_stringify(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(
            f"{k}:{_stringify(vv)}"
            for k, vv in sorted(v.items())
        ) + "}"
    return str(v)


class ConceptFormer:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        drop_keys: Iterable[str] = _DEFAULT_DROP,
    ) -> None:
        self._lock = threading.Lock()
        self._drop_keys = tuple(drop_keys)
        self._conn: sqlite3.Connection | None = None
        # In-memory cache keyed by signature → list of (ts, outcome)
        self._observations: dict[
            str, list[tuple[float, str, dict[str, Any]]]
        ] = defaultdict(list)
        self._labels: dict[str, tuple[str, str]] = {}
        # signature → (concept_id, label)
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
                "SELECT signature, fields_json, outcome_sign, ts "
                "FROM observations ORDER BY ts ASC",
            ):
                try:
                    fields = json.loads(row[1] or "{}")
                except (json.JSONDecodeError, ValueError):
                    continue
                self._observations[row[0]].append(
                    (float(row[3]), str(row[2] or ""), fields),
                )
            for row in self._conn.execute(
                "SELECT id, signature, label FROM concept_labels",
            ):
                self._labels[row[1]] = (row[0], row[2])

    # ── Intake ────────────────────────────────────────────

    def observe(
        self,
        fields: dict[str, Any],
        *,
        outcome_sign: str = "",
        ts: float | None = None,
    ) -> str:
        """Record one observation. Returns the canonical signature."""
        if not fields:
            raise ValueError("fields required")
        canonical = _canonicalise(fields, self._drop_keys)
        signature = _signature_of(canonical)
        timestamp = float(ts if ts is not None else time.time())
        with self._lock:
            self._observations[signature].append(
                (timestamp, str(outcome_sign or ""), canonical),
            )
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO observations"
                    "(signature, fields_json, outcome_sign, ts) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        signature,
                        json.dumps(canonical, sort_keys=True),
                        str(outcome_sign or ""),
                        timestamp,
                    ),
                )
                self._conn.commit()
        return signature

    # ── Form concepts ────────────────────────────────────

    def form(
        self,
        *,
        min_support: int = 3,
    ) -> list[FormedConcept]:
        if min_support < 1:
            raise ValueError("min_support must be ≥ 1")
        out: list[FormedConcept] = []
        with self._lock:
            items = list(self._observations.items())
            labels = dict(self._labels)
        for signature, entries in items:
            if len(entries) < min_support:
                continue
            entries_sorted = sorted(entries, key=lambda e: e[0])
            first_ts = entries_sorted[0][0]
            last_ts = entries_sorted[-1][0]
            counts: dict[str, int] = {}
            for _, outcome, _ in entries:
                if not outcome:
                    continue
                counts[outcome] = counts.get(outcome, 0) + 1
            examples = entries_sorted[0][2]
            cid, label = labels.get(
                signature,
                (f"concept_{uuid.uuid4().hex[:8]}", ""),
            )
            out.append(FormedConcept(
                id=cid,
                signature=signature,
                examples_signature=examples,
                support=len(entries),
                first_ts=first_ts,
                last_ts=last_ts,
                outcome_sign_counts=counts,
                label=label,
            ))
        out.sort(key=lambda c: -c.support)
        return out

    # ── Label ────────────────────────────────────────────

    def name_concept(
        self,
        signature: str,
        label: str,
    ) -> str:
        if not signature:
            raise ValueError("signature required")
        if not label:
            raise ValueError("label required")
        with self._lock:
            existing = self._labels.get(signature)
            cid = existing[0] if existing else (
                f"concept_{uuid.uuid4().hex[:8]}"
            )
            self._labels[signature] = (cid, label)
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO concept_labels"
                    "(id, signature, label, named_at) "
                    "VALUES (?, ?, ?, ?)",
                    (cid, signature, label, time.time()),
                )
                self._conn.commit()
        return cid

    def labelled_concepts(self) -> list[FormedConcept]:
        all_concepts = self.form(min_support=1)
        return [c for c in all_concepts if c.label]

    # ── Stats / maintenance ──────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = sum(
                len(v) for v in self._observations.values()
            )
            distinct = len(self._observations)
            named = len(self._labels)
        return {
            "total_observations": total,
            "distinct_signatures": distinct,
            "named_concepts": named,
        }

    def reset(self) -> int:
        with self._lock:
            n = sum(
                len(v) for v in self._observations.values()
            )
            self._observations.clear()
            self._labels.clear()
            if self._conn is not None:
                self._conn.execute("DELETE FROM observations")
                self._conn.execute("DELETE FROM concept_labels")
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
