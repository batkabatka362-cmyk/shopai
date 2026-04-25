"""Skill library — named, composable skills with observed win rate.

**When to use (vs skill_composer / skill_distiller / skill_transfer)**:
  • ``skill_library`` — REGISTER + RUN single atomic skills in the
    current context. Tracks per-skill win rate.
  • ``skill_composer`` — CHAIN atomic skills into macro-skills
    (sequence / fallback / parallel). Tracks macro-level win rate
    separately.
  • ``skill_distiller`` — DISCOVER new skills from case clusters
    (promotes (situation, action) patterns with high win rate into
    a named Skill).
  • ``skill_transfer`` — PORT a skill learned in store/niche A to
    store/niche B, discounted by trait similarity.

Intelligence scattered across ``engines/`` is brittle: the caller
must know which engine to invoke, what inputs it wants, how to
interpret the output. A *skill* packages (name, preconditions,
recipe, post-check) into a reusable unit that tracks its own
historical win rate so the decision layer can pick the best proven
skill for a goal.

    lib = SkillLibrary()
    lib.register(Skill(
        name="kill_underperforming_ad",
        preconditions={"ad_roas_lt": 1.5, "ad_age_days_gt": 3},
        recipe=kill_ad_fn,                 # callable
        post_check=lambda ctx: ctx.get("ad_status") == "paused",
        tags=("ads", "kill"),
    ))
    lib.record_outcome("kill_underperforming_ad", success=True)

At decision time:

    candidates = lib.candidates(context={"ad_roas": 1.2, "ad_age_days": 5})
    best = lib.best(candidates)           # picks by win_rate × support

Pure stdlib. SQLite-persisted win/use stats. Deterministic.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


RecipeFn = Callable[[dict[str, Any]], Any]
PostCheckFn = Callable[[dict[str, Any]], bool]


_OPS = re.compile(r"^(.+?)_(lt|gt|eq|in|exists)$")


def _check_precondition(ctx: dict[str, Any], cond: dict[str, Any]) -> bool:
    """Mini-DSL: "ad_roas_lt": 1.5 → ctx['ad_roas'] < 1.5.

    Supported suffixes: _lt, _gt, _eq, _in, _exists. Keys without
    a suffix fall back to equality.
    """
    for key, expected in cond.items():
        m = _OPS.match(key)
        if m:
            field_name, op = m.groups()
            actual = ctx.get(field_name)
            if op == "exists":
                if bool(expected) != (actual is not None):
                    return False
                continue
            if actual is None:
                return False
            try:
                if op == "lt" and not (float(actual) < float(expected)):
                    return False
                if op == "gt" and not (float(actual) > float(expected)):
                    return False
                if op == "eq" and actual != expected:
                    return False
                if op == "in" and actual not in expected:
                    return False
            except (TypeError, ValueError):
                return False
        else:
            if ctx.get(key) != expected:
                return False
    return True


@dataclass
class Skill:
    name: str
    preconditions: dict[str, Any] = field(default_factory=dict)
    recipe: RecipeFn | None = None
    post_check: PostCheckFn | None = None
    tags: tuple[str, ...] = ()
    description: str = ""

    def applicable(self, context: dict[str, Any]) -> bool:
        return _check_precondition(context, self.preconditions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "preconditions": self.preconditions,
            "tags": list(self.tags),
            "description": self.description,
        }


@dataclass
class SkillStats:
    name: str
    uses: int
    wins: int
    last_used_ts: float

    @property
    def win_rate(self) -> float:
        if self.uses == 0:
            return 0.0
        return self.wins / self.uses

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "uses": self.uses,
            "wins": self.wins,
            "win_rate": round(self.win_rate, 4),
            "last_used_ts": self.last_used_ts,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_stats (
    name         TEXT PRIMARY KEY,
    uses         INTEGER NOT NULL DEFAULT 0,
    wins         INTEGER NOT NULL DEFAULT 0,
    last_used_ts REAL NOT NULL DEFAULT 0
);
"""


