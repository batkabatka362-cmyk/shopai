"""Skill composer — chain individual skills into macro-skills.

skill_library (v22-D2) stores atomic skills. Real work comes from
*composing* them: "launch a new product" =
  ingest → enrich → publish → launch_ads → monitor.
Without a composer, every caller hand-wires these chains and tracks
their win rate in whatever way they prefer. The composer formalises
it:

  • MacroSkill(name, steps, composition_kind)
  • composition_kind = "sequence" | "fallback" | "parallel"
  • run(macro_name, context) executes the composition atop
    skill_library.run(), threads context, returns one combined
    ExecutionReport with per-step statuses.
  • record_outcome_on_macro() updates the macro's own win rate —
    separate from per-step stats — so we can learn that the *whole
    chain* works, even when one step occasionally falters.

Composition semantics:

  sequence — run steps in order, each gets the prior output in its
             ctx; fail fast unless a step is tagged optional.
  fallback — try steps in order; first success wins.
  parallel — run steps independently on the same context; report
             individual statuses, macro-success when all succeed.

SQLite-persisted win/use stats. Pure stdlib. Deterministic.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from utils.logger import get_logger


logger = get_logger("brain.skill_composer")


Composition = Literal["sequence", "fallback", "parallel"]


@dataclass
class MacroStep:
    skill: str
    optional: bool = False
    # Pre-processor: mutate the context just before this step fires.
    prepare: Callable[[dict[str, Any]], dict[str, Any]] | None = None


@dataclass
class MacroSkill:
    name: str
    kind: Composition
    steps: list[MacroStep] = field(default_factory=list)
    description: str = ""
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "steps": [
                {"skill": s.skill, "optional": s.optional}
                for s in self.steps
            ],
            "description": self.description,
            "tags": list(self.tags),
        }


@dataclass
class StepReport:
    skill: str
    status: str          # "ok" | "failed" | "skipped"
    success: bool
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "status": self.status,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class ExecutionReport:
    macro: str
    kind: Composition
    success: bool
    steps: list[StepReport] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "macro": self.macro,
            "kind": self.kind,
            "success": self.success,
            "steps": [s.as_dict() for s in self.steps],
            "elapsed_ms": round(self.elapsed_ms, 2),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS macro_stats (
    name         TEXT PRIMARY KEY,
    uses         INTEGER NOT NULL DEFAULT 0,
    wins         INTEGER NOT NULL DEFAULT 0,
    last_used_ts REAL NOT NULL DEFAULT 0
);
"""


