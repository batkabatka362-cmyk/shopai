"""Evidence accumulator — Bayesian evidence per claim over time.

Claims accumulate evidence slowly. Today's "winner" was yesterday's
"maybe"; tomorrow's "needs more data" is today's "promising". A
proper brain doesn't flip claims after one observation — it updates
a posterior.

Each claim has a Beta(α, β) posterior over "probability the claim
is true". Evidence comes in as (weight, polarity):

  • polarity=+1 (supports claim)  → α += weight
  • polarity=−1 (contradicts)     → β += weight

Prior defaults to Beta(1, 1) = uniform. Queries:

  • ``probability(claim_id)``      — mean of Beta
  • ``credible_interval(..., q)``  — Beta-approximate CI
  • ``evidence_gap(claim_id)``     — 1 / (α + β), shrinks with data
  • ``strongest_supports/contras`` — which evidence items drove it

Pure stdlib, SQLite-persisted, deterministic.
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
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.evidence_accumulator")


Polarity = Literal["support", "contradict"]


@dataclass
class EvidenceItem:
    id: str
    claim_id: str
    polarity: Polarity
    weight: float               # 0..1
    source: str
    note: str
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim_id": self.claim_id,
            "polarity": self.polarity,
            "weight": round(self.weight, 4),
            "source": self.source,
            "note": self.note,
            "ts": self.ts,
        }


@dataclass
class ClaimPosterior:
    claim_id: str
    statement: str
    alpha: float
    beta: float
    n_items: int

    @property
    def probability(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def evidence_gap(self) -> float:
        return 1.0 / (self.alpha + self.beta)

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "alpha": round(self.alpha, 4),
            "beta": round(self.beta, 4),
            "n_items": self.n_items,
            "probability": round(self.probability, 4),
            "evidence_gap": round(self.evidence_gap, 4),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    id          TEXT PRIMARY KEY,
    statement   TEXT NOT NULL,
    alpha       REAL NOT NULL,
    beta        REAL NOT NULL,
    n_items     INTEGER NOT NULL,
    first_ts    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    id          TEXT PRIMARY KEY,
    claim_id    TEXT NOT NULL,
    polarity    TEXT NOT NULL,
    weight      REAL NOT NULL,
    source      TEXT NOT NULL,
    note        TEXT NOT NULL,
    ts          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ev_claim
    ON evidence(claim_id);
"""


def _beta_ci(
    alpha: float, beta: float, q: float = 0.95,
) -> tuple[float, float]:
    """Cheap normal-approximation CI centred on mean.

    Safe for alpha+beta > 5; good enough for relative judgments.
    """
    n = alpha + beta
    if n <= 0:
        return (0.0, 1.0)
    mean = alpha / n
    var = alpha * beta / (n * n * (n + 1))
    std = math.sqrt(max(var, 0.0))
    z = 1.96 if q >= 0.95 else 1.645 if q >= 0.9 else 1.0
    lo = max(0.0, mean - z * std)
    hi = min(1.0, mean + z * std)
    return (lo, hi)