class SkillLibrary:
    def __init__(
        self, db_path: str | Path = "data/skill_library.db",
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._skills: dict[str, Skill] = {}
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Registration ───────────────────────────────────────

    def register(self, skill: Skill, overwrite: bool = False) -> None:
        if not skill.name:
            raise ValueError("skill.name required")
        if skill.name in self._skills and not overwrite:
            raise ValueError(
                f"skill {skill.name!r} already registered",
            )
        self._skills[skill.name] = skill
        # Ensure a stats row exists so win_rate queries don't blank
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO skill_stats(name) VALUES (?)",
                (skill.name,),
            )
            self._conn.commit()

    def unregister(self, name: str) -> bool:
        return self._skills.pop(name, None) is not None

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all_skills(self) -> list[Skill]:
        return list(self._skills.values())

    # ── Matching ───────────────────────────────────────────

    def candidates(self, context: dict[str, Any]) -> list[Skill]:
        return [s for s in self._skills.values() if s.applicable(context)]

    def best(
        self,
        candidates: Iterable[Skill],
        *,
        min_support: int = 3,
        exploration: float = 0.1,
    ) -> Skill | None:
        """Pick highest win_rate among candidates with enough uses.
        Untested skills (uses < min_support) are scored at ``exploration``
        so the library still tries them occasionally."""
        best_score = -1.0
        best_skill: Skill | None = None
        for s in candidates:
            stats = self.stats(s.name)
            if stats.uses < min_support:
                score = exploration
            else:
                score = stats.win_rate
            if score > best_score:
                best_score = score
                best_skill = s
        return best_skill

    # ── Execution ──────────────────────────────────────────

    def run(
        self,
        name: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a skill's recipe, run post_check, record outcome."""
        skill = self._skills.get(name)
        if skill is None:
            return {"status": "unknown_skill", "name": name}
        if not skill.applicable(context):
            return {"status": "precondition_failed", "name": name}
        if skill.recipe is None:
            return {"status": "no_recipe", "name": name}
        output = skill.recipe(context)
        ctx_after = dict(context)
        if isinstance(output, dict):
            ctx_after.update(output)
        success = True
        if skill.post_check is not None:
            try:
                success = bool(skill.post_check(ctx_after))
            except Exception:
                success = False
        self.record_outcome(name, success=success)
        return {
            "status": "ok",
            "name": name,
            "success": success,
            "output": output,
        }

    # ── Stats ──────────────────────────────────────────────

    def record_outcome(self, name: str, success: bool) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO skill_stats(name) VALUES (?)",
                (name,),
            )
            self._conn.execute(
                "UPDATE skill_stats SET uses=uses+1, "
                "wins=wins+?, last_used_ts=? WHERE name=?",
                (1 if success else 0, time.time(), name),
            )
            self._conn.commit()

    def stats(self, name: str) -> SkillStats:
        with self._lock:
            row = self._conn.execute(
                "SELECT uses, wins, last_used_ts FROM skill_stats "
                "WHERE name=?",
                (name,),
            ).fetchone()
        if row is None:
            return SkillStats(name=name, uses=0, wins=0, last_used_ts=0.0)
        return SkillStats(
            name=name, uses=int(row[0]), wins=int(row[1]),
            last_used_ts=float(row[2]),
        )

    def rank(self, min_support: int = 3) -> list[SkillStats]:
        """Proven skills sorted by win rate × support."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, uses, wins, last_used_ts FROM skill_stats "
                "WHERE uses >= ?",
                (int(min_support),),
            ).fetchall()
        stats = [
            SkillStats(
                name=r[0], uses=int(r[1]), wins=int(r[2]),
                last_used_ts=float(r[3]),
            )
            for r in rows
        ]
        stats.sort(key=lambda s: -(s.win_rate * s.uses))
        return stats

    def close(self) -> None:
        with self._lock:
            self._conn.close()
