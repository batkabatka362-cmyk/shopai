"""Launch digest — owner-facing weekly summary.

Sprint 2 #3 of AGI_MISSION_PLAN. Pulls from the v33-v38 brain
(autopilot runs, launch_learner distillations, revision_journal
pending/applied, compute_budget archive, insight_synthesizer
active, mood_model snapshot, workflow_bottleneck_detector) and
formats one owner-readable text block with a headline, key
numbers, top insights, and a "what to do next" recommendation.

Designed so Sprint 3's Telegram/Slack adapter can convert this to
a chat message by replacing ``as_text`` with ``as_markdown``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("agents.learning.launch_digest")


@dataclass
class LaunchDigest:
    period_label: str            # "last 24h" / "last 7d" / ...
    generated_ts: float
    launches_total: int
    launches_successful: int
    launches_blocked: int
    distill_proposals: int
    distill_accepted: int
    journal_pending: int
    journal_applied: int
    compute_spent_usd: float
    mood_label: str
    bottleneck_phase: str
    top_insights: list[dict[str, Any]]
    recommendations: list[str]
    period_start_ts: float
    period_end_ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "period_label": self.period_label,
            "generated_ts": self.generated_ts,
            "launches_total": self.launches_total,
            "launches_successful": (
                self.launches_successful
            ),
            "launches_blocked": self.launches_blocked,
            "distill_proposals": self.distill_proposals,
            "distill_accepted": self.distill_accepted,
            "journal_pending": self.journal_pending,
            "journal_applied": self.journal_applied,
            "compute_spent_usd": round(
                self.compute_spent_usd, 4,
            ),
            "mood_label": self.mood_label,
            "bottleneck_phase": self.bottleneck_phase,
            "top_insights": list(self.top_insights),
            "recommendations": list(self.recommendations),
            "period_start_ts": self.period_start_ts,
            "period_end_ts": self.period_end_ts,
        }

    def as_text(self) -> str:
        lines = [
            f"ShopAI digest — {self.period_label}",
            "",
            (
                f"Launches:   {self.launches_successful}"
                f"/{self.launches_total} successful "
                f"({self.launches_blocked} blocked)"
            ),
            (
                f"Learning:   {self.distill_accepted}"
                f"/{self.distill_proposals} proposals "
                f"accepted"
            ),
            (
                f"Journal:    {self.journal_pending} "
                f"pending, {self.journal_applied} applied"
            ),
            (
                f"Spend:      $"
                f"{self.compute_spent_usd:.2f} compute"
            ),
            f"Mood:       {self.mood_label}",
            f"Bottleneck: {self.bottleneck_phase}",
        ]
        if self.top_insights:
            lines.append("")
            lines.append("Top insights:")
            for i in self.top_insights:
                sev = str(i.get("severity", "?"))
                stmt = str(i.get("statement", ""))[:80]
                lines.append(f"  [{sev}] {stmt}")
        if self.recommendations:
            lines.append("")
            lines.append("Recommended next:")
            for r in self.recommendations:
                lines.append(f"  · {r}")
        return "\n".join(lines)

    def as_markdown(self) -> str:
        """Telegram-safe Markdown (v1). Escapes underscores that
        could otherwise start italics mid-text."""
        def _safe(s: str) -> str:
            return str(s).replace("_", r"\_").replace(
                "*", r"\*",
            )

        lines = [
            f"*ShopAI digest — {_safe(self.period_label)}*",
            "",
            (
                f"• *Launches*: {self.launches_successful}/"
                f"{self.launches_total} ok, "
                f"{self.launches_blocked} blocked"
            ),
            (
                f"• *Learning*: {self.distill_accepted}/"
                f"{self.distill_proposals} proposals "
                f"accepted"
            ),
            (
                f"• *Journal*: {self.journal_pending} pending, "
                f"{self.journal_applied} applied"
            ),
            (
                f"• *Spend*: $"
                f"{self.compute_spent_usd:.2f} compute"
            ),
            f"• *Mood*: {_safe(self.mood_label)}",
            f"• *Bottleneck*: {_safe(self.bottleneck_phase)}",
        ]
        if self.top_insights:
            lines.append("")
            lines.append("*Top insights*:")
            for i in self.top_insights:
                sev = _safe(str(i.get("severity", "?")))
                stmt = _safe(str(i.get("statement", ""))[:80])
                lines.append(f"  _\\[{sev}]_ {stmt}")
        if self.recommendations:
            lines.append("")
            lines.append("*Recommended next*:")
            for r in self.recommendations:
                lines.append(f"  · {_safe(r)}")
        lines.append("")
        lines.append(
            "_Reply_: `approve <id>` · `reject <id>` · "
            "`status` · `limits` · `pause`",
        )
        return "\n".join(lines)


def _period_label(hours: float) -> str:
    if hours <= 25:
        return "last 24h"
    if hours <= 24 * 8:
        return "last 7d"
    return f"last {int(hours/24)}d"


def compose_digest(
    *,
    period_hours: float = 24.0 * 7,
    autopilot: Any = None,
    launch_learner: Any = None,
    revision_journal: Any = None,
    compute_budget: Any = None,
    insight_synthesizer: Any = None,
    mood_model: Any = None,
    bottleneck_detector: Any = None,
) -> LaunchDigest:
    """Gather signals from each brain module (all injectable) and
    emit a LaunchDigest."""
    now = time.time()
    period_start = now - period_hours * 3600.0
    # Default to brain_facade singletons when not injected
    if autopilot is None:
        try:
            from execution.launch.autopilot import Autopilot
            autopilot = Autopilot()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "autopilot unavailable: %s", exc,
            )
    if launch_learner is None:
        try:
            from agents.learning.launch_learner import (
                LaunchLearner,
            )
            launch_learner = LaunchLearner()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "launch_learner unavailable: %s", exc,
            )
    if revision_journal is None:
        try:
            from core.brain.brain_facade import (
                _revision_journal,
            )
            revision_journal = _revision_journal()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "revision_journal unavailable: %s", exc,
            )
    if compute_budget is None:
        try:
            from core.brain.brain_facade import (
                _compute_budget,
            )
            compute_budget = _compute_budget()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "compute_budget unavailable: %s", exc,
            )
    if insight_synthesizer is None:
        try:
            from core.brain.brain_facade import (
                _insight_synthesizer,
            )
            insight_synthesizer = _insight_synthesizer()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "insight_synthesizer unavailable: %s",
                exc,
            )
    if mood_model is None:
        try:
            from core.brain.brain_facade import (
                _mood_model,
            )
            mood_model = _mood_model()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "mood_model unavailable: %s", exc,
            )
    if bottleneck_detector is None:
        try:
            from core.brain.brain_facade import (
                _bottleneck_detector,
            )
            bottleneck_detector = (
                _bottleneck_detector()
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "bottleneck_detector unavailable: %s",
                exc,
            )

    # ── Launches ───────────────────────────────────────
    launches_total = 0
    launches_successful = 0
    launches_blocked = 0
    if autopilot is not None:
        try:
            recent = autopilot.recent(limit=500) or []
            for run in recent:
                ts = getattr(run, "started_ts", 0.0)
                if ts < period_start:
                    continue
                for l in getattr(run, "launches", []):
                    launches_total += 1
                    if (
                        getattr(
                            l, "activate_verdict", "",
                        ) == "blocked"
                        or getattr(
                            l, "publish_verdict", "",
                        ) == "error"
                    ):
                        launches_blocked += 1
                # successful_launches is a computed property
                launches_successful += getattr(
                    run, "successful_launches", 0,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "autopilot scan failed: %s", exc,
            )

    # ── Learning ───────────────────────────────────────
    distill_proposals = 0
    distill_accepted = 0
    if launch_learner is not None:
        try:
            for report in (
                launch_learner.recent(limit=50) or []
            ):
                ts = getattr(report, "ts", 0.0)
                if ts < period_start:
                    continue
                distill_proposals += len(
                    getattr(report, "proposals", ()),
                )
                distill_accepted += getattr(
                    report, "accepted", 0,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "launch_learner scan failed: %s", exc,
            )

    # ── Journal ────────────────────────────────────────
    journal_pending = 0
    journal_applied = 0
    if revision_journal is not None:
        try:
            pending = revision_journal.by_status(
                "proposed",
            ) or []
            applied = revision_journal.by_status(
                "applied",
            ) or []
            journal_pending = len(pending)
            journal_applied = sum(
                1 for r in applied
                if getattr(r, "resolved_ts", 0.0)
                >= period_start
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "revision_journal scan failed: %s",
                exc,
            )

    # ── Compute budget ─────────────────────────────────
    compute_spent = 0.0
    if compute_budget is not None:
        try:
            archive = compute_budget.archive(
                limit=1000,
            ) or []
            for cycle in archive:
                ended = getattr(cycle, "ended_ts", 0.0)
                if ended < period_start:
                    continue
                compute_spent += (
                    getattr(
                        cycle, "spent_by_kind", {},
                    ).get("usd", 0.0)
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "compute_budget scan failed: %s", exc,
            )

    # ── Mood ───────────────────────────────────────────
    mood_label = "unknown"
    if mood_model is not None:
        try:
            snap = mood_model.snapshot()
            mood_label = getattr(snap, "label", "unknown")
        except Exception as exc:  # noqa: BLE001
            logger.debug("mood snapshot failed: %s", exc)

    # ── Bottleneck ─────────────────────────────────────
    bottleneck = "(none)"
    if bottleneck_detector is not None:
        try:
            top = bottleneck_detector.top_bottleneck()
            if top is not None:
                bottleneck = (
                    f"{top.phase} "
                    f"(reason={top.reason})"
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "bottleneck scan failed: %s", exc,
            )

    # ── Insights ───────────────────────────────────────
    top_insights: list[dict[str, Any]] = []
    if insight_synthesizer is not None:
        try:
            for i in (
                insight_synthesizer.active(limit=5) or []
            ):
                top_insights.append({
                    "severity": getattr(
                        i, "severity", "info",
                    ),
                    "statement": getattr(
                        i, "statement", "",
                    ),
                    "kind": getattr(
                        i, "kind", "",
                    ),
                })
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "insights scan failed: %s", exc,
            )

    # ── Recommendations ────────────────────────────────
    recs: list[str] = []
    if launches_total == 0:
        recs.append(
            "No launches in this window. Check "
            "`shopai doctor` + winner_seeds.json.",
        )
    if (
        launches_total > 0
        and launches_blocked / launches_total > 0.3
    ):
        recs.append(
            f"High block rate "
            f"({launches_blocked}/{launches_total}). "
            "Review pending approvals: `shopai pending`."
        )
    if journal_pending > 0:
        recs.append(
            f"{journal_pending} pending rule proposals. "
            "Review with `shopai pending` + "
            "`shopai approve <id>`.",
        )
    if distill_proposals == 0 and launches_total >= 5:
        recs.append(
            "No distilled proposals despite "
            f"{launches_total} launches. Run "
            "`shopai distill`.",
        )
    if mood_label in ("stressed", "overwhelmed"):
        recs.append(
            f"Brain reports mood={mood_label}. "
            "Inspect `shopai doctor` + recent errors.",
        )
    if compute_spent > 0 and compute_spent > 5.0:
        recs.append(
            f"Compute spend ${compute_spent:.2f} high; "
            "cap via `compute_budget` registration.",
        )

    return LaunchDigest(
        period_label=_period_label(period_hours),
        generated_ts=now,
        launches_total=launches_total,
        launches_successful=launches_successful,
        launches_blocked=launches_blocked,
        distill_proposals=distill_proposals,
        distill_accepted=distill_accepted,
        journal_pending=journal_pending,
        journal_applied=journal_applied,
        compute_spent_usd=compute_spent,
        mood_label=mood_label,
        bottleneck_phase=bottleneck,
        top_insights=top_insights,
        recommendations=recs,
        period_start_ts=period_start,
        period_end_ts=now,
    )