class SkillComposer:
    def __init__(
        self,
        db_path: str | Path = "data/skill_composer.db",
        skill_library: Any = None,
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._macros: dict[str, MacroSkill] = {}
        # Allow dependency injection of the skill library so the
        # composer is testable without touching the singleton.
        self._skill_library = skill_library
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Registration ─────────────────────────────────────

    def register(
        self, macro: MacroSkill, overwrite: bool = False,
    ) -> None:
        if not macro.name:
            raise ValueError("macro.name required")
        if macro.kind not in ("sequence", "fallback", "parallel"):
            raise ValueError("kind must be sequence/fallback/parallel")
        if not macro.steps:
            raise ValueError("macro needs ≥ 1 step")
        if macro.name in self._macros and not overwrite:
            raise ValueError(f"macro {macro.name!r} already registered")
        self._macros[macro.name] = macro
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO macro_stats(name) VALUES (?)",
                (macro.name,),
            )
            self._conn.commit()

    def unregister(self, name: str) -> bool:
        return self._macros.pop(name, None) is not None

    def get(self, name: str) -> MacroSkill | None:
        return self._macros.get(name)

    def all_macros(self) -> list[MacroSkill]:
        return list(self._macros.values())

    # ── Execution ────────────────────────────────────────

    def _skill_lib(self):
        if self._skill_library is not None:
            return self._skill_library
        from core.brain.skill_library import SkillLibrary
        self._skill_library = SkillLibrary()
        return self._skill_library

    def _apply_prepare(
        self, step: MacroStep, context: dict[str, Any],
    ) -> dict[str, Any]:
        if step.prepare is None:
            return dict(context)
        try:
            return dict(step.prepare(dict(context)))
        except Exception as exc:
            logger.debug("prepare failed for %s: %s", step.skill, exc)
            return dict(context)

    def _run_step(
        self, step: MacroStep, context: dict[str, Any],
    ) -> tuple[StepReport, dict[str, Any]]:
        ctx = self._apply_prepare(step, context)
        try:
            result = self._skill_lib().run(step.skill, ctx)
        except Exception as exc:
            logger.debug("skill.run raised: %s", exc)
            return (
                StepReport(
                    skill=step.skill, status="failed",
                    success=False, error=str(exc),
                ),
                ctx,
            )
        status = str(result.get("status", "ok"))
        success = bool(result.get("success", status == "ok"))
        new_ctx = dict(ctx)
        output = result.get("output")
        if isinstance(output, dict):
            new_ctx.update(output)
        return (
            StepReport(
                skill=step.skill,
                status=status,
                success=success,
                error=str(result.get("error", "")),
            ),
            new_ctx,
        )

    def run(
        self,
        name: str,
        context: dict[str, Any] | None = None,
    ) -> ExecutionReport:
        macro = self._macros.get(name)
        if macro is None:
            return ExecutionReport(
                macro=name, kind="sequence", success=False,
                steps=[],
            )
        started = time.monotonic()
        context = dict(context or {})
        reports: list[StepReport] = []
        success = True

        if macro.kind == "sequence":
            for step in macro.steps:
                rep, context = self._run_step(step, context)
                reports.append(rep)
                if not rep.success and not step.optional:
                    success = False
                    break
        elif macro.kind == "fallback":
            success = False
            for step in macro.steps:
                rep, context = self._run_step(step, context)
                reports.append(rep)
                if rep.success:
                    success = True
                    break
        else:  # parallel
            # Deterministic parallelism: run one after another on the
            # original context (no threading — callers rely on the
            # composer being predictable).
            original = dict(context)
            for step in macro.steps:
                rep, _ = self._run_step(step, original)
                reports.append(rep)
            success = all(
                r.success for r in reports
                if not self._step_optional(macro, r.skill)
            )

        self._record_outcome(macro.name, success=success)
        return ExecutionReport(
            macro=macro.name, kind=macro.kind,
            success=success, steps=reports,
            elapsed_ms=(time.monotonic() - started) * 1000.0,
        )

    @staticmethod
    def _step_optional(macro: MacroSkill, skill: str) -> bool:
        for s in macro.steps:
            if s.skill == skill:
                return s.optional
        return False

    # ── Stats ────────────────────────────────────────────

    def _record_outcome(self, name: str, success: bool) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO macro_stats(name) VALUES (?)",
                (name,),
            )
            self._conn.execute(
                "UPDATE macro_stats SET uses=uses+1, "
                "wins=wins+?, last_used_ts=? WHERE name=?",
                (1 if success else 0, time.time(), name),
            )
            self._conn.commit()

    def stats(self, name: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT uses, wins, last_used_ts FROM macro_stats "
                "WHERE name=?",
                (name,),
            ).fetchone()
        if row is None:
            return {"name": name, "uses": 0, "wins": 0, "win_rate": 0.0}
        uses, wins, last = int(row[0]), int(row[1]), float(row[2])
        return {
            "name": name, "uses": uses, "wins": wins,
            "win_rate": (wins / uses) if uses else 0.0,
            "last_used_ts": last,
        }

    def rank(self, min_support: int = 3) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, uses, wins, last_used_ts "
                "FROM macro_stats WHERE uses >= ?",
                (int(min_support),),
            ).fetchall()
        out = [
            {
                "name": r[0], "uses": int(r[1]), "wins": int(r[2]),
                "win_rate": int(r[2]) / int(r[1]) if int(r[1]) else 0.0,
                "last_used_ts": float(r[3]),
            }
            for r in rows
        ]
        out.sort(key=lambda s: -(s["win_rate"] * s["uses"]))
        return out

    def close(self) -> None:
        with self._lock:
            self._conn.close()
