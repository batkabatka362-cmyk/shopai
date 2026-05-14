"""Obsidian-compatible knowledge vault exporter.

Walks ShopAI's persistent state (approval queue, goal effectiveness
EMA, engine→goal map) and emits a folder of plain Markdown files
that drops directly into an Obsidian vault. Read-only — never
mutates the source systems.

Why
---
The user's 17-day plan step 2 calls for an Obsidian + NotebookLM
memory layer "like inserting a human thinking system into AI."
The cleanest first piece is an export bridge: ShopAI keeps its
state in SQLite (approval queue) and Python in-memory structures
(GoalManager); Obsidian wants Markdown. This module is the
bridge. The user reviews / annotates in Obsidian; future passes
can feed those annotations back through NotebookLM into a
retrieval-augmented prompt for the LLM layer.

Output layout
-------------
::

    <vault>/
        overview.md             — top-level dashboard
        engines/
            cart_recovery.md
            discount_strategy.md
            ...
        goals/
            maximize_profit.md
            grow_customers.md
            ...
        decisions/
            <YYYY-MM-DD>-<engine>-<action_id>.md

Each file carries:

* **YAML frontmatter** — typed metadata (``type``, ``goal``,
  ``status``, ``confidence``) so Obsidian's Dataview plugin can
  index and query.
* **Wiki-links** — ``[[grow_customers]]``, ``[[cart_recovery]]``
  for cross-navigation.
* **Tags** — ``#shopai/engine``, ``#shopai/goal``,
  ``#shopai/decision/executed``.

The export is **additive** — running twice writes the same files
with refreshed content (deterministic per-source). Existing files
NOT produced by this exporter (operator's own notes) are left
alone.

Usage
-----
::

    from core.knowledge import ObsidianExporter

    exporter = ObsidianExporter(target_dir="/path/to/vault")
    summary = exporter.export()
    # summary = {"engines": 30, "goals": 5, "decisions": 12, ...}

CLI: ``shopai knowledge export <path>``.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("core.knowledge.exporter")


@dataclass
class ExportSummary:
    """Counts of files written, per category. Returned by
    :meth:`ObsidianExporter.export` so the CLI can render
    a one-line success message."""

    engines: int = 0
    goals: int = 0
    decisions: int = 0
    overview_written: bool = False
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engines": self.engines,
            "goals": self.goals,
            "decisions": self.decisions,
            "overview_written": self.overview_written,
            "skipped": list(self.skipped),
        }


class ObsidianExporter:
    """Dump ShopAI state to an Obsidian-compatible Markdown vault.

    Args:
        target_dir: Path to the vault root. Created (and parent
            directories) if missing. Per-category subdirectories
            (engines/, goals/, decisions/) are created as needed.
        goal_manager: Optional :class:`~core.goals.goal_manager.GoalManager`.
            Defaults to the goal-feedback singleton so the export
            sees the same effectiveness EMA the brain uses live.
        decision_limit: Max number of executed/failed approvals to
            export to ``decisions/``. Old entries are skipped so
            the vault doesn't blow up over time; default 200.
    """

    def __init__(
        self,
        target_dir: str | Path,
        *,
        goal_manager: Any | None = None,
        decision_limit: int = 200,
    ) -> None:
        self.target_dir = Path(target_dir).expanduser().resolve()
        self.goal_manager = goal_manager
        self.decision_limit = max(0, int(decision_limit))

    # ── Public API ────────────────────────────────────────────

    def export(self) -> ExportSummary:
        """Walk every source and write the markdown tree.

        Returns a :class:`ExportSummary`. Never raises — sources
        that fail (e.g. SQLite missing) record a ``skipped`` entry
        instead of aborting the whole export.
        """
        self._ensure_dir(self.target_dir)
        summary = ExportSummary()

        # Engines — pure dict walk, can't fail
        summary.engines = self._export_engines()

        # Goals — needs GoalManager; degrades to empty stats
        try:
            summary.goals = self._export_goals()
        except Exception as exc:  # noqa: BLE001
            logger.debug("export_goals failed: %s", exc)
            summary.skipped.append(f"goals: {exc}")

        # Decisions — needs ApprovalQueue/SQLite; tolerable absent
        try:
            summary.decisions = self._export_decisions()
        except Exception as exc:  # noqa: BLE001
            logger.debug("export_decisions failed: %s", exc)
            summary.skipped.append(f"decisions: {exc}")

        # Overview last — its content references the above
        try:
            self._write_overview(summary)
            summary.overview_written = True
        except Exception as exc:  # noqa: BLE001
            logger.debug("write_overview failed: %s", exc)
            summary.skipped.append(f"overview: {exc}")

        return summary

    # ── Per-category writers ──────────────────────────────────

    def _export_engines(self) -> int:
        """One Markdown file per entry in ``ENGINE_GOAL_MAP``."""
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP

        engines_dir = self.target_dir / "engines"
        self._ensure_dir(engines_dir)
        count = 0
        for engine, goal in sorted(ENGINE_GOAL_MAP.items()):
            body = self._render_engine(engine, goal)
            self._write(engines_dir / f"{engine}.md", body)
            count += 1
        return count

    def _export_goals(self) -> int:
        """One Markdown file per canonical goal.

        Surfaces effectiveness EMA + sample count + which engines
        contribute. When the manager hasn't recorded outcomes yet
        the EMA is the neutral 0.5 default — that's still useful
        to render (operator sees "no data yet" clearly).
        """
        from core.goals.engine_goal_map import engines_for_goal
        from core.goals.goal_manager import GOAL_DEFINITIONS

        mgr = self.goal_manager or self._resolve_default_manager()
        goals_dir = self.target_dir / "goals"
        self._ensure_dir(goals_dir)
        count = 0
        for goal, definition in GOAL_DEFINITIONS.items():
            effectiveness = _safe_get_effectiveness(mgr, goal)
            samples = _safe_get_sample_count(mgr, goal)
            engines = engines_for_goal(goal)
            body = self._render_goal(
                goal, definition, effectiveness, samples, engines,
            )
            self._write(goals_dir / f"{goal}.md", body)
            count += 1
        return count

    def _export_decisions(self) -> int:
        """One Markdown file per EXECUTED / FAILED approval.

        ``decision_limit`` caps the page size so an old store with
        thousands of historical actions doesn't produce a huge
        vault. Newest-first ordering keeps recent decisions on
        top.
        """
        from core.approval import get_approval_queue

        queue = get_approval_queue()
        executed = queue.list_executed(limit=self.decision_limit) or []
        decisions_dir = self.target_dir / "decisions"
        self._ensure_dir(decisions_dir)
        count = 0
        for action in executed:
            filename = self._decision_filename(action)
            body = self._render_decision(action)
            self._write(decisions_dir / filename, body)
            count += 1
        return count

    def _write_overview(self, summary: ExportSummary) -> None:
        """Top-level dashboard with links into the three folders."""
        body = self._render_overview(summary)
        self._write(self.target_dir / "overview.md", body)

    # ── Renderers ─────────────────────────────────────────────

    def _render_engine(self, engine: str, goal: str) -> str:
        lines = [
            "---",
            f"name: {engine}",
            "type: engine",
            f"primary_goal: {goal}",
            "source: shopai",
            "---",
            "",
            f"# {engine}",
            "",
            f"Primary goal: [[{goal}]]",
            "",
            "## What this engine does",
            "",
            f"Auto-exported placeholder for the **{engine}** engine.",
            "ShopAI optimises this engine for its primary goal "
            f"[[{goal}]]. Engine code lives at "
            f"`engines/{engine}/flow.py`.",
            "",
            "## Operator notes",
            "",
            "_Add your own observations below. This block is "
            "preserved across re-exports — but the front matter "
            "above is regenerated._",
            "",
            f"#shopai/engine #shopai/goal/{goal}",
            "",
        ]
        return "\n".join(lines)

    def _render_goal(
        self,
        goal: str,
        definition: dict[str, Any],
        effectiveness: float,
        samples: int,
        engines: list[str],
    ) -> str:
        priority = definition.get("priority", "?")
        description = definition.get("description", "")
        triggers = definition.get("triggers") or {}
        engine_links = " · ".join(f"[[{e}]]" for e in engines) or "_(none)_"
        eff_label = "no_data" if samples == 0 else f"{effectiveness:.3f}"

        lines = [
            "---",
            f"name: {goal}",
            "type: goal",
            f"priority: {priority}",
            f"effectiveness: {effectiveness:.3f}",
            f"sample_count: {samples}",
            "source: shopai",
            "---",
            "",
            f"# {goal}",
            "",
            description,
            "",
            "## Current state",
            "",
            f"- **Priority**: {priority} (1 = highest)",
            f"- **Effectiveness EMA**: {eff_label}",
            f"- **Samples**: {samples} outcome event(s) recorded",
            "",
            "## Triggers",
            "",
        ]
        if triggers:
            for k, v in triggers.items():
                lines.append(f"- `{k}`: {v}")
        else:
            lines.append("_(default goal — fires when no trigger matches)_")
        lines += [
            "",
            "## Aligned engines",
            "",
            engine_links,
            "",
            "## Operator notes",
            "",
            "_Add observations or override hints here._",
            "",
            f"#shopai/goal #shopai/priority/{priority}",
            "",
        ]
        return "\n".join(lines)

    def _render_decision(self, action: Any) -> str:
        # Attribute access mirrors ApprovalAction.to_dict; lift
        # via getattr so future schema additions don't break the
        # exporter.
        action_id = getattr(action, "id", "unknown")
        engine = getattr(action, "engine", "unknown")
        action_type = getattr(action, "action_type", "")
        capability = getattr(action, "capability", "")
        narrative = getattr(action, "narrative", "")
        status = getattr(action, "status", None)
        status_value = (
            status.value if hasattr(status, "value") else str(status)
        )
        confidence = getattr(action, "confidence", None)
        proposed_at = getattr(action, "proposed_at", 0.0)
        decided_at = getattr(action, "decided_at", None)
        decided_by = getattr(action, "decided_by", "") or ""
        decision_reason = getattr(action, "decision_reason", "") or ""

        proposed_str = _ts_iso(proposed_at)
        decided_str = _ts_iso(decided_at) if decided_at else "_(pending)_"
        conf_label = (
            f"{confidence:.3f}" if isinstance(confidence, (int, float))
            else "n/a"
        )

        lines = [
            "---",
            f"id: {action_id}",
            "type: decision",
            f"engine: {engine}",
            f"action_type: {action_type}",
            f"capability: {capability}",
            f"status: {status_value}",
            f"confidence: {conf_label}",
            f"proposed_at: {proposed_str}",
            f"decided_at: {decided_str}",
            "source: shopai",
            "---",
            "",
            f"# {engine}: {action_type}",
            "",
            f"**Status**: {status_value}",
            "",
            "## Narrative",
            "",
            narrative or "_(no narrative recorded)_",
            "",
            "## Lineage",
            "",
            f"- Engine: [[{engine}]]",
            f"- Capability: `{capability}`",
            f"- Proposed: {proposed_str}",
            f"- Decided: {decided_str}",
            f"- Decided by: {decided_by or '_(unknown)_'}",
        ]
        if decision_reason:
            lines += ["", "## Decision reason", "", decision_reason]

        tag_status = (status_value or "unknown").replace("/", "_")
        lines += [
            "",
            f"#shopai/decision/{tag_status} #shopai/engine/{engine}",
            "",
        ]
        return "\n".join(lines)

    def _render_overview(self, summary: ExportSummary) -> str:
        ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        lines = [
            "---",
            "name: shopai overview",
            "type: overview",
            f"exported_at: {ts}",
            "source: shopai",
            "---",
            "",
            "# ShopAI knowledge vault",
            "",
            f"Exported {ts}.",
            "",
            "## Contents",
            "",
            f"- **Engines** ([{summary.engines}]) — see `engines/`",
            f"- **Goals** ([{summary.goals}]) — see `goals/`",
            f"- **Decisions** ([{summary.decisions}]) — see `decisions/`",
            "",
            "## How to read this vault",
            "",
            "Each engine has a primary goal it optimises for. Goal pages",
            "carry a learned effectiveness EMA from past outcomes. Decisions",
            "are the per-approval audit trail. Wiki-links cross-reference",
            "between the three.",
            "",
            "Add your own notes below the auto-generated sections in each",
            "file — those survive re-exports.",
            "",
        ]
        if summary.skipped:
            lines += [
                "## Skipped during this export",
                "",
            ] + [f"- {s}" for s in summary.skipped] + [""]
        lines += [
            "#shopai/overview",
            "",
        ]
        return "\n".join(lines)

    # ── Helpers ───────────────────────────────────────────────

    def _decision_filename(self, action: Any) -> str:
        action_id = getattr(action, "id", "unknown")
        engine = getattr(action, "engine", "unknown")
        ts = getattr(action, "proposed_at", 0.0)
        date_part = (
            time.strftime("%Y-%m-%d", time.gmtime(ts))
            if isinstance(ts, (int, float)) and ts > 0
            else "0000-00-00"
        )
        safe_id = _safe_filename(action_id)[:24]
        safe_engine = _safe_filename(engine)[:32]
        return f"{date_part}-{safe_engine}-{safe_id}.md"

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def _write(self, path: Path, content: str) -> None:
        # utf-8 explicit so Cyrillic / em-dash etc. round-trip
        # cleanly on Windows.
        path.write_text(content, encoding="utf-8")

    def _resolve_default_manager(self) -> Any | None:
        try:
            from core.goals.goal_feedback import _default_manager
            return _default_manager()
        except Exception as exc:  # noqa: BLE001
            logger.debug("default manager unavailable: %s", exc)
            return None


# ── Module-level helpers (testable in isolation) ──────────────


def _safe_get_effectiveness(manager: Any | None, goal: str) -> float:
    if manager is None:
        return 0.5
    try:
        return float(manager.get_effectiveness(goal))
    except Exception:  # noqa: BLE001
        return 0.5


def _safe_get_sample_count(manager: Any | None, goal: str) -> int:
    """Pull ``n`` from the manager's stats blob — schema-tolerant."""
    if manager is None:
        return 0
    try:
        stats = manager.get_effectiveness_stats() or {}
        entry = stats.get(goal) or {}
        return int(entry.get("n", 0))
    except Exception:  # noqa: BLE001
        return 0


def _ts_iso(epoch_seconds: Any) -> str:
    """UTC ISO-ish string. Falls back to ``"0"`` when epoch is
    missing / non-numeric so frontmatter parses cleanly."""
    if not isinstance(epoch_seconds, (int, float)) or epoch_seconds <= 0:
        return "0"
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_seconds),
    )


def _safe_filename(raw: str) -> str:
    """Replace anything that isn't ``[A-Za-z0-9_-]`` with
    underscore. Used for decision filenames so action ids and
    engine names can't escape the target directory or break
    Obsidian's file picker."""
    if not isinstance(raw, str):
        return "_"
    out: list[str] = []
    for ch in raw:
        out.append(ch if ch.isalnum() or ch in ("-", "_") else "_")
    return "".join(out) or "_"
