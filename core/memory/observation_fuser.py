"""Observation fuser — reconcile same-event reports across sources.

Shopify says order 8824 was placed at 14:22 for $47.50. Meta pixel
logged a conversion at 14:22:03 for $47.49. GA says the same unit
hit a thank-you page at 14:22:07. Bank feed confirms a $47.50 deposit
at 14:25. *These are all the same event* — we must not count four
orders.

The fuser groups raw reports by a ``fusion_key`` (usually an external
order id or a structural hash of fields), weights each report by
its source trust, and emits one ``FusedObservation`` per group with:

  • a consensus value per field (Bayesian-ish weighted vote)
  • a list of contributing sources + their confidences
  • a reconciliation note if sources disagreed

Source trust is injected (typically ``trust_calibrator.trust``). Pure
stdlib. Deterministic. SQLite-persisted when db_path provided.
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
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("memory.observation_fuser")


@dataclass
class Report:
    source: str
    fusion_key: str
    payload: dict[str, Any]
    confidence: float = 1.0
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "fusion_key": self.fusion_key,
            "payload": dict(self.payload),
            "confidence": round(self.confidence, 4),
            "ts": self.ts,
        }


@dataclass
class FieldConsensus:
    value: Any
    weight: float
    agreement: float        # fraction of weight behind this value
    voters: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "weight": round(self.weight, 4),
            "agreement": round(self.agreement, 4),
            "voters": list(self.voters),
        }


@dataclass
class FusedObservation:
    id: str
    fusion_key: str
    fields: dict[str, FieldConsensus]
    sources: list[str] = field(default_factory=list)
    reconciliation_note: str = ""
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fusion_key": self.fusion_key,
            "fields": {
                k: v.as_dict() for k, v in self.fields.items()
            },
            "sources": list(self.sources),
            "reconciliation_note": self.reconciliation_note,
            "ts": self.ts,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    fusion_key   TEXT NOT NULL,
    payload      TEXT NOT NULL,
    confidence   REAL NOT NULL DEFAULT 1.0,
    ts           REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_key
    ON raw_reports(fusion_key);
"""


def _value_key(v: Any) -> str:
    if isinstance(v, float):
        return f"{round(v, 4)}"
    return str(v)


class ObservationFuser:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        trust_fn: Callable[[str], float] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._trust_fn = trust_fn
        self._reports: dict[str, list[Report]] = defaultdict(list)
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
                "SELECT source, fusion_key, payload, confidence, ts "
                "FROM raw_reports ORDER BY ts ASC",
            ):
                try:
                    payload = json.loads(row[2] or "{}")
                except (json.JSONDecodeError, ValueError):
                    continue
                self._reports[row[1]].append(Report(
                    source=row[0],
                    fusion_key=row[1],
                    payload=payload,
                    confidence=float(row[3]),
                    ts=float(row[4]),
                ))

    # ── Intake ────────────────────────────────────────────

    def report(
        self,
        *,
        source: str,
        fusion_key: str,
        payload: dict[str, Any],
        confidence: float = 1.0,
        ts: float | None = None,
    ) -> Report:
        if not source or not fusion_key:
            raise ValueError("source and fusion_key required")
        conf = max(0.0, min(1.0, float(confidence)))
        rec = Report(
            source=str(source),
            fusion_key=str(fusion_key),
            payload=dict(payload or {}),
            confidence=conf,
            ts=float(ts if ts is not None else time.time()),
        )
        with self._lock:
            self._reports[rec.fusion_key].append(rec)
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO raw_reports"
                    "(source, fusion_key, payload, confidence, ts) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        rec.source, rec.fusion_key,
                        json.dumps(rec.payload, sort_keys=True),
                        rec.confidence, rec.ts,
                    ),
                )
                self._conn.commit()
        return rec

    # ── Trust lookup ─────────────────────────────────────

    def _trust(self, source: str) -> float:
        if self._trust_fn is None:
            return 1.0
        try:
            return max(0.0, min(1.0, float(self._trust_fn(source))))
        except Exception as exc:
            logger.debug(
                "trust_fn %s raised: %s", source, exc,
            )
            return 1.0

    # ── Fuse ─────────────────────────────────────────────

    def fuse(self, fusion_key: str) -> FusedObservation | None:
        with self._lock:
            reports = list(self._reports.get(fusion_key, []))
        if not reports:
            return None

        # Per-field voting
        per_field: dict[
            str, dict[str, tuple[float, set[str]]]
        ] = defaultdict(lambda: defaultdict(
            lambda: (0.0, set()),
        ))
        # we'll track value -> (total_weight, voters)
        per_field_typed: dict[
            str, dict[str, tuple[float, set[str], Any]]
        ] = defaultdict(dict)

        for r in reports:
            w = self._trust(r.source) * r.confidence
            if w <= 0:
                continue
            for field_name, value in r.payload.items():
                key = _value_key(value)
                cur = per_field_typed[field_name].get(
                    key, (0.0, set(), value),
                )
                per_field_typed[field_name][key] = (
                    cur[0] + w,
                    cur[1] | {r.source},
                    value,
                )

        fields: dict[str, FieldConsensus] = {}
        any_disagreement = False
        for field_name, candidates in per_field_typed.items():
            # Sort descending by weight
            ranked = sorted(
                candidates.items(),
                key=lambda kv: -kv[1][0],
            )
            if not ranked:
                continue
            total_weight = sum(v[0] for _, v in ranked) or 1.0
            top_key, (top_w, voters, top_val) = ranked[0]
            agreement = top_w / total_weight
            fields[field_name] = FieldConsensus(
                value=top_val,
                weight=top_w,
                agreement=agreement,
                voters=sorted(voters),
            )
            if len(ranked) > 1:
                any_disagreement = True

        sources_list = sorted({r.source for r in reports})
        note = "agreement" if not any_disagreement else (
            "reconciled by weighted vote; disagreement observed"
        )
        return FusedObservation(
            id=uuid.uuid4().hex,
            fusion_key=fusion_key,
            fields=fields,
            sources=sources_list,
            reconciliation_note=note,
            ts=max((r.ts for r in reports), default=0.0),
        )

    def fuse_all(self) -> list[FusedObservation]:
        with self._lock:
            keys = list(self._reports.keys())
        out: list[FusedObservation] = []
        for key in keys:
            fo = self.fuse(key)
            if fo is not None:
                out.append(fo)
        return out

    def disagreements(
        self, *, min_sources: int = 2,
    ) -> list[FusedObservation]:
        return [
            f for f in self.fuse_all()
            if len(f.sources) >= min_sources
            and "disagreement" in f.reconciliation_note
        ]

    # ── Maintenance ──────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = sum(
                len(v) for v in self._reports.values()
            )
        return {
            "keys": len(self._reports),
            "reports": total,
        }

    def reset(self, fusion_key: str | None = None) -> int:
        with self._lock:
            if fusion_key is None:
                n = sum(len(v) for v in self._reports.values())
                self._reports.clear()
                if self._conn is not None:
                    self._conn.execute(
                        "DELETE FROM raw_reports",
                    )
                    self._conn.commit()
                return n
            n = len(self._reports.pop(fusion_key, []))
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM raw_reports WHERE fusion_key=?",
                    (fusion_key,),
                )
                self._conn.commit()
            return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
