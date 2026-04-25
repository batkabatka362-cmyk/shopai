"""Daily opportunity scout.

Everything built so far is *reactive* — the brain responds to an
event (new memory, order webhook, reasoning question). The scout
runs once per calendar day and surfaces *proactive* opportunities
the owner would otherwise miss:

  • SCALE CANDIDATES — launches whose ROAS exceeds their niche
    baseline + 1σ but haven't been scaled yet.
  • KILL CANDIDATES — launches >= kill_after_days old with
    estimated_roas < niche_kill_threshold.
  • UNDERUTILISED RULES — memory rules with high score but zero
    uses in the last 7 days.
  • COMPETITOR OPENINGS — competitors whose price dropped >15%
    (we could undercut) or raised >20% (we can raise too).
  • TRANSFER WINS — niches with no local launches yet but matching
    cross-niche transfer strategies.

Output is a ``DigestReport`` that CLI / API / dashboard render, and
which is also persisted as a ``category=digest`` memory event so
the brain can learn which of its own suggestions the owner
actually pursued.

Deterministic, LLM-free; an optional ``narrative`` field is filled
when the router is configured so the digest reads like a human brief.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("autonomous.opportunity_scout")

_DB_PATH = Path("data/memory_intelligence.db")
_SECONDS_PER_DAY = 86_400


@dataclass
class Opportunity:
    kind: str                    # scale | kill | underutilised_rule | competitor | transfer
    target_id: str
    headline: str
    detail: str = ""
    score: float = 0.0
    tags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target_id": self.target_id,
            "headline": self.headline,
            "detail": self.detail,
            "score": round(self.score, 3),
            "tags": self.tags,
        }


@dataclass
class DigestReport:
    date: str
    opportunities: list[Opportunity] = field(default_factory=list)
    narrative: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "count": len(self.opportunities),
            "by_kind": self._counts_by_kind(),
            "opportunities": [o.as_dict() for o in self.opportunities],
            "narrative": self.narrative,
        }

    def _counts_by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for o in self.opportunities:
            out[o.kind] = out.get(o.kind, 0) + 1
        return out


def scout(include_narrative: bool = False) -> DigestReport:
    """Run one full scout pass."""
    report = DigestReport(date=dt.date.today().isoformat())

    _find_scale_candidates(report)
    _find_kill_candidates(report)
    _find_underutilised_rules(report)
    _find_competitor_openings(report)
    _find_transfer_wins(report)

    # Rank descending by score and cap
    report.opportunities.sort(key=lambda o: -o.score)
    report.opportunities = report.opportunities[:20]

    if include_narrative and report.opportunities:
        report.narrative = _narrative_for(report)

    _persist(report)
    return report


# ── Individual scouts ───────────────────────────────────────

def _find_scale_candidates(report: DigestReport) -> None:
    """Launches with ROAS above niche baseline + 1σ, not yet scaled."""
    try:
        from core.autonomous.launch_evaluator import evaluate
        from core.autonomous.self_critic import _niche_map
    except Exception:
        return
    eval_report = evaluate()
    niches = _niche_map(limit=500)

    # Group launches by niche, compute mean + stddev
    per_niche: dict[str, list[float]] = {}
    for s in (eval_report.monitor_recommendations
              + eval_report.kill_recommendations
              + eval_report.scale_recommendations):
        niche = niches.get(s.launch_id, "")
        if niche and s.estimated_roas > 0:
            per_niche.setdefault(niche, []).append(s.estimated_roas)

    baselines: dict[str, tuple[float, float]] = {}
    for niche, values in per_niche.items():
        if len(values) < 3:
            continue
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / len(values)
        stddev = math.sqrt(var) if var > 0 else 0.0
        baselines[niche] = (mean, stddev)

    for s in eval_report.monitor_recommendations:
        if s.verdict != "hold":
            continue
        niche = niches.get(s.launch_id, "")
        base = baselines.get(niche)
        if not base or base[1] == 0:
            continue
        mean, stddev = base
        if s.estimated_roas < mean + stddev:
            continue
        # +1σ above niche mean → candidate
        report.opportunities.append(Opportunity(
            kind="scale",
            target_id=s.launch_id,
            headline=f"{s.launch_id[:24]} — ROAS {s.estimated_roas:.2f} "
                     f"beats {niche} baseline {mean:.2f}",
            detail=(
                f"Running for {s.days_live:.1f} days at "
                f"ROAS {s.estimated_roas:.2f} vs niche mean {mean:.2f} "
                f"(±{stddev:.2f}). Consider doubling daily budget."
            ),
            score=float(s.estimated_roas - mean),
            tags=["scale", niche, f"launch:{s.launch_id}"],
        ))


def _find_kill_candidates(report: DigestReport) -> None:
    """Launches already past kill horizon + under threshold — but not
    yet acted on (no recent ``kill_launch`` action tagged to them)."""
    try:
        from core.autonomous.launch_evaluator import evaluate
    except Exception:
        return
    eval_report = evaluate()
    for s in eval_report.kill_recommendations:
        report.opportunities.append(Opportunity(
            kind="kill",
            target_id=s.launch_id,
            headline=(
                f"{s.launch_id[:24]} — ROAS {s.estimated_roas:.2f} "
                f"< kill threshold"
            ),
            detail=s.reason,
            score=float(max(0.1, 2.0 - s.estimated_roas)),
            tags=["kill", f"launch:{s.launch_id}"],
        ))


def _find_underutilised_rules(report: DigestReport) -> None:
    """High-score rules with no uses in the last 7 days — either we
    forgot about them or the feedback loop is broken."""
    if not _DB_PATH.exists():
        return
    cutoff = time.time() - 7 * _SECONDS_PER_DAY
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, category, action, score "
            "FROM memories WHERE level >= 2 AND score >= 3.5 "
            "  AND (last_used = 0 OR last_used < ?) "
            "ORDER BY score DESC LIMIT 5",
            (cutoff,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    for mid, cat, act, score in rows:
        report.opportunities.append(Opportunity(
            kind="underutilised_rule",
            target_id=f"rule_{mid}",
            headline=f"Rule [{cat}/{act}] (#{mid}) score {score:.2f} "
                     f"idle > 7 days",
            detail="Apply it next cycle or retire if no longer relevant.",
            score=float(score) - 1.5,
            tags=["underutilised", cat, f"memory:{mid}"],
        ))


def _find_competitor_openings(report: DigestReport) -> None:
    """Large competitor price moves in the last 24h."""
    if not _DB_PATH.exists():
        return
    cutoff = time.time() - _SECONDS_PER_DAY
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, content, timestamp FROM memories "
            "WHERE category='competitor' AND timestamp > ? "
            "ORDER BY timestamp DESC LIMIT 10",
            (cutoff,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    for mid, content_json, ts in rows:
        try:
            c = json.loads(content_json or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        delta = float(c.get("delta_pct", 0) or 0)
        if abs(delta) < 15:
            continue
        direction = "dropped" if delta < 0 else "raised"
        report.opportunities.append(Opportunity(
            kind="competitor",
            target_id=f"competitor_{mid}",
            headline=f"Competitor {direction} price {delta:+.1f}%",
            detail=(
                f"{c.get('title', '(no title)')[:80]} now "
                f"${c.get('new_price')} (was ${c.get('old_price')})"
            ),
            score=abs(delta) / 10.0,
            tags=["competitor", direction, f"memory:{mid}"],
        ))


def _find_transfer_wins(report: DigestReport) -> None:
    """Transfer strategies we haven't exercised in any local niche yet."""
    try:
        from core.brain.transfer_learner import retrieve_for_niche
    except Exception:
        return
    strategies = retrieve_for_niche(niche="", k=5)
    for strat in strategies:
        feat = strat.get("feature") or {}
        niches = strat.get("niches") or []
        if not niches:
            continue
        universality = strat.get("universality") or 0.0
        if universality < 0.5:
            continue
        report.opportunities.append(Opportunity(
            kind="transfer",
            target_id=f"strategy_{strat.get('id')}",
            headline=(
                f"Universal pattern: {feat.get('copy_tone')} tone + "
                f"{feat.get('price_band')} price won in "
                f"{len(niches)} niches"
            ),
            detail=(
                f"Universality {universality:.0%}. Niches: "
                f"{', '.join(niches[:4])}. Try in a new niche."
            ),
            score=universality * len(niches) / 5.0,
            tags=["transfer"] + list(niches),
        ))


