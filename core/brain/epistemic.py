"""Epistemic coverage — know what we don't know.

Every AGI-adjacent system needs a sense of its *own* knowledge
frontier. Without it the brain can't tell the difference between:

  • "we've tried 50 audio launches — we're confident ROAS ~2.5"
  • "we've tried 0 gardening launches — we have no idea"

Both come out of ``world_model.predict(..)`` with some number.
EpistemicCoverage builds a coverage map explicitly: for each
(dimension, value) combination, how many observations do we have,
when was the last one, what's our confidence tier?

Dimensions: niche, price_band, margin_band, copy_tone, action.
The map supports:

  coverage(dim, value) → CoverageCell with (n, last_seen_s, tier)
  gaps(top_k)          → the top-K cells with the *least* coverage
                         (dimensions × values with 0 or very few
                         observations)
  confidence(context)  → 0-1 scalar composing per-dim coverage
  suggest_exploration_target() → which cell to probe next

Tiers:
  ``cold``   n < 3
  ``warm``   3 ≤ n < 10
  ``hot``    n ≥ 10

When the dual-process router (v7-D7) or curiosity policy asks
"what should we sample?" the engine returns the most-cold cell
that's also *reachable* (i.e. appears in the current candidate
feature space). That's active inference: directed sampling to
collapse uncertainty where it matters.

Persistence: ``data/epistemic.db``. Pure stdlib.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_DB_PATH = Path("data/epistemic.db")

_DIMENSIONS = ("niche", "price_band", "margin_band",
               "copy_tone", "action")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cells (
    dimension   TEXT NOT NULL,
    value       TEXT NOT NULL,
    n           INTEGER NOT NULL DEFAULT 0,
    last_seen   REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (dimension, value)
);
CREATE INDEX IF NOT EXISTS idx_n ON cells(n);
"""


@dataclass
class CoverageCell:
    dimension: str
    value: str
    n: int
    last_seen_s: float
    tier: str                       # cold | warm | hot

    def as_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "value": self.value,
            "n": self.n,
            "last_seen_s": self.last_seen_s,
            "tier": self.tier,
        }


@dataclass
class ExplorationSuggestion:
    dimension: str
    value: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "value": self.value,
            "reason": self.reason,
        }


# ── Tier helper ─────────────────────────────────────────────

def _tier(n: int) -> str:
    if n < 3:
        return "cold"
    if n < 10:
        return "warm"
    return "hot"


# ── Engine ──────────────────────────────────────────────────

class EpistemicCoverage:
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

    # ── Record ──────────────────────────────────────────────

    def observe(self, features: dict[str, Any]) -> int:
        """Fold one observation. Increments ``n`` for every
        dimension-value present in ``features``."""
        with self._lock, self._connect() as conn:
            touched = 0
            now = time.time()
            for dim in _DIMENSIONS:
                val = features.get(dim)
                if val is None:
                    continue
                val = str(val).strip().lower()
                if not val:
                    continue
                conn.execute(
                    "INSERT INTO cells (dimension, value, n, last_seen) "
                    "VALUES (?, ?, 1, ?) "
                    "ON CONFLICT(dimension, value) DO UPDATE SET "
                    "  n = n + 1, last_seen = ?",
                    (dim, val, now, now),
                )
                touched += 1
            conn.commit()
            return touched

    # ── Queries ─────────────────────────────────────────────

    def coverage(self, dimension: str, value: str) -> CoverageCell:
        value = str(value).strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT n, last_seen FROM cells "
                "WHERE dimension=? AND value=?",
                (dimension, value),
            ).fetchone()
        if not row:
            return CoverageCell(
                dimension=dimension, value=value, n=0,
                last_seen_s=0.0, tier="cold",
            )
        n, last = row
        return CoverageCell(
            dimension=dimension, value=value, n=int(n),
            last_seen_s=float(last), tier=_tier(int(n)),
        )

    def gaps(self, top_k: int = 10) -> list[CoverageCell]:
        """Cells with the least coverage. Sorts ascending by ``n``;
        ties broken by oldest last_seen."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT dimension, value, n, last_seen FROM cells "
                "ORDER BY n ASC, last_seen ASC LIMIT ?",
                (int(top_k),),
            ).fetchall()
        return [
            CoverageCell(
                dimension=r[0], value=r[1], n=int(r[2]),
                last_seen_s=float(r[3]), tier=_tier(int(r[2])),
            )
            for r in rows
        ]

    def confidence(self, context: dict[str, Any]) -> float:
        """0-1 scalar: lower when any dimension is cold."""
        scores: list[float] = []
        for dim in _DIMENSIONS:
            if dim not in context:
                continue
            cell = self.coverage(dim, str(context[dim]))
            if cell.tier == "hot":
                scores.append(1.0)
            elif cell.tier == "warm":
                scores.append(0.6)
            else:
                scores.append(0.2)
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 3)

    def suggest_exploration_target(
        self,
        candidate_values: dict[str, list[str]] | None = None,
    ) -> ExplorationSuggestion | None:
        """Return the most-cold (dim, value) combination, optionally
        restricted to ``candidate_values`` provided by the caller —
        e.g. "which audio tone haven't we tried?".

        Returns None if the coverage table is empty (nothing known
        to contrast)."""
        with self._connect() as conn:
            if candidate_values:
                # Check every provided (dim, value) pair against
                # existing counts, pick the lowest n.
                candidates: list[tuple[str, str, int, float]] = []
                for dim, values in candidate_values.items():
                    for v in values:
                        row = conn.execute(
                            "SELECT n, last_seen FROM cells "
                            "WHERE dimension=? AND value=?",
                            (dim, str(v).lower()),
                        ).fetchone()
                        n = int(row[0]) if row else 0
                        last = float(row[1]) if row else 0.0
                        candidates.append((dim, str(v).lower(), n, last))
                if not candidates:
                    return None
                candidates.sort(key=lambda c: (c[2], c[3]))
                dim, val, n, _ = candidates[0]
                return ExplorationSuggestion(
                    dimension=dim,
                    value=val,
                    reason=f"n={n} (lowest of {len(candidates)} "
                           "candidates)",
                )
            row = conn.execute(
                "SELECT dimension, value, n FROM cells "
                "ORDER BY n ASC, last_seen ASC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return ExplorationSuggestion(
            dimension=row[0],
            value=row[1],
            reason=f"n={int(row[2])} (rarest observed cell)",
        )

    # ── Introspection ─────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM cells"
            ).fetchone()[0]
            by_tier: dict[str, int] = {"cold": 0, "warm": 0, "hot": 0}
            rows = conn.execute(
                "SELECT n FROM cells"
            ).fetchall()
            for (n,) in rows:
                by_tier[_tier(int(n))] += 1
            total_obs = conn.execute(
                "SELECT SUM(n) FROM cells"
            ).fetchone()[0]
        return {
            "total_cells": int(total or 0),
            "total_observations": int(total_obs or 0),
            "by_tier": by_tier,
        }


# ── Singleton ────────────────────────────────────────────────

_EC_LOCK = threading.Lock()
_EC: EpistemicCoverage | None = None


def coverage_engine() -> EpistemicCoverage:
    global _EC
    if _EC is None:
        with _EC_LOCK:
            if _EC is None:
                _EC = EpistemicCoverage()
    return _EC
