"""Insight digest — periodic Markdown briefing summarising
ShopAI's recent activity.

Where ``exporter.py`` produces a full Markdown reference vault
(one file per engine / goal / decision), the digest produces a
SINGLE file: "What's been happening lately?" The intent is
twofold:

  1. **Operator morning briefing.** One scrollable page covering
     active goal + top recommendations + recent decisions + goal
     EMA trends, suitable to skim at the start of a session.
  2. **NotebookLM training input.** Rolling weekly digests fed
     into a NotebookLM notebook give the retrieval layer a
     compact, chronological narrative to ground future LLM
     prompts in.

The digest is **derived** — every signal comes from sources the
exporter already reads (``GoalManager``, ``ApprovalQueue``,
``ENGINE_GOAL_MAP``, ``engine_recommender``). It's a compact
rendering, not a new data store.

Sections
--------
* **Active goal & priority** — what GoalManager picks right now
  and why.
* **Top recommendations** — engine_recommender's top 5.
* **Goal effectiveness leaderboard** — every goal's EMA sorted
  desc, with sample count so neutral defaults can be told apart
  from "actually neutral after data" cases.
* **Recent decisions** — last N approvals (default 20), newest
  first.
* **Per-engine activity** — engines that appeared in those
  decisions, with counts.

Usage
-----
::

    from core.knowledge import InsightDigest

    digest = InsightDigest(since_days=7, decision_limit=20)
    markdown = digest.render()         # string
    digest.write_to("/path/digest.md") # convenience writer

CLI: ``shopai knowledge digest --out <path>``.
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("core.knowledge.digest")


_DEFAULT_DECISION_LIMIT = 20
_DEFAULT_SINCE_DAYS = 7


@dataclass
class DigestStats:
    """Counts surfaced in the digest. Returned alongside the
    rendered Markdown so a CLI / API caller can summarise the
    digest in one line without re-parsing it."""

    active_goal: str = "maximize_profit"
    decisions_window: int = 0
    decisions_total_executed: int = 0
    decisions_total_failed: int = 0
    top_engine: str = ""
    skipped: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_goal": self.active_goal,
            "decisions_window": self.decisions_window,
            "decisions_total_executed": self.decisions_total_executed,
            "decisions_total_failed": self.decisions_total_failed,
            "top_engine": self.top_engine,
            "skipped": list(self.skipped or []),
        }


class InsightDigest:
    """Render a one-page Markdown briefing.

    Args:
        since_days: Window for the "Recent decisions" section.
            Decisions older than this are excluded from the
            window count + per-engine breakdown, but the total-
            executed / total-failed counts still reflect the
            full queue history.
        decision_limit: Max decisions to render in the bullet
            list (default 20, newest first). Bounded so the
            digest stays scannable.
        goal_manager: Optional :class:`GoalManager`. Defaults
            to the goal-feedback singleton.
        recommendation_limit: How many recommender picks to
            display under "Top recommendations" (default 5).
    """

    def __init__(
        self,
        *,
        since_days: int = _DEFAULT_SINCE_DAYS,
        decision_limit: int = _DEFAULT_DECISION_LIMIT,
        goal_manager: Any | None = None,
        recommendation_limit: int = 5,
    ) -> None:
        self.since_days = max(1, int(since_days))
        self.decision_limit = max(0, int(decision_limit))
        self.goal_manager = goal_manager
        self.recommendation_limit = max(1, int(recommendation_limit))

    # ── Public API ────────────────────────────────────────────

    def render(self) -> tuple[str, DigestStats]:
        """Build the Markdown digest. Returns ``(markdown, stats)``.

        Never raises — source failures record a ``skipped``
        diagnostic on the stats and the affected section
        degrades gracefully (header + "no data" line).
        """
        stats = DigestStats(skipped=[])
        mgr = self.goal_manager or self._resolve_default_manager()

        # Pull the four signal streams.
        active_goal = self._active_goal(mgr, stats)
        stats.active_goal = active_goal
        recommendations = self._top_recommendations(active_goal, mgr, stats)
        goal_table = self._goal_leaderboard(mgr, stats)
        decisions, engine_counts, totals = self._recent_decisions(stats)
        stats.decisions_window = len(decisions)
        stats.decisions_total_executed = totals.get("executed", 0)
        stats.decisions_total_failed = totals.get("failed", 0)
        if engine_counts:
            stats.top_engine = engine_counts.most_common(1)[0][0]

        # Operator notes — surface anything persisted via the
        # importer. Highlights the engines/goals the operator
        # has actually annotated so the digest doesn't get
        # cluttered when there's nothing to say.
        engine_notes, goal_notes = self._operator_notes(
            recommendations, active_goal, stats,
        )

        # Engine health — flag currently-paused engines (exempt /
        # released / alert_paused) plus the 5 most recent alert
        # firings. Omitted entirely when nothing's flagged so the
        # digest doesn't carry empty headers.
        health = self._engine_health(stats)

        # Compose
        lines: list[str] = []
        lines += self._render_header()
        lines += self._render_active_goal(active_goal, mgr)
        lines += self._render_recommendations(recommendations)
        lines += self._render_goal_table(goal_table)
        if health["paused_engines"] or health["recent_alerts"]:
            lines += self._render_engine_health(health)
        lines += self._render_decisions(decisions)
        lines += self._render_engine_activity(engine_counts)
        if engine_notes or goal_notes:
            lines += self._render_operator_notes(
                engine_notes, goal_notes,
            )
        if stats.skipped:
            lines += self._render_skipped(stats.skipped)
        return "\n".join(lines), stats

    def write_to(self, path: str | Path) -> DigestStats:
        """Convenience writer — renders + writes the markdown to
        ``path``. The parent directory is created if missing.
        Returns the same stats ``render`` would.
        """
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        markdown, stats = self.render()
        target.write_text(markdown, encoding="utf-8")
        return stats

    # ── Signal-gathering helpers ──────────────────────────────

    def _active_goal(
        self, mgr: Any | None, stats: DigestStats,
    ) -> str:
        if mgr is None:
            return "maximize_profit"
        try:
            current = mgr.get_current_goal()
            if isinstance(current, str) and current:
                return current
        except Exception as exc:  # noqa: BLE001
            stats.skipped.append(f"active_goal: {exc}")
        return "maximize_profit"

    def _top_recommendations(
        self,
        active_goal: str,
        mgr: Any | None,
        stats: DigestStats,
    ) -> list[Any]:
        try:
            from core.brain.engine_recommender import recommend_engines
            result = recommend_engines(
                goal=active_goal,
                limit=self.recommendation_limit,
                manager=mgr,
                include_alternatives=False,
            )
            return list(result.primary)
        except Exception as exc:  # noqa: BLE001
            stats.skipped.append(f"recommendations: {exc}")
            return []

    def _goal_leaderboard(
        self, mgr: Any | None, stats: DigestStats,
    ) -> list[tuple[str, float, int]]:
        """``[(goal, effectiveness, sample_count), ...]`` sorted
        by effectiveness DESC. Includes every canonical goal even
        when no data — neutral 0.5 / samples=0 still rendered so
        operators can see "nothing learned yet" explicitly."""
        try:
            from core.goals.goal_manager import GOAL_DEFINITIONS
        except Exception as exc:  # noqa: BLE001
            stats.skipped.append(f"goal_table: {exc}")
            return []
        rows: list[tuple[str, float, int]] = []
        all_stats: dict[str, dict[str, Any]] = {}
        if mgr is not None:
            try:
                all_stats = mgr.get_effectiveness_stats() or {}
            except Exception as exc:  # noqa: BLE001
                stats.skipped.append(f"goal_stats: {exc}")
        for goal in GOAL_DEFINITIONS:
            entry = all_stats.get(goal) or {}
            eff = float(entry.get("effectiveness", 0.5) or 0.5)
            samples = int(entry.get("n", 0) or 0)
            rows.append((goal, eff, samples))
        rows.sort(key=lambda r: (-r[1], r[0]))
        return rows

    def _recent_decisions(
        self, stats: DigestStats,
    ) -> tuple[list[Any], Counter, dict[str, int]]:
        """Pull EXECUTED/FAILED actions, filter by the window,
        count totals + per-engine activity.

        Returns ``(window_actions, engine_counts, totals)``:

        * ``window_actions``: at most ``decision_limit`` actions
          newest-first, filtered to ones decided within
          ``since_days``.
        * ``engine_counts``: per-engine counter across the
          window.
        * ``totals``: ``{"executed": N, "failed": M}`` across
          the queue's full visible history (NOT windowed) — so
          the digest can report a cumulative score next to the
          windowed list.
        """
        try:
            from core.approval import get_approval_queue
            queue = get_approval_queue()
        except Exception as exc:  # noqa: BLE001
            stats.skipped.append(f"decisions: {exc}")
            return [], Counter(), {}

        try:
            history = queue.list_executed(limit=500) or []
        except Exception as exc:  # noqa: BLE001
            stats.skipped.append(f"list_executed: {exc}")
            return [], Counter(), {}

        cutoff = time.time() - self.since_days * 86400
        windowed: list[Any] = []
        engine_counts: Counter = Counter()
        totals: dict[str, int] = {"executed": 0, "failed": 0}

        for action in history:
            status = getattr(action, "status", None)
            status_value = (
                status.value
                if hasattr(status, "value")
                else str(status or "")
            )
            if status_value == "executed":
                totals["executed"] += 1
            elif status_value == "failed":
                totals["failed"] += 1

            decided_at = getattr(action, "decided_at", None) or 0
            if not isinstance(decided_at, (int, float)):
                continue
            if decided_at < cutoff:
                continue
            engine = getattr(action, "engine", "unknown")
            engine_counts[engine] += 1
            if len(windowed) < self.decision_limit:
                windowed.append(action)

        return windowed, engine_counts, totals

    # ── Markdown renderers ────────────────────────────────────

    def _render_header(self) -> list[str]:
        ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        return [
            "---",
            f"generated_at: {ts}",
            f"since_days: {self.since_days}",
            "type: digest",
            "source: shopai",
            "---",
            "",
            "# ShopAI Insight Digest",
            "",
            f"_Generated {ts} · window: last {self.since_days}d_",
            "",
        ]

    def _render_active_goal(
        self, goal: str, mgr: Any | None,
    ) -> list[str]:
        eff = 0.5
        samples = 0
        if mgr is not None:
            try:
                eff = float(mgr.get_effectiveness(goal))
            except Exception as exc:  # noqa: BLE001
                # Manager exists but couldn't return a value for
                # this goal (unknown goal name, broken backing
                # store, etc.). Degrade silently to neutral
                # default — the rendered marker will reflect
                # "no_data" via the samples-zero check below.
                logger.debug(
                    "active_goal effectiveness lookup failed: %s", exc,
                )
            try:
                stats = mgr.get_effectiveness_stats() or {}
                samples = int((stats.get(goal) or {}).get("n", 0))
            except Exception as exc:  # noqa: BLE001
                # Same fallback path — samples stays 0 which is
                # the truthful default when we couldn't read it.
                logger.debug(
                    "active_goal stats lookup failed: %s", exc,
                )
        marker = "no_data" if samples == 0 else f"{eff:.3f}"
        return [
            "## Active goal",
            "",
            f"**[[{goal}]]** — effectiveness {marker} "
            f"({samples} sample{'s' if samples != 1 else ''})",
            "",
        ]

    def _render_recommendations(
        self, recommendations: list[Any],
    ) -> list[str]:
        out = ["## Top recommendations", ""]
        if not recommendations:
            out.append("_(no recommendations available)_")
            out.append("")
            return out
        out.append("| Rank | Engine | Priority | Effectiveness |")
        out.append("|------|--------|----------|---------------|")
        for i, r in enumerate(recommendations, 1):
            engine = getattr(r, "engine", "?")
            priority = float(getattr(r, "priority", 0.0))
            eff = float(getattr(r, "effectiveness", 0.5))
            out.append(
                f"| {i} | [[{engine}]] | "
                f"{priority:.2f} | {eff:.2f} |"
            )
        out.append("")
        return out

    def _render_goal_table(
        self, rows: list[tuple[str, float, int]],
    ) -> list[str]:
        out = ["## Goal effectiveness leaderboard", ""]
        if not rows:
            out.append("_(goal data unavailable)_")
            out.append("")
            return out
        out.append("| Goal | Effectiveness | Samples |")
        out.append("|------|---------------|---------|")
        for goal, eff, samples in rows:
            label = "no_data" if samples == 0 else f"{eff:.3f}"
            out.append(
                f"| [[{goal}]] | {label} | {samples} |"
            )
        out.append("")
        return out

    def _render_decisions(
        self, decisions: list[Any],
    ) -> list[str]:
        out = [
            f"## Recent decisions (last {self.since_days}d)",
            "",
        ]
        if not decisions:
            out.append("_(no decisions in this window)_")
            out.append("")
            return out
        for action in decisions:
            engine = getattr(action, "engine", "?")
            action_type = getattr(action, "action_type", "")
            status = getattr(action, "status", None)
            status_value = (
                status.value
                if hasattr(status, "value")
                else str(status or "")
            )
            decided_at = getattr(action, "decided_at", 0) or 0
            ts = (
                time.strftime(
                    "%Y-%m-%d %H:%M", time.gmtime(decided_at),
                )
                if isinstance(decided_at, (int, float)) and decided_at > 0
                else "—"
            )
            narrative = getattr(action, "narrative", "") or ""
            # Compact one-liner per decision; full detail stays in
            # the per-decision exporter pages.
            out.append(
                f"- **{ts}** · [[{engine}]] · "
                f"`{action_type}` · _{status_value}_"
            )
            if narrative:
                # Indent the narrative as a sub-bullet so the
                # outline stays readable; truncate at 140 chars to
                # keep digest scannable.
                short = narrative[:140]
                if len(narrative) > 140:
                    short += "…"
                out.append(f"    - {short}")
        out.append("")
        return out

    def _engine_health(
        self, stats: DigestStats,
    ) -> dict[str, Any]:
        """Pull current quarantine state + recent alert events.

        Returns ``{paused_engines: [...], recent_alerts: [...]}``
        where ``paused_engines`` is a list of ``(engine, flags,
        stores)`` tuples and ``recent_alerts`` is the newest-first
        list of the last 5 :class:`AlertEvent` rows in a 7-day
        window. Both sub-sources fail open -- a missing
        quarantine_state.json or unreadable alert_history.json
        contributes empty data instead of aborting the digest.
        """
        result: dict[str, Any] = {
            "paused_engines": [],
            "recent_alerts": [],
        }
        try:
            from core.approval.quarantine import load_state
            state = load_state()
        except Exception as exc:  # noqa: BLE001
            stats.skipped.append(f"engine_health_quarantine: {exc}")
            state = None

        if state is not None:
            per_engine: dict[str, dict[str, Any]] = {}
            for engine in state.exemptions:
                per_engine.setdefault(engine, _empty_paused_row())
                per_engine[engine]["exempt"] = True
            for engine in state.released:
                per_engine.setdefault(engine, _empty_paused_row())
                per_engine[engine]["released"] = True
            for engine, store_id in state.alert_paused:
                per_engine.setdefault(engine, _empty_paused_row())
                if store_id is None:
                    per_engine[engine]["fleet_paused"] = True
                else:
                    per_engine[engine]["stores"].append(store_id)
            for engine, entry in sorted(per_engine.items()):
                entry["stores"] = sorted(set(entry["stores"]))
                flags: list[str] = []
                if entry["exempt"]:
                    flags.append("exempt")
                if entry["released"]:
                    flags.append("released")
                if entry["fleet_paused"]:
                    flags.append("alert_paused_fleet")
                if entry["stores"]:
                    flags.append("alert_paused_per_store")
                result["paused_engines"].append({
                    "engine": engine,
                    "flags": flags,
                    "stores": entry["stores"],
                })

        try:
            from core.approval.alert_history import recent_history
            events = recent_history(since_seconds=86400.0 * 7.0)
        except Exception as exc:  # noqa: BLE001
            stats.skipped.append(f"engine_health_alerts: {exc}")
            events = []
        result["recent_alerts"] = list(events[:5])
        return result

    def _render_engine_activity(
        self, engine_counts: Counter,
    ) -> list[str]:
        out = ["## Engine activity in window", ""]
        if not engine_counts:
            out.append("_(no engine activity)_")
            out.append("")
            return out
        out.append("| Engine | Decisions |")
        out.append("|--------|-----------|")
        for engine, count in engine_counts.most_common(10):
            out.append(f"| [[{engine}]] | {count} |")
        out.append("")
        return out

    def _render_skipped(self, skipped: list[str]) -> list[str]:
        out = ["## Sources skipped during render", ""]
        for s in skipped:
            out.append(f"- {s}")
        out.append("")
        out.append("_These sources were unavailable — usually means "
                   "the corresponding subsystem isn't initialised._")
        out.append("")
        return out

    def _operator_notes(
        self,
        recommendations: list[Any],
        active_goal: str,
        stats: DigestStats,
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Pull persisted operator notes that are relevant RIGHT NOW.

        Two filters keep the section signal-dense:
          * **Engine notes** — only for engines that appear in the
            current top-recommendations list. Notes on engines that
            won't run anyway are noise.
          * **Goal notes** — only for the active goal. The leaderboard
            already shows every goal; commentary lives next to the
            one the system is optimising for.

        Returns ``(engine_notes, goal_notes)`` — each a list of
        ``(name, text)`` tuples. Empty when the notes store is
        unavailable or has nothing relevant.
        """
        try:
            from core.knowledge.notes_store import get_default_store
            store = get_default_store()
        except Exception as exc:  # noqa: BLE001
            stats.skipped.append(f"operator_notes: {exc}")
            return [], []

        try:
            engine_map = store.all_engine_notes()
            goal_map = store.all_goal_notes()
        except Exception as exc:  # noqa: BLE001
            stats.skipped.append(f"operator_notes_read: {exc}")
            return [], []

        # Filter engine notes to current recommendation names
        rec_engines = [
            getattr(r, "engine", "") for r in recommendations
        ]
        engine_notes: list[tuple[str, str]] = []
        for engine in rec_engines:
            entry = engine_map.get(engine)
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("notes", "") or "").strip()
            if text:
                engine_notes.append((engine, text))

        # Active-goal note (singular — at most one)
        goal_notes: list[tuple[str, str]] = []
        goal_entry = goal_map.get(active_goal)
        if isinstance(goal_entry, dict):
            text = str(goal_entry.get("notes", "") or "").strip()
            if text:
                goal_notes.append((active_goal, text))

        return engine_notes, goal_notes

    def _render_engine_health(
        self, health: dict[str, Any],
    ) -> list[str]:
        """Render the engine-health section.

        Caller is responsible for skipping this when both
        ``paused_engines`` and ``recent_alerts`` are empty -- this
        method does NOT defensively return [] for that case so the
        header stays consistent with the rest of the digest.
        """
        out = ["## Engine health", ""]
        paused = health.get("paused_engines") or []
        if paused:
            out.append("### Currently flagged engines")
            out.append("")
            out.append("| Engine | Flags | Stores |")
            out.append("|--------|-------|--------|")
            for row in paused:
                engine = row["engine"]
                flags = ", ".join(row["flags"]) or "-"
                stores = (
                    ", ".join(f"`{s}`" for s in row["stores"])
                    if row["stores"] else "-"
                )
                out.append(f"| [[{engine}]] | {flags} | {stores} |")
            out.append("")

        recent = health.get("recent_alerts") or []
        if recent:
            out.append("### Recent degradation alerts (7d)")
            out.append("")
            for event in recent:
                engine = getattr(event, "engine", "") or "?"
                drop = getattr(event, "drop", None)
                drop_str = (
                    f"{float(drop):.0%}"
                    if isinstance(drop, (int, float))
                    else "?"
                )
                store_id = getattr(event, "store_id", None)
                scope = f"@{store_id}" if store_id else "(fleet)"
                recorded_at = (
                    getattr(event, "recorded_at", 0.0) or 0.0
                )
                ts = (
                    time.strftime(
                        "%Y-%m-%d %H:%M",
                        time.gmtime(recorded_at),
                    )
                    if isinstance(recorded_at, (int, float))
                    and recorded_at > 0
                    else "--"
                )
                out.append(
                    f"- **{ts}** [[{engine}]] {scope} "
                    f"drop=`{drop_str}`"
                )
            out.append("")
        return out

    def _render_operator_notes(
        self,
        engine_notes: list[tuple[str, str]],
        goal_notes: list[tuple[str, str]],
    ) -> list[str]:
        out = ["## Operator notes (from your vault)", ""]
        if goal_notes:
            out.append("### Active goal")
            out.append("")
            for goal, text in goal_notes:
                out.append(f"**[[{goal}]]**")
                out.append("")
                out += _indent_quote(text)
                out.append("")
        if engine_notes:
            out.append("### Engines in your top recommendations")
            out.append("")
            for engine, text in engine_notes:
                out.append(f"**[[{engine}]]**")
                out.append("")
                out += _indent_quote(text)
                out.append("")
        out.append(
            "_Notes captured via `shopai knowledge import`. "
            "Update them by editing the matching vault page and "
            "re-importing._"
        )
        out.append("")
        return out

    # ── Internal ──────────────────────────────────────────────

    def _resolve_default_manager(self) -> Any | None:
        try:
            from core.goals.goal_feedback import _default_manager
            return _default_manager()
        except Exception as exc:  # noqa: BLE001
            logger.debug("default manager unavailable: %s", exc)
            return None


def _indent_quote(text: str) -> list[str]:
    """Render ``text`` as a Markdown block-quote.

    Used by the operator-notes section so the operator's prose is
    visually distinguished from the surrounding auto-generated
    tables.
    """
    return [f"> {line}" if line else ">"
            for line in text.splitlines()]


def _empty_paused_row() -> dict[str, Any]:
    """Default shape used by :meth:`InsightDigest._engine_health`
    so each engine bucket has a stable schema regardless of which
    signals populate it."""
    return {
        "exempt": False,
        "released": False,
        "fleet_paused": False,
        "stores": [],
    }
