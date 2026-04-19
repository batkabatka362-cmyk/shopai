"""Skill registry + skill tree.

Every capability ShopAI demonstrates — scraping Alibaba, writing
ad copy, computing ROAS, killing a campaign — is treated as a
named *Skill* with:

  • ``confidence``   — Beta(α, β) posterior over success probability
  • ``uses``, ``wins`` — raw counts feeding the posterior
  • ``prereqs``       — list of skills that must exist first
  • ``last_used``     — cold skills get promoted on the opportunity
                        scout's ``underutilised`` bucket
  • ``cost_usd``      — rough per-use cost (LLM tokens + API fees)

Composite skills (e.g. ``run_launch``) list the atomic skills they
depend on and inherit the *minimum* confidence of their prereqs —
a single weak link collapses the composite confidence. This mirrors
how a human operator reasons about "can we pull this off?"

Skills are stored in a separate SQLite DB so the memory DB stays
pure episodic. Instrumentation hook ``record(skill, success)`` is
called by the existing adapter/action layer via ``with_skill``
context manager.

Example::

    from core.brain.skills import registry, with_skill

    with with_skill("content.write_product_copy"):
        run_llm(...)   # exception → records failure; success → win
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


_DB_PATH = Path("data/skills.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    name        TEXT PRIMARY KEY,
    category    TEXT NOT NULL DEFAULT 'general',
    alpha       REAL NOT NULL DEFAULT 1.0,
    beta        REAL NOT NULL DEFAULT 1.0,
    uses        INTEGER NOT NULL DEFAULT 0,
    wins        INTEGER NOT NULL DEFAULT 0,
    prereqs     TEXT NOT NULL DEFAULT '[]',
    cost_usd    REAL NOT NULL DEFAULT 0.0,
    created_at  REAL NOT NULL,
    last_used   REAL NOT NULL DEFAULT 0,
    last_failed REAL NOT NULL DEFAULT 0,
    metadata    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_skill_category ON skills(category);
CREATE INDEX IF NOT EXISTS idx_skill_last_used ON skills(last_used);
"""


_lock = threading.Lock()


@dataclass
class Skill:
    name: str
    category: str = "general"
    alpha: float = 1.0
    beta: float = 1.0
    uses: int = 0
    wins: int = 0
    prereqs: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    created_at: float = 0.0
    last_used: float = 0.0
    last_failed: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def confidence(self) -> float:
        """Posterior mean of the Beta(α, β) success probability."""
        denom = self.alpha + self.beta
        return self.alpha / denom if denom > 0 else 0.5

    @property
    def uncertainty(self) -> float:
        """Posterior stddev — high when we lack evidence."""
        a = self.alpha
        b = self.beta
        denom = (a + b) ** 2 * (a + b + 1)
        if denom <= 0:
            return 0.5
        import math
        return math.sqrt(a * b / denom)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "confidence": round(self.confidence, 3),
            "uncertainty": round(self.uncertainty, 3),
            "uses": self.uses,
            "wins": self.wins,
            "prereqs": self.prereqs,
            "cost_usd": round(self.cost_usd, 4),
            "last_used": self.last_used,
            "last_failed": self.last_failed,
            "metadata": self.metadata,
        }


