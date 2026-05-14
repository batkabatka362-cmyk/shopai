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

        # Compose
        lines: list[str] = []
        lines += self._render_header()
        lines += self._render_active_goal(active_goal, mgr)
        lines += self._render_recommendations(recommendations)
        lines += self._render_goal_table(goal_table)
        lines += self._render_decisions(decisions)
        lines += self._render_engine_activity(engine_counts)
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
            except Exception:  # noqa: BLE001
                pass
            try:
                stats = mgr.get_effectiveness_stats() or {}
                samples = int((stats.get(goal) or {}).get("n", 0))
            except Exception:  # noqa: BLE001
                pass
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

    # ── Internal ──────────────────────────────────────────────

    def _resolve_default_manager(self) -> Any | None:
        try:
            from core.goals.goal_feedback import _default_manager
            return _default_manager()
        except Exception as exc:  # noqa: BLE001
            logger.debug("default manager unavailable: %s", exc)
            return None