class EvidenceAccumulator:
    def __init__(
        self,
        db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._claims: dict[str, ClaimPosterior] = {}
        self._evidence: dict[str, list[EvidenceItem]] = {}
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
                "SELECT id, statement, alpha, beta, n_items, "
                "first_ts FROM claims",
            ):
                self._claims[row[0]] = ClaimPosterior(
                    claim_id=row[0],
                    statement=row[1],
                    alpha=float(row[2]),
                    beta=float(row[3]),
                    n_items=int(row[4]),
                )
            for row in self._conn.execute(
                "SELECT id, claim_id, polarity, weight, source, "
                "note, ts FROM evidence",
            ):
                item = EvidenceItem(
                    id=row[0],
                    claim_id=row[1],
                    polarity=row[2],
                    weight=float(row[3]),
                    source=row[4],
                    note=row[5] or "",
                    ts=float(row[6]),
                )
                self._evidence.setdefault(
                    item.claim_id, [],
                ).append(item)

    # ── Register claim ──────────────────────────────────

    def register_claim(
        self,
        statement: str,
        *,
        claim_id: str | None = None,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> ClaimPosterior:
        if not statement:
            raise ValueError("statement required")
        if prior_alpha <= 0 or prior_beta <= 0:
            raise ValueError(
                "prior_alpha and prior_beta must be > 0",
            )
        cid = claim_id or uuid.uuid4().hex
        claim = ClaimPosterior(
            claim_id=cid,
            statement=statement,
            alpha=float(prior_alpha),
            beta=float(prior_beta),
            n_items=0,
        )
        with self._lock:
            if cid in self._claims:
                return self._claims[cid]
            self._claims[cid] = claim
            self._evidence[cid] = []
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO claims"
                    "(id, statement, alpha, beta, n_items, "
                    " first_ts) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        cid, statement, claim.alpha,
                        claim.beta, 0, time.time(),
                    ),
                )
                self._conn.commit()
        return claim

    # ── Add evidence ─────────────────────────────────────

    def add_evidence(
        self,
        *,
        claim_id: str,
        polarity: Polarity,
        weight: float = 1.0,
        source: str = "",
        note: str = "",
        ts: float | None = None,
    ) -> EvidenceItem:
        if polarity not in ("support", "contradict"):
            raise ValueError(
                "polarity must be support|contradict",
            )
        if not 0.0 <= weight <= 1.0:
            raise ValueError("weight must be in [0, 1]")
        timestamp = float(ts if ts is not None else time.time())
        with self._lock:
            claim = self._claims.get(claim_id)
            if claim is None:
                raise ValueError(
                    f"unknown claim {claim_id!r}",
                )
            item = EvidenceItem(
                id=uuid.uuid4().hex,
                claim_id=claim_id,
                polarity=polarity,
                weight=float(weight),
                source=str(source),
                note=str(note),
                ts=timestamp,
            )
            self._evidence[claim_id].append(item)
            claim.n_items += 1
            if polarity == "support":
                claim.alpha += float(weight)
            else:
                claim.beta += float(weight)
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO evidence"
                    "(id, claim_id, polarity, weight, source, "
                    " note, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.id, claim_id, polarity,
                        item.weight, item.source,
                        item.note, item.ts,
                    ),
                )
                self._conn.execute(
                    "UPDATE claims "
                    "SET alpha = ?, beta = ?, n_items = ? "
                    "WHERE id = ?",
                    (
                        claim.alpha, claim.beta,
                        claim.n_items, claim_id,
                    ),
                )
                self._conn.commit()
            return item

    # ── Queries ──────────────────────────────────────────

    def probability(self, claim_id: str) -> float:
        with self._lock:
            claim = self._claims.get(claim_id)
        if claim is None:
            return 0.0
        return claim.probability

    def credible_interval(
        self, claim_id: str, *, q: float = 0.95,
    ) -> tuple[float, float]:
        with self._lock:
            claim = self._claims.get(claim_id)
        if claim is None:
            return (0.0, 1.0)
        return _beta_ci(claim.alpha, claim.beta, q)

    def evidence_gap(self, claim_id: str) -> float:
        with self._lock:
            claim = self._claims.get(claim_id)
        if claim is None:
            return 1.0
        return claim.evidence_gap

    def strongest(
        self,
        claim_id: str,
        *,
        polarity: Polarity,
        limit: int = 5,
    ) -> list[EvidenceItem]:
        with self._lock:
            items = list(self._evidence.get(claim_id, ()))
        filtered = [
            e for e in items if e.polarity == polarity
        ]
        filtered.sort(key=lambda e: -e.weight)
        return filtered[: max(1, int(limit))]

    def posterior(
        self, claim_id: str,
    ) -> ClaimPosterior | None:
        with self._lock:
            return self._claims.get(claim_id)

    def claims(self) -> list[ClaimPosterior]:
        with self._lock:
            out = list(self._claims.values())
        out.sort(key=lambda c: -c.probability)
        return out

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_ev = sum(
                len(v) for v in self._evidence.values()
            )
            return {
                "claims": len(self._claims),
                "total_evidence": total_ev,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._claims)
            self._claims.clear()
            self._evidence.clear()
            if self._conn is not None:
                self._conn.execute("DELETE FROM claims")
                self._conn.execute("DELETE FROM evidence")
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