class SkillRegistry:
    """Process-wide registry. Thread-safe via the module lock."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            conn = sqlite3.connect(str(self._path))
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()

    # ── CRUD ────────────────────────────────────────────────

    def define(
        self,
        name: str,
        category: str = "general",
        prereqs: list[str] | None = None,
        cost_usd: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> Skill:
        """Register a skill. Idempotent — second call is a no-op."""
        assert name, "skill name required"
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM skills WHERE name=?", (name,))
                if cur.fetchone():
                    return self._get_locked(conn, name)
                cur.execute(
                    "INSERT INTO skills(name, category, prereqs, cost_usd, "
                    "  created_at, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        name, category,
                        json.dumps(list(prereqs or [])),
                        float(cost_usd),
                        time.time(),
                        json.dumps(metadata or {}),
                    ),
                )
                conn.commit()
                return self._get_locked(conn, name)
            finally:
                conn.close()

    def record(
        self,
        name: str,
        success: bool,
        cost_usd: float = 0.0,
    ) -> Skill:
        """Record one attempt. Auto-defines unknown skills so
        instrumentation doesn't need to register first."""
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM skills WHERE name=?", (name,))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO skills(name, category, created_at) "
                        "VALUES (?, 'general', ?)",
                        (name, time.time()),
                    )
                now = time.time()
                if success:
                    cur.execute(
                        "UPDATE skills SET "
                        "alpha = alpha + 1, uses = uses + 1, "
                        "wins = wins + 1, last_used = ?, "
                        "cost_usd = cost_usd + ? "
                        "WHERE name=?",
                        (now, float(cost_usd), name),
                    )
                else:
                    cur.execute(
                        "UPDATE skills SET "
                        "beta = beta + 1, uses = uses + 1, "
                        "last_used = ?, last_failed = ?, "
                        "cost_usd = cost_usd + ? "
                        "WHERE name=?",
                        (now, now, float(cost_usd), name),
                    )
                conn.commit()
                return self._get_locked(conn, name)
            finally:
                conn.close()

    def get(self, name: str) -> Skill | None:
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                return self._get_locked(conn, name)
            finally:
                conn.close()

    def list_all(
        self,
        category: str | None = None,
        min_confidence: float | None = None,
    ) -> list[Skill]:
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                if category:
                    cur.execute(
                        "SELECT * FROM skills WHERE category=?",
                        (category,),
                    )
                else:
                    cur.execute("SELECT * FROM skills ORDER BY name")
                rows = cur.fetchall()
                names = [r[0] for r in rows]
                skills = [self._row_to_skill(r) for r in rows]
            finally:
                conn.close()
        if min_confidence is not None:
            skills = [s for s in skills if s.confidence >= min_confidence]
        return skills

    def composite_confidence(self, composite_name: str) -> float:
        """Composite skill confidence = min(prereq confidences).

        A composite with no declared prereqs falls back to its own
        recorded confidence. Returns 0.0 when the skill is unknown.
        """
        s = self.get(composite_name)
        if s is None:
            return 0.0
        if not s.prereqs:
            return s.confidence
        lows = []
        for p in s.prereqs:
            ps = self.get(p)
            if ps is None:
                return 0.0
            lows.append(ps.confidence)
        return min(lows)

    # ── Internals ───────────────────────────────────────────

    def _get_locked(self, conn: sqlite3.Connection, name: str) -> Skill | None:
        cur = conn.cursor()
        cur.execute("SELECT * FROM skills WHERE name=?", (name,))
        row = cur.fetchone()
        return self._row_to_skill(row) if row else None

    @staticmethod
    def _row_to_skill(row: tuple) -> Skill:
        try:
            prereqs = json.loads(row[6] or "[]")
        except (json.JSONDecodeError, ValueError):
            prereqs = []
        try:
            metadata = json.loads(row[11] or "{}")
        except (json.JSONDecodeError, ValueError):
            metadata = {}
        return Skill(
            name=row[0],
            category=row[1],
            alpha=float(row[2] or 1),
            beta=float(row[3] or 1),
            uses=int(row[4] or 0),
            wins=int(row[5] or 0),
            prereqs=list(prereqs) if isinstance(prereqs, list) else [],
            cost_usd=float(row[7] or 0),
            created_at=float(row[8] or 0),
            last_used=float(row[9] or 0),
            last_failed=float(row[10] or 0),
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
        )


# ── Singleton ────────────────────────────────────────────────

_REGISTRY_LOCK = threading.Lock()
_REGISTRY: SkillRegistry | None = None


def registry() -> SkillRegistry:
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = SkillRegistry()
    return _REGISTRY


# ── Instrumentation helper ──────────────────────────────────

@contextlib.contextmanager
def with_skill(name: str, cost_usd: float = 0.0) -> Iterator[None]:
    """Context manager that records a success if the block completes
    cleanly and a failure if it raises. The exception is re-raised;
    callers always see the same error semantics."""
    success = False
    try:
        yield
        success = True
    finally:
        try:
            registry().record(name, success=success, cost_usd=cost_usd)
        except Exception:
            # Instrumentation must not break callers.
            pass
