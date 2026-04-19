"""Trust calibrator — per-source reliability weights.

The brain ingests information from many sources: Shopify API,
AutoDS feed, Alibaba scrape, competitor monitor, owner-typed
goals, LLM outputs, reviews. Each source has a *different* error
rate. Treating them equally means a noisy Alibaba scrape can
override a clean Shopify API read on the same question.

TrustCalibrator maintains a Beta(α, β) trust posterior per source.
Every time a source makes a claim that later gets verified (or
refuted) by ground truth, the posterior updates. The engine
exposes:

  update(source, correct)            → fold one outcome
  trust(source)                       → posterior mean in [0, 1]
  rank()                              → sources by trust descending
  weight(source, context=None)        → trust × context_affinity,
                                         useful for ensemble fusion
  consensus(claims)                   → weighted-majority result
  decay_stale(half_life_days)         → exponentially decay counts
                                         so ancient trust fades

Sources register with optional *priors* (beta α/β) so a trusted
vendor (Shopify API) starts high, a fresh scrape starts uniform.

Persistence: ``data/trust.db`` SQLite. Pure Python.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_DB_PATH = Path("data/trust.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    name         TEXT PRIMARY KEY,
    alpha        REAL NOT NULL DEFAULT 1.0,
    beta         REAL NOT NULL DEFAULT 1.0,
    kind         TEXT,
    last_update  REAL NOT NULL DEFAULT 0
);
"""


@dataclass
class SourceTrust:
    name: str
    alpha: float
    beta: float
    kind: str = ""
    last_update: float = 0.0

    @property
    def trust(self) -> float:
        total = self.alpha + self.beta
        return self.alpha / total if total > 0 else 0.5

    @property
    def samples(self) -> int:
        return int((self.alpha - 1) + (self.beta - 1))

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "alpha": round(self.alpha, 2),
            "beta": round(self.beta, 2),
            "trust": round(self.trust, 3),
            "samples": self.samples,
            "last_update": self.last_update,
        }


# ── Calibrator ──────────────────────────────────────────────

class TrustCalibrator:
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

    # ── Registration ───────────────────────────────────────

    def register(
        self,
        name: str,
        kind: str = "",
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> SourceTrust:
        name = name.strip()
        if not name:
            raise ValueError("source name required")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sources (name, alpha, beta, kind, last_update) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind",
                (name, float(prior_alpha), float(prior_beta),
                 kind, time.time()),
            )
            conn.commit()
        return self.get(name)

    # ── Update ─────────────────────────────────────────────

    def update(self, name: str, correct: bool) -> SourceTrust | None:
        """Fold one outcome: correct bumps α, incorrect bumps β."""
        name = name.strip()
        if not name:
            return None
        with self._lock, self._connect() as conn:
            # Auto-register if new
            conn.execute(
                "INSERT OR IGNORE INTO sources (name) VALUES (?)",
                (name,),
            )
            if correct:
                conn.execute(
                    "UPDATE sources SET alpha=alpha+1, last_update=? "
                    "WHERE name=?",
                    (time.time(), name),
                )
            else:
                conn.execute(
                    "UPDATE sources SET beta=beta+1, last_update=? "
                    "WHERE name=?",
                    (time.time(), name),
                )
            conn.commit()
        return self.get(name)

    # ── Query ───────────────────────────────────────────────

    def get(self, name: str) -> SourceTrust | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT name, alpha, beta, kind, last_update "
                "FROM sources WHERE name=?",
                (name.strip(),),
            ).fetchone()
        if not row:
            return None
        return SourceTrust(
            name=row[0], alpha=float(row[1]), beta=float(row[2]),
            kind=row[3] or "", last_update=float(row[4] or 0),
        )

    def trust(self, name: str) -> float:
        s = self.get(name)
        return s.trust if s else 0.5   # uniform prior

    def rank(self, limit: int = 20) -> list[SourceTrust]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, alpha, beta, kind, last_update "
                "FROM sources"
            ).fetchall()
        out = [
            SourceTrust(
                name=r[0], alpha=float(r[1]), beta=float(r[2]),
                kind=r[3] or "", last_update=float(r[4] or 0),
            )
            for r in rows
        ]
        out.sort(key=lambda s: -s.trust)
        return out[:limit]

    def weight(
        self, name: str, context: dict[str, Any] | None = None,
    ) -> float:
        """Trust × optional context affinity.

        ``context`` may carry ``expected_kind`` (must match the
        source's kind to avoid a 0.5 penalty) and ``min_samples``
        (trust is capped at 0.5 when too few samples)."""
        s = self.get(name)
        if s is None:
            return 0.5
        weight = s.trust
        if context:
            expected_kind = context.get("expected_kind")
            if expected_kind and s.kind and expected_kind != s.kind:
                weight *= 0.5
            min_samples = int(context.get("min_samples", 0))
            if s.samples < min_samples:
                weight = min(weight, 0.5)
        return round(weight, 3)

    # ── Decay ───────────────────────────────────────────────

    def decay_stale(self, half_life_days: float = 60.0) -> int:
        """Exponentially decay α and β for sources whose last update
        is older than the half-life. Pulls trust back toward the
        uniform prior so ancient trust doesn't dominate forever.

        Returns the number of sources decayed."""
        if half_life_days <= 0:
            return 0
        now = time.time()
        half_s = half_life_days * 86_400
        count = 0
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT name, alpha, beta, last_update FROM sources"
            ).fetchall()
            for name, a, b, lu in rows:
                if lu <= 0:
                    continue
                age = now - float(lu)
                if age <= half_s:
                    continue
                factor = 0.5 ** (age / half_s)
                new_a = 1.0 + (float(a) - 1.0) * factor
                new_b = 1.0 + (float(b) - 1.0) * factor
                conn.execute(
                    "UPDATE sources SET alpha=?, beta=? WHERE name=?",
                    (new_a, new_b, name),
                )
                count += 1
            conn.commit()
        return count

    # ── Consensus ──────────────────────────────────────────

    def consensus(
        self, claims: Iterable[tuple[str, Any]],
    ) -> tuple[Any, float] | None:
        """Weighted majority over (source, value) pairs. Returns
        (winning_value, total_trust) or None if no claims."""
        tallies: dict[Any, float] = {}
        for source, value in claims:
            w = self.trust(source)
            key = _freeze(value)
            tallies[key] = tallies.get(key, 0.0) + w
        if not tallies:
            return None
        winner_key = max(tallies.keys(), key=lambda k: tallies[k])
        return (_unfreeze(winner_key, claims), tallies[winner_key])


def _freeze(v: Any) -> Any:
    if isinstance(v, dict):
        return ("__dict__", tuple(sorted(v.items())))
    if isinstance(v, list):
        return ("__list__", tuple(v))
    return v


def _unfreeze(key: Any, claims: Iterable[tuple[str, Any]]) -> Any:
    # Return the original value (first claim that matches the frozen
    # key). This preserves dict/list references for the caller.
    for _, v in claims:
        if _freeze(v) == key:
            return v
    return key
