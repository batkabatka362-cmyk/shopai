"""Weekly digest — compress 7 days of cycles into one owner story.

narrative_generator (v26-D5) summarises ONE cycle. By Sunday night
the owner has 168 cycle reports; nobody reads 168 things. The
weekly digest pulls a configurable window (default 7 days) of
experience-recorder events and produces:

  • headline                   — totals + biggest move
  • by_day                     — small per-day rollup (decisions,
                                   outcomes, errors, llm cost)
  • top_decisions              — five most consequential by credit
  • top_movers                 — five biggest KPI swings
  • repeated_failures          — phase failure streaks
  • llm_total_cost_usd         — operator visibility on spend
  • new_skills_distilled       — skill_distiller candidates promoted
  • narrative                  — markdown body, deterministic

Pure function over inputs. The caller (daemon housekeep, CLI) owns
delivery — Obsidian write, email, etc. Default lookup is via
experience_recorder.recent; tests inject their own.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.weekly_digest")


@dataclass
class DayRollup:
    day_iso: str
    decisions: int
    outcomes: int
    phase_errors: int
    llm_cost_usd: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "day_iso": self.day_iso,
            "decisions": self.decisions,
            "outcomes": self.outcomes,
            "phase_errors": self.phase_errors,
            "llm_cost_usd": round(self.llm_cost_usd, 4),
        }


@dataclass
class WeeklyDigest:
    period_days: int
    headline: str
    body: str
    by_day: list[DayRollup] = field(default_factory=list)
    top_decisions: list[dict[str, Any]] = field(default_factory=list)
    top_movers: list[dict[str, Any]] = field(default_factory=list)
    repeated_failures: list[dict[str, Any]] = field(default_factory=list)
    llm_total_cost_usd: float = 0.0
    new_skills_distilled: list[dict[str, Any]] = field(default_factory=list)
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "period_days": self.period_days,
            "headline": self.headline,
            "body": self.body,
            "by_day": [d.as_dict() for d in self.by_day],
            "top_decisions": list(self.top_decisions),
            "top_movers": list(self.top_movers),
            "repeated_failures": list(self.repeated_failures),
            "llm_total_cost_usd": round(self.llm_total_cost_usd, 4),
            "new_skills_distilled": list(self.new_skills_distilled),
            "ts": self.ts,
        }


def _payload(event: Any) -> dict[str, Any]:
    p = getattr(event, "payload", None)
    if p is None and isinstance(event, dict):
        p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _kind(event: Any) -> str:
    return str(
        getattr(event, "kind", None)
        or (event.get("kind") if isinstance(event, dict) else "")
    )


def _ts(event: Any) -> float:
    return float(
        getattr(event, "ts", None)
        or (event.get("ts") if isinstance(event, dict) else 0.0)
        or 0.0
    )


def _day_key(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


# ── Compose ───────────────────────────────────────────────

def compose(
    events: Iterable[Any],
    *,
    period_days: int = 7,
    distilled_skills: Iterable[dict[str, Any]] = (),
    failure_threshold: int = 3,
) -> WeeklyDigest:
    if period_days < 1:
        raise ValueError("period_days must be ≥ 1")
    rows = list(events)
    now = time.time()
    cutoff = now - period_days * 86_400.0
    rows = [e for e in rows if _ts(e) >= cutoff]

    # ── Per-day rollup ────────────────────────────────────
    days: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "decisions": 0, "outcomes": 0,
            "phase_errors": 0, "llm_cost_usd": 0.0,
        },
    )
    decisions: list[Any] = []
    outcomes: list[Any] = []
    failures_by_name: dict[str, int] = defaultdict(int)
    total_llm_cost = 0.0

    for ev in rows:
        k = _kind(ev)
        d = _day_key(_ts(ev))
        if k == "decision":
            days[d]["decisions"] += 1
            decisions.append(ev)
        elif k == "outcome":
            days[d]["outcomes"] += 1
            outcomes.append(ev)
        elif k == "phase":
            payload = _payload(ev)
            status = str(payload.get("status", "")).lower()
            if status not in ("ok", ""):
                days[d]["phase_errors"] += 1
                name = str(payload.get("name", "?"))
                failures_by_name[name] += 1
        elif k == "llm_call":
            cost = float(_payload(ev).get("cost_usd", 0.0) or 0.0)
            days[d]["llm_cost_usd"] += cost
            total_llm_cost += cost

    by_day_sorted = sorted(days.keys())
    by_day = [
        DayRollup(
            day_iso=day,
            decisions=int(days[day]["decisions"]),
            outcomes=int(days[day]["outcomes"]),
            phase_errors=int(days[day]["phase_errors"]),
            llm_cost_usd=float(days[day]["llm_cost_usd"]),
        )
        for day in by_day_sorted
    ]

    # ── Top decisions (by chosen confidence × support) ───
    scored: list[tuple[float, dict[str, Any]]] = []
    for d_ev in decisions:
        payload = _payload(d_ev)
        chosen = payload.get("chosen") or {}
        action = chosen.get("action") or chosen.get("kind") or "?"
        conf = float(chosen.get("confidence", 0.5) or 0.5)
        scored.append((
            conf,
            {
                "action": action,
                "context": payload.get("context") or {},
                "confidence": round(conf, 4),
            },
        ))
    scored.sort(key=lambda kv: -kv[0])
    top_decisions = [d for _, d in scored[:5]]

    # ── Top movers (KPI delta vs baseline mean) ──────────
    by_kpi: dict[str, list[float]] = defaultdict(list)
    for o_ev in outcomes:
        payload = _payload(o_ev)
        kpi = str(payload.get("kpi", ""))
        if not kpi:
            continue
        try:
            by_kpi[kpi].append(float(payload.get("value", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
    movers: list[dict[str, Any]] = []
    for kpi, vals in by_kpi.items():
        if len(vals) < 2:
            continue
        mean = sum(vals) / len(vals)
        latest = vals[-1]
        movers.append({
            "kpi": kpi,
            "mean": round(mean, 4),
            "latest": round(latest, 4),
            "delta": round(latest - mean, 4),
        })
    movers.sort(key=lambda m: -abs(m["delta"]))
    top_movers = movers[:5]

    # ── Repeated failures ───────────────────────────────
    repeated = [
        {"phase": name, "count": count}
        for name, count in failures_by_name.items()
        if count >= failure_threshold
    ]
    repeated.sort(key=lambda r: -r["count"])

    # ── Headline + body ─────────────────────────────────
    headline = (
        f"Weekly digest ({period_days}d): "
        f"{len(decisions)} decisions, "
        f"{len(outcomes)} outcomes, "
        f"${total_llm_cost:.2f} LLM spend"
    )
    if repeated:
        headline += f", {len(repeated)} repeating failure(s)"

    body_lines: list[str] = [f"# {headline}", ""]
    if by_day:
        body_lines.append("## Daily rollup")
        for d in by_day:
            body_lines.append(
                f"- **{d.day_iso}**: {d.decisions} decisions, "
                f"{d.outcomes} outcomes, "
                f"{d.phase_errors} phase errors, "
                f"${d.llm_cost_usd:.4f} LLM"
            )
    if top_movers:
        body_lines.append("\n## Biggest KPI moves")
        for m in top_movers:
            arrow = "↑" if m["delta"] > 0 else "↓"
            body_lines.append(
                f"- {m['kpi']}: latest {m['latest']:.4f} vs "
                f"mean {m['mean']:.4f} {arrow}"
            )
    if top_decisions:
        body_lines.append("\n## Most-confident decisions")
        for d in top_decisions:
            body_lines.append(
                f"- {d['action']} (conf {d['confidence']:.2f})"
            )
    if repeated:
        body_lines.append("\n## Repeated failures")
        for r in repeated:
            body_lines.append(f"- {r['phase']}: {r['count']}x")
    distilled_list = list(distilled_skills)
    if distilled_list:
        body_lines.append("\n## New skills distilled this week")
        for s in distilled_list[:10]:
            body_lines.append(
                f"- {s.get('name', '?')} "
                f"(support={s.get('support', '?')}, "
                f"score={s.get('mean_score', '?')})"
            )

    return WeeklyDigest(
        period_days=period_days,
        headline=headline,
        body="\n".join(body_lines).strip(),
        by_day=by_day,
        top_decisions=top_decisions,
        top_movers=top_movers,
        repeated_failures=repeated,
        llm_total_cost_usd=total_llm_cost,
        new_skills_distilled=distilled_list[:10],
        ts=now,
    )


def generate_digest(
    *,
    period_days: int = 7,
    recent_fn: Callable[..., list[Any]] | None = None,
    distill_fn: Callable[..., list[dict[str, Any]]] | None = None,
) -> WeeklyDigest:
    """Pull events from experience_recorder.recent and compose a
    digest. ``recent_fn`` and ``distill_fn`` accept injection for
    tests; default to the real singletons."""
    events: list[Any] = []
    if recent_fn is not None:
        try:
            events = list(recent_fn(limit=2000))
        except Exception as exc:
            logger.debug("injected recent_fn failed: %s", exc)
            events = []
    else:
        try:
            from core.brain.experience_recorder import recent
            events = list(recent(limit=2000))
        except Exception as exc:
            logger.debug("experience_recorder unavailable: %s", exc)
            events = []
    distilled: list[dict[str, Any]] = []
    if distill_fn is not None:
        try:
            distilled = list(distill_fn())
        except Exception as exc:
            logger.debug("distill_fn failed: %s", exc)
    return compose(
        events,
        period_days=period_days,
        distilled_skills=distilled,
    )