def _narrative_for(report: DigestReport) -> str:
    """Compact narrative via the router. Empty string on failure."""
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
        from core.adapters.router import RouteContext
    except Exception:
        return ""
    bullets = [
        f"- [{o.kind}] {o.headline}"
        for o in report.opportunities[:10]
    ]
    prompt = (
        "You are writing the daily morning digest for an e-commerce "
        "operator. Turn these opportunities into a 100-word briefing. "
        "Order by urgency (kills first, then high-score scales, then "
        "the rest). Be concrete, no filler:\n\n"
        + "\n".join(bullets)
    )
    try:
        result = get_router().execute(
            capability=Capability.CHAT_COMPLETE,
            params={
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400,
                "temperature": 0.3,
            },
            context=RouteContext(prefer=["groq", "gemini"]),
        )
    except Exception:
        return ""
    if not getattr(result, "ok", False):
        return ""
    return (getattr(result, "data", {}) or {}).get("text", "").strip()


def _persist(report: DigestReport) -> None:
    if not report.opportunities:
        return
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mi.create(
            category="digest",
            content=report.as_dict(),
            action="daily_digest",
            score=3.0,
            tags=["digest", "opportunity_scout", report.date],
        )
    except Exception as exc:
        logger.debug("opportunity digest persist failed: %s", exc)
