"""Shadow divergence — compare legacy vs facade decisions.

SHOPAI_BRAIN_SHADOW mode runs the legacy ``DecisionBrain.think()``
AND the new facade path side-by-side without letting the new path
actually touch production. shadow_divergence consumes those paired
results and scores:

  • ``agrees``           — both paths picked the same action_kind
  • ``kind_mismatch``    — different action kinds → investigate
  • ``legacy_only``      — legacy picked an action, facade skipped
  • ``facade_only``      — facade picked an action, legacy skipped
  • ``both_empty``       — neither path produced an action

Each comparison is stored with the context so a batch ``summary()``
can report agreement rate, most-common divergence pattern, and a
sample of divergent cases.

The purpose is *evidence*: before flipping SHOPAI_BRAIN_SHADOW off
and routing decisions through the facade, you want hard numbers on
whether the facade and legacy agree often enough. Pure stdlib,
SQLite-persisted, deterministic.
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


logger = get_logger("brain.shadow_divergence")


Verdict = Literal[
    "agrees", "kind_mismatch",
    "legacy_only", "facade_only", "both_empty",
]


@dataclass
class Divergence:
    id: str
    ts: float
    context_summary: dict[str, Any]
    legacy_action_kind: str
    facade_action_kind: str
    verdict: Verdict
    legacy_note: str = ""
    facade_note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "context_summary": dict(self.context_summary),
            "legacy_action_kind": self.legacy_action_kind,
            "facade_action_kind": self.facade_action_kind,
            "verdict": self.verdict,
            "legacy_note": self.legacy_note,
            "facade_note": self.facade_note,
        }


@dataclass
class DivergenceSummary:
    total: int
    agreement_rate: float
    by_verdict: dict[str, int]
    sample_divergent: list[Divergence]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "agreement_rate": round(self.agreement_rate, 4),
            "by_verdict": dict(self.by_verdict),
            "sample_divergent": [
                s.as_dict() for s in self.sample_divergent
            ],
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS divergences (
    id                   TEXT PRIMARY KEY,
    ts                   REAL NOT NULL,
    context_summary      TEXT NOT NULL DEFAULT '{}',
    legacy_action_kind   TEXT NOT NULL DEFAULT '',
    facade_action_kind   TEXT NOT NULL DEFAULT '',
    verdict              TEXT NOT NULL,
    legacy_note          TEXT NOT NULL DEFAULT '',
    facade_note          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_div_ts
    ON divergences(ts);
CREATE INDEX IF NOT EXISTS idx_div_verdict
    ON divergences(verdict);
"""


def _classify(
    legacy_kind: str, facade_kind: str,
) -> Verdict:
    if legacy_kind and facade_kind:
        return "agrees" if legacy_kind == facade_kind else "kind_mismatch"
    if legacy_kind and not facade_kind:
        return "legacy_only"
    if facade_kind and not legacy_kind:
        return "facade_only"
    return "both_empty"


class ShadowDivergence:
    def __init__(
        self,
        db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._records: list[Divergence] = []
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
                "SELECT id, ts, context_summary, legacy_action_kind, "
                "facade_action_kind, verdict, legacy_note, facade_note "
                "FROM divergences ORDER BY ts ASC",
            ):
                try:
                    ctx = json.loads(row[2] or "{}")
                except (json.JSONDecodeError, ValueError):
                    ctx = {}
                self._records.append(Divergence(
                    id=row[0], ts=float(row[1]),
                    context_summary=ctx,
                    legacy_action_kind=row[3],
                    facade_action_kind=row[4],
                    verdict=row[5],
                    legacy_note=row[6] or "",
                    facade_note=row[7] or "",
                ))

    # ── Record ───────────────────────────────────────────

    def record(
        self,
        *,
        context_summary: dict[str, Any],
        legacy_action: dict[str, Any] | None,
        facade_action: dict[str, Any] | None,
        legacy_note: str = "",
        facade_note: str = "",
    ) -> Divergence:
        legacy_kind = (
            str(legacy_action.get("kind", ""))
            if legacy_action else ""
        )
        facade_kind = (
            str(facade_action.get("kind", ""))
            if facade_action else ""
        )
        verdict = _classify(legacy_kind, facade_kind)
        div = Divergence(
            id=uuid.uuid4().hex,
            ts=time.time(),
            context_summary=dict(context_summary or {}),
            legacy_action_kind=legacy_kind,
            facade_action_kind=facade_kind,
            verdict=verdict,
            legacy_note=str(legacy_note),
            facade_note=str(facade_note),
        )
        with self._lock:
            self._records.append(div)
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO divergences("
                    "  id, ts, context_summary, "
                    "  legacy_action_kind, facade_action_kind, "
                    "  verdict, legacy_note, facade_note"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        div.id, div.ts,
                        json.dumps(
                            div.context_summary, sort_keys=True,
                        ),
                        div.legacy_action_kind,
                        div.facade_action_kind,
                        div.verdict,
                        div.legacy_note,
                        div.facade_note,
                    ),
                )
                self._conn.commit()
        return div

    # ── Summary ──────────────────────────────────────────

    def summary(
        self,
        *,
        lookback_s: float | None = None,
        sample_size: int = 5,
    ) -> DivergenceSummary:
        with self._lock:
            records = list(self._records)
        if lookback_s is not None:
            cutoff = time.time() - float(lookback_s)
            records = [r for r in records if r.ts >= cutoff]
        total = len(records)
        by_verdict: dict[str, int] = {}
        for r in records:
            by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1
        agrees = by_verdict.get("agrees", 0)
        rate = (agrees / total) if total > 0 else 0.0
        divergent = [r for r in records if r.verdict != "agrees"]
        # Newest-first sample
        divergent.sort(key=lambda r: -r.ts)
        return DivergenceSummary(
            total=total,
            agreement_rate=rate,
            by_verdict=by_verdict,
            sample_divergent=divergent[: max(0, int(sample_size))],
        )

    def recent(
        self, limit: int = 50,
    ) -> list[Divergence]:
        with self._lock:
            rs = list(self._records)
        rs.sort(key=lambda r: -r.ts)
        return rs[: max(1, int(limit))]

    # ── Maintenance ──────────────────────────────────────

    def clear(self) -> int:
        with self._lock:
            n = len(self._records)
            self._records.clear()
            if self._conn is not None:
                self._conn.execute("DELETE FROM divergences")
                self._conn.commit()
        return n

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total": len(self._records),
            }

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
