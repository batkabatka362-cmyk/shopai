"""Narrative generator — render a cycle's experience as owner-readable prose.

The experience recorder captures every phase, decision, LLM call,
outcome, and assessment. Dashboards show counts; owners want a story.
narrative_generator composes a short cycle report from those events:

  1. One-line headline (health + total actions + biggest event)
  2. "What happened" — bullets for decisions + outcomes
  3. "What broke" — phase errors + invariant breaches
  4. "What changed" — KPI moves vs the previous cycle

Output is deterministic plain-text markdown, safe to mirror to
Obsidian. Zero LLM. Pure function over the experience ledger.

Key API:

    story = generate_narrative(cycle_id="c_42", lookback=5)
    # → Narrative(headline, body, kpi_moves, warnings)

The narrative is *deterministic* — same inputs always produce the same
prose — because it's just a template filled from counted events.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.narrative_generator")


@dataclass
class KpiMove:
    kpi: str
    previous: float
    current: float
    delta: float

    @property
    def percent_change(self) -> float:
        if self.previous == 0:
            return 0.0
        return (self.current - self.previous) / abs(self.previous) * 100.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kpi": self.kpi,
            "previous": round(self.previous, 4),
            "current": round(self.current, 4),
            "delta": round(self.delta, 4),
            "percent_change": round(self.percent_change, 2),
        }


@dataclass
class Narrative:
    cycle_id: str
    headline: str
    body: str
    kpi_moves: list[KpiMove] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    health_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "headline": self.headline,
            "body": self.body,
            "kpi_moves": [m.as_dict() for m in self.kpi_moves],
            "warnings": list(self.warnings),
            "health_score": self.health_score,
        }


# ── Pure helpers (no side effects) ────────────────────────

def _group_by_kind(events: list[Any]) -> dict[str, list[Any]]:
    """Bucket a list of Experience-like objects by their kind
    attribute (dicts or dataclasses with .kind + .payload)."""
    groups: dict[str, list[Any]] = {}
    for e in events:
        kind = getattr(e, "kind", None) or (
            e.get("kind") if isinstance(e, dict) else ""
        )
        kind = str(kind or "")
        if not kind:
            continue
        groups.setdefault(kind, []).append(e)
    return groups


def _payload(event: Any) -> dict[str, Any]:
    p = getattr(event, "payload", None)
    if p is None and isinstance(event, dict):
        p = event.get("payload")
    if isinstance(p, dict):
        return p
    return {}


def _compute_kpi_moves(
    outcomes_now: list[Any],
    outcomes_prev: list[Any],
) -> list[KpiMove]:
    def _bucket(evs: list[Any]) -> dict[str, list[float]]:
        by: dict[str, list[float]] = {}
        for ev in evs:
            p = _payload(ev)
            kpi = str(p.get("kpi", ""))
            if not kpi:
                continue
            raw = p.get("value")
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            by.setdefault(kpi, []).append(value)
        return by

    now = _bucket(outcomes_now)
    prev = _bucket(outcomes_prev)
    moves: list[KpiMove] = []
    for kpi, values in now.items():
        cur = sum(values) / len(values) if values else 0.0
        prev_values = prev.get(kpi, [])
        pre = (
            sum(prev_values) / len(prev_values)
            if prev_values else cur
        )
        moves.append(KpiMove(
            kpi=kpi, previous=pre, current=cur, delta=cur - pre,
        ))
    moves.sort(key=lambda m: -abs(m.delta))
    return moves


# ── Compose ───────────────────────────────────────────────

def compose(
    cycle_id: str,
    current: list[Any],
    previous: list[Any] | None = None,
) -> Narrative:
    """Pure composition from event lists — does not touch any DB."""
    previous = previous or []
    groups_now = _group_by_kind(current)
    groups_prev = _group_by_kind(previous)

    phases = groups_now.get("phase", [])
    decisions = groups_now.get("decision", [])
    outcomes = groups_now.get("outcome", [])
    assessments = groups_now.get("assessment", [])
    llm = groups_now.get("llm_call", [])

    # Health: pick the most recent assessment's health_score if any
    health: float | None = None
    for a in assessments:
        p = _payload(a)
        hs = p.get("health_score")
        if hs is not None:
            try:
                health = float(hs)
            except (TypeError, ValueError):
                continue
            break

    warnings: list[str] = []
    phase_failures = [
        p for p in phases
        if str(_payload(p).get("status", "")).lower() not in ("ok", "")
    ]
    for p in phase_failures:
        pp = _payload(p)
        warnings.append(
            f"phase {pp.get('name','?')} status={pp.get('status','?')}",
        )

    moves = _compute_kpi_moves(outcomes, groups_prev.get("outcome", []))

    # Headline
    action_count = len(decisions)
    headline = (
        f"Cycle {cycle_id[:8]}: "
        f"{action_count} decision(s), {len(outcomes)} outcome(s)"
    )
    if health is not None:
        headline += f", health={health:.0f}"
    if warnings:
        headline += f", {len(warnings)} phase warning(s)"

    # Body
    body_lines: list[str] = []
    if decisions:
        body_lines.append("## What happened")
        for d in decisions[:10]:
            pp = _payload(d)
            chosen = pp.get("chosen") or {}
            kind = chosen.get("action") or chosen.get("kind") or "?"
            ctx = pp.get("context") or {}
            niche = ctx.get("niche") or ""
            body_lines.append(
                f"- decided **{kind}**"
                + (f" (niche={niche})" if niche else "")
            )
    if moves:
        body_lines.append("\n## KPI moves")
        for m in moves[:5]:
            arrow = "↑" if m.delta > 0 else ("↓" if m.delta < 0 else "→")
            body_lines.append(
                f"- {m.kpi}: {m.previous:.3f} → {m.current:.3f} "
                f"{arrow} ({m.percent_change:+.1f}%)"
            )
    if warnings:
        body_lines.append("\n## What broke")
        for w in warnings[:10]:
            body_lines.append(f"- {w}")
    if llm:
        total_cost = sum(
            float(_payload(e).get("cost_usd", 0) or 0) for e in llm
        )
        body_lines.append(
            f"\n## LLM: {len(llm)} call(s), ${total_cost:.4f} spent",
        )

    body = "\n".join(body_lines).strip()
    return Narrative(
        cycle_id=cycle_id,
        headline=headline,
        body=body,
        kpi_moves=moves,
        warnings=warnings,
        health_score=health,
    )


def generate_narrative(
    cycle_id: str,
    *,
    lookback: int = 1,
) -> Narrative:
    """Look up current + previous events from the experience recorder
    and compose. ``lookback=N`` means the narrative compares against
    the union of the last N prior cycles."""
    try:
        from core.brain.experience_recorder import recent
    except ImportError:
        logger.debug("experience_recorder unavailable")
        return Narrative(cycle_id=cycle_id, headline="", body="")
    try:
        current = recent(cycle_id=cycle_id, limit=200)
        others = recent(limit=500)
    except Exception as exc:
        logger.debug("experience recent() failed: %s", exc)
        return Narrative(cycle_id=cycle_id, headline="", body="")
    # Previous cycles: collect recent events with different cycle_ids.
    seen_cycles: list[str] = []
    previous_events: list[Any] = []
    for ev in others:
        cid = getattr(ev, "cycle_id", None) or (
            ev.get("cycle_id") if isinstance(ev, dict) else ""
        )
        if not cid or cid == cycle_id:
            continue
        if cid not in seen_cycles:
            seen_cycles.append(cid)
            if len(seen_cycles) > lookback:
                break
        previous_events.append(ev)
    return compose(cycle_id, current, previous_events)
