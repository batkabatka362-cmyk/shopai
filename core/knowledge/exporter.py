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
        """One Markdown file per entry in ``ENGINE_GOAL_MAP``.

        Pre-computes signal streams once per export so each engine
        page renders its enrichment block without N independent
        queue / store queries:

          * ``decisions_by_engine`` — recent approvals grouped by
            engine name, newest first, capped per-engine.
          * ``goal_stats`` — ``GoalManager`` effectiveness +
            sample counts for every goal at once.
          * ``notes_by_engine`` — operator's persisted commentary
            from the NotesStore.
          * ``quarantine_by_engine`` — exempt / released / alert-
            paused state from the quarantine module so each engine
            page can flag itself as paused (with scope).
          * ``alerts_by_engine`` — recent EngineAlert events +
            consecutive-day streak from the alert-history log.

        Source-failure isolated: a missing approval DB or store
        records nothing — the per-engine page degrades to the
        bare placeholder it had pre-enrichment.
        """
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP

        decisions_by_engine = self._collect_decisions_by_engine()
        goal_stats = self._collect_goal_stats()
        notes_by_engine = self._collect_engine_notes()
        quarantine_by_engine = self._collect_quarantine_state()
        alerts_by_engine = self._collect_alert_summary()
        trajectory_by_engine = self._collect_score_trajectory()

        engines_dir = self.target_dir / "engines"
        self._ensure_dir(engines_dir)
        count = 0
        for engine, goal in sorted(ENGINE_GOAL_MAP.items()):
            body = self._render_engine(
                engine,
                goal,
                recent_decisions=decisions_by_engine.get(engine, []),
                goal_effectiveness=goal_stats.get(goal),
                persisted_notes=notes_by_engine.get(engine, ""),
                quarantine=quarantine_by_engine.get(engine),
                alerts=alerts_by_engine.get(engine),
                trajectory=trajectory_by_engine.get(engine, []),
            )
            self._write(engines_dir / f"{engine}.md", body)
            count += 1
        return count

    # ── Signal collectors (called once per export) ─────────────

    def _collect_decisions_by_engine(
        self,
    ) -> dict[str, list[Any]]:
        """Group recent executed approvals by engine.

        Pulls a wide window (500) then trims per-engine to the
        five most recent. Newest-first ordering matches the way
        the engine page renders them.
        """
        try:
            from core.approval import get_approval_queue
            queue = get_approval_queue()
            history = queue.list_executed(limit=500) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug("decisions collection failed: %s", exc)
            return {}

        per_engine: dict[str, list[Any]] = {}
        for action in history:
            engine = getattr(action, "engine", "") or ""
            if not engine:
                continue
            bucket = per_engine.setdefault(engine, [])
            if len(bucket) < 5:
                bucket.append(action)
        return per_engine

    def _collect_goal_stats(self) -> dict[str, dict[str, Any]]:
        """Snapshot every goal's EMA + sample count in one call."""
        mgr = self.goal_manager or self._resolve_default_manager()
        if mgr is None:
            return {}
        try:
            stats = mgr.get_effectiveness_stats() or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("goal stats collection failed: %s", exc)
            return {}
        return {
            goal: dict(entry) for goal, entry in stats.items()
            if isinstance(entry, dict)
        }

    def _collect_engine_notes(self) -> dict[str, str]:
        """Pull persisted operator notes keyed by engine name.

        Returns ``{engine: text}`` — empty when the NotesStore
        is unavailable or has no entries.
        """
        try:
            from core.knowledge.notes_store import get_default_store
            store = get_default_store()
            raw = store.all_engine_notes()
        except Exception as exc:  # noqa: BLE001
            logger.debug("notes collection failed: %s", exc)
            return {}
        out: dict[str, str] = {}
        for engine, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("notes", "") or "").strip()
            if text:
                out[engine] = text
        return out

    def _collect_quarantine_state(self) -> dict[str, dict[str, Any]]:
        """Snapshot per-engine quarantine state.

        Returns ``{engine: {flags, fleet_paused, stores_paused,
        exempt, released}}`` for engines that have ANY non-default
        state. Engines with no entry render no Quarantine block.

        ``flags`` is a sorted list of human-readable tokens
        (``"exempt"``, ``"released"``, ``"alert_paused_fleet"``,
        ``"alert_paused_per_store"``) so the renderer can build
        a one-line summary without re-deriving them.
        """
        try:
            from core.approval.quarantine import load_state
            state = load_state()
        except Exception as exc:  # noqa: BLE001
            logger.debug("quarantine state collection failed: %s", exc)
            return {}

        per_engine: dict[str, dict[str, Any]] = {}
        for engine in state.exemptions:
            per_engine.setdefault(engine, _empty_quarantine_entry())
            per_engine[engine]["exempt"] = True
        for engine in state.released:
            per_engine.setdefault(engine, _empty_quarantine_entry())
            per_engine[engine]["released"] = True
        for engine, store_id in state.alert_paused:
            per_engine.setdefault(engine, _empty_quarantine_entry())
            if store_id is None:
                per_engine[engine]["fleet_paused"] = True
            else:
                per_engine[engine]["stores_paused"].append(store_id)

        for engine, entry in per_engine.items():
            entry["stores_paused"] = sorted(set(entry["stores_paused"]))
            flags: list[str] = []
            if entry["exempt"]:
                flags.append("exempt")
            if entry["released"]:
                flags.append("released")
            if entry["fleet_paused"]:
                flags.append("alert_paused_fleet")
            if entry["stores_paused"]:
                flags.append("alert_paused_per_store")
            entry["flags"] = flags
        return per_engine

    def _collect_alert_summary(self) -> dict[str, dict[str, Any]]:
        """Snapshot recent alert history keyed by engine.

        Returns ``{engine: {recent: [...], streak_days: int}}``
        where ``recent`` is the newest-first list of the last 5
        :class:`AlertEvent` records (within a 7-day window) and
        ``streak_days`` is the count of distinct daily buckets
        that fired alerts for the engine in that window.

        Source-failure isolated -- a missing alert-history file
        returns an empty dict so the page still renders.
        """
        try:
            from core.approval.alert_history import (
                consecutive_runs_per_engine,
                recent_history,
            )
            events = recent_history(since_seconds=86400.0 * 7.0)
            streaks = consecutive_runs_per_engine(
                window_seconds=86400.0 * 7.0,
                bucket_seconds=86400.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("alert summary collection failed: %s", exc)
            return {}

        per_engine: dict[str, dict[str, Any]] = {}
        for event in events:
            engine = getattr(event, "engine", "") or ""
            if not engine:
                continue
            bucket = per_engine.setdefault(
                engine,
                {"recent": [], "streak_days": 0},
            )
            if len(bucket["recent"]) < 5:
                bucket["recent"].append(event)
        for engine, count in streaks.items():
            bucket = per_engine.setdefault(
                engine,
                {"recent": [], "streak_days": 0},
            )
            bucket["streak_days"] = int(count)
        return per_engine

    def _collect_score_trajectory(
        self,
    ) -> dict[str, list[Any]]:
        """Snapshot recorded engine_health scores by engine.

        Returns ``{engine: [ScoreEvent, ...]}`` newest-first,
        capped at the last 10 events per engine in the 30-day
        window. Engines with no recorded scores are absent
        from the dict.

        Source-failure isolated: a missing
        engine_health_history module returns an empty dict so
        the engine page still renders without the trajectory
        block.
        """
        try:
            from core.approval.engine_health_history import (
                recent_history,
            )
            events = recent_history(
                since_seconds=86400.0 * 30.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "score_trajectory collection failed: %s", exc,
            )
            return {}

        per_engine: dict[str, list[Any]] = {}
        for event in events:
            engine = getattr(event, "engine", "") or ""
            if not engine:
                continue
            bucket = per_engine.setdefault(engine, [])
            if len(bucket) < 10:
                bucket.append(event)
        return per_engine

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

    def _render_engine(
        self,
        engine: str,
        goal: str,
        *,
        recent_decisions: list[Any] | None = None,
        goal_effectiveness: dict[str, Any] | None = None,
        persisted_notes: str = "",
        quarantine: dict[str, Any] | None = None,
        alerts: dict[str, Any] | None = None,
        trajectory: list[Any] | None = None,
    ) -> str:
        """Render one engine page.

        The kwargs come from the pre-computed signals in
        :meth:`_export_engines`. All three are optional so this
        renderer remains usable from tests that want a plain
        page without seeding the queue / manager / store.
        """
        recent_decisions = recent_decisions or []
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
        ]

        # Performance block — only when we have a real EMA reading
        # (i.e. the manager has recorded outcomes for the goal).
        # Skip when stats are missing so the page doesn't lie
        # about precision.
        if isinstance(goal_effectiveness, dict):
            eff = goal_effectiveness.get("effectiveness")
            samples = goal_effectiveness.get("n", 0)
            if eff is not None and isinstance(samples, int):
                lines += [
                    "## Performance",
                    "",
                    f"- Primary goal: [[{goal}]]",
                    f"- Goal effectiveness EMA: {float(eff):.3f}",
                    f"- Samples: {samples} outcome event(s)",
                    f"- Executed approvals for this engine: "
                    f"{len(recent_decisions)} in recent window",
                    "",
                ]

        # Quarantine + alerts block — operator immediately sees
        # whether the engine is paused / exempt / released and
        # how many days it has been firing degradation alerts.
        # Each line is omitted independently so a healthy engine
        # produces no section at all.
        q_lines = _render_quarantine_block(quarantine, alerts)
        if q_lines:
            lines += ["## Quarantine & alerts", ""]
            lines += q_lines
            lines.append("")

        # Score trajectory block -- engine_health_history events
        # rendered as a tight per-row "date score verdict" list.
        # Operators reviewing the engine in Obsidian see the
        # directional read alongside the static state above.
        # Omitted entirely when there are no recorded events.
        t_lines = _render_score_trajectory_block(trajectory)
        if t_lines:
            lines += ["## Score trajectory", ""]
            lines += t_lines
            lines.append("")

        # Recent decisions block — bullet-list, most recent first
        if recent_decisions:
            lines += [
                "## Recent activity",
                "",
            ]
            for action in recent_decisions:
                action_type = getattr(action, "action_type", "")
                decided_at = getattr(action, "decided_at", 0) or 0
                ts = (
                    time.strftime(
                        "%Y-%m-%d %H:%M", time.gmtime(decided_at),
                    )
                    if isinstance(decided_at, (int, float))
                    and decided_at > 0
                    else "—"
                )
                status = getattr(action, "status", None)
                status_value = (
                    status.value
                    if hasattr(status, "value")
                    else str(status or "")
                )
                narrative = (
                    getattr(action, "narrative", "") or ""
                )
                lines.append(
                    f"- **{ts}** · `{action_type}` · "
                    f"_{status_value}_"
                )
                if narrative:
                    short = narrative[:140]
                    if len(narrative) > 140:
                        short += "…"
                    lines.append(f"    - {short}")
            lines.append("")

        # Persisted operator notes — surface what the operator
        # has previously written, distinct from the empty
        # placeholder section below.
        if persisted_notes:
            lines += [
                "## Persisted operator notes",
                "",
            ]
            for line in persisted_notes.splitlines():
                lines.append(f"> {line}" if line else ">")
            lines.append("")
            lines.append(
                "_Imported from a previous "
                "`shopai knowledge import` pass. "
                "Update by editing the section below and "
                "re-importing._"
            )
            lines.append("")

        lines += [
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


def _empty_quarantine_entry() -> dict[str, Any]:
    """Default shape used by :meth:`ObsidianExporter
    ._collect_quarantine_state` so each engine bucket has a
    stable schema regardless of which signals populate it."""
    return {
        "exempt": False,
        "released": False,
        "fleet_paused": False,
        "stores_paused": [],
        "flags": [],
    }


def _render_quarantine_block(
    quarantine: dict[str, Any] | None,
    alerts: dict[str, Any] | None,
) -> list[str]:
    """Render the "Quarantine & alerts" block for one engine.

    Returns an empty list when both inputs are empty / absent --
    the caller skips emitting the section header entirely so
    healthy engines stay clean.

    The block lists, in order:
      * exempt / released flag, when set.
      * fleet-wide alert pause, when set.
      * per-store alert pauses as a bullet list, when any.
      * 7-day alert-streak count, when > 0.
      * up to 5 most recent ``AlertEvent`` rows as bullets.
    """
    quarantine = quarantine or {}
    alerts = alerts or {}
    lines: list[str] = []

    if quarantine.get("exempt"):
        lines.append(
            "- **Exempt** -- engine is on the never-quarantine list."
        )
    if quarantine.get("released"):
        lines.append(
            "- **Released** -- operator cleared a prior quarantine; "
            "auto-quarantine is bypassed until removed."
        )
    if quarantine.get("fleet_paused"):
        lines.append(
            "- **Alert-paused (fleet)** -- enqueues for every store "
            "are rejected until released."
        )
    stores = quarantine.get("stores_paused") or []
    if stores:
        lines.append("- **Alert-paused (per-store):**")
        for store_id in stores:
            lines.append(f"    - `{store_id}`")

    streak = int(alerts.get("streak_days", 0) or 0)
    if streak > 0:
        lines.append(
            f"- Alert streak (last 7d): **{streak} day(s)** with "
            "at least one degradation alert."
        )

    recent = alerts.get("recent") or []
    if recent:
        lines.append("- Recent alerts:")
        for event in recent[:5]:
            recorded_at = getattr(event, "recorded_at", 0.0) or 0.0
            ts = (
                time.strftime(
                    "%Y-%m-%d %H:%M", time.gmtime(recorded_at),
                )
                if isinstance(recorded_at, (int, float))
                and recorded_at > 0
                else "--"
            )
            store_id = getattr(event, "store_id", None)
            scope = (
                f"@{store_id}" if store_id else "(fleet)"
            )
            drop = getattr(event, "drop", None)
            drop_str = (
                f"{float(drop):.0%} drop"
                if isinstance(drop, (int, float))
                else "drop ?"
            )
            recent_score = getattr(event, "recent_score", None)
            baseline_score = getattr(event, "baseline_score", None)
            score_str = ""
            if (
                isinstance(recent_score, (int, float))
                and isinstance(baseline_score, (int, float))
            ):
                score_str = (
                    f" -- recent={float(recent_score):.2f} "
                    f"baseline={float(baseline_score):.2f}"
                )
            lines.append(
                f"    - **{ts}** {scope} `{drop_str}`{score_str}"
            )

    return lines


def _render_score_trajectory_block(
    trajectory: list[Any] | None,
) -> list[str]:
    """Render the "Score trajectory" block for one engine.

    ``trajectory`` is a list of ``ScoreEvent`` (or any object
    with ``recorded_at`` / ``score`` / ``verdict`` attrs),
    newest-first, capped at 10 by the collector. Returns an
    empty list when the input is empty so the caller can skip
    emitting the section header for engines without recorded
    history.
    """
    trajectory = trajectory or []
    if not trajectory:
        return []
    lines: list[str] = []
    for event in trajectory:
        recorded_at = getattr(event, "recorded_at", 0.0) or 0.0
        ts = (
            time.strftime(
                "%Y-%m-%d %H:%M", time.gmtime(recorded_at),
            )
            if isinstance(recorded_at, (int, float))
            and recorded_at > 0
            else "--"
        )
        score = getattr(event, "score", None)
        verdict = getattr(event, "verdict", "") or "?"
        if isinstance(score, int):
            score_str = f"{score:>2d}/10"
        else:
            score_str = "?/10"
        lines.append(
            f"- **{ts}**  `{score_str}`  {verdict}"
        )
    return lines
