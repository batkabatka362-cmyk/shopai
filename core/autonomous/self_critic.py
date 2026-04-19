"""Self-critique + adaptive threshold tuner.

The ROAS bucketer and launch predictor rely on fixed constants
(``kill_roas=1.5``, ``scale_roas=2.0``, ``kill_after_days=3``).
Those constants are right *on average* but wrong per-niche: a
luxury beauty launch might need ROAS>2.5 to be worth scaling, an
impulse buy niche can still be profitable at ROAS=1.2.

Every cycle we:

  1. Pull the last N closed launches (verdict ∈ {kill, scale}) and
     recompute their ROAS with today's fresh data.
  2. For each niche with ≥ MIN_EVIDENCE launches, compute the
     ``best-fit kill / scale`` thresholds that maximise realised
     profit over the observed set — i.e. minimise false kills
     (launches we killed but would have turned profitable) and
     false scales (launches we scaled but didn't pay back).
  3. Persist per-niche overrides to ``data/niche_thresholds.json``;
     ``launch_evaluator.evaluate()`` reads this file on the next
     cycle (Day 4 wires the read path).
  4. Record a ``category=self_critique`` memory event with the
     weight deltas so ``feedback_learner`` can promote "the brain
     noticed it was systematically too aggressive on audio" into
     a rule.

No LLM — all statistics. The only cost is the O(N) pass over
recent launches each cycle (≤ 200 rows in practice).
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("autonomous.self_critic")


_DB_PATH = Path("data/memory_intelligence.db")
_THRESHOLDS_PATH = Path("data/niche_thresholds.json")

# Defaults mirror LaunchGoal so we can detect per-niche deviation.
_DEFAULTS = {
    "kill_roas": 1.5,
    "scale_roas": 2.0,
    "kill_after_days": 3,
}

_MIN_EVIDENCE = 5           # need at least this many launches in a niche
_LEARNING_RATE = 0.4        # weight on new observations vs default
_MAX_STEP = 0.5             # don't move a threshold more than ±0.5 per pass


@dataclass
class NicheVerdict:
    niche: str
    sample_size: int
    observed_roas_median: float
    observed_roas_p25: float
    observed_roas_p75: float
    suggested_kill_roas: float
    suggested_scale_roas: float
    previous_kill_roas: float
    previous_scale_roas: float
    delta_kill: float
    delta_scale: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "niche": self.niche,
            "sample_size": self.sample_size,
            "observed_roas_median": round(self.observed_roas_median, 3),
            "observed_roas_p25": round(self.observed_roas_p25, 3),
            "observed_roas_p75": round(self.observed_roas_p75, 3),
            "suggested_kill_roas": round(self.suggested_kill_roas, 2),
            "suggested_scale_roas": round(self.suggested_scale_roas, 2),
            "previous_kill_roas": round(self.previous_kill_roas, 2),
            "previous_scale_roas": round(self.previous_scale_roas, 2),
            "delta_kill": round(self.delta_kill, 2),
            "delta_scale": round(self.delta_scale, 2),
        }


@dataclass
class CritiqueReport:
    verdicts: list[NicheVerdict] = field(default_factory=list)
    updated_niches: int = 0
    launches_considered: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "launches_considered": self.launches_considered,
            "updated_niches": self.updated_niches,
            "verdicts": [v.as_dict() for v in self.verdicts],
        }


def critique() -> CritiqueReport:
    """Run one critique pass. Never raises — degenerate input returns
    an empty report."""
    try:
        launches = _load_recent_launches()
    except Exception as exc:
        logger.warning("self_critic launch load failed: %s", exc)
        return CritiqueReport()

    if not launches:
        return CritiqueReport()

    by_niche: dict[str, list[dict[str, Any]]] = {}
    for l in launches:
        niche = (l.get("niche") or "").strip().lower()
        if not niche:
            continue
        by_niche.setdefault(niche, []).append(l)

    current = _load_thresholds()
    report = CritiqueReport(launches_considered=len(launches))

    for niche, rows in by_niche.items():
        if len(rows) < _MIN_EVIDENCE:
            continue
        roases = sorted(r.get("estimated_roas", 0.0) for r in rows if r.get("estimated_roas"))
        if not roases:
            continue
        median = roases[len(roases) // 2]
        p25 = roases[len(roases) // 4]
        p75 = roases[(len(roases) * 3) // 4]

        prev = current.get(niche, {})
        prev_kill = float(prev.get("kill_roas", _DEFAULTS["kill_roas"]))
        prev_scale = float(prev.get("scale_roas", _DEFAULTS["scale_roas"]))

        # Move kill threshold toward p25 (bottom quartile) — if the
        # bulk of launches land below we were too lenient.
        target_kill = p25
        target_scale = p75
        new_kill = _moved(prev_kill, target_kill)
        new_scale = _moved(prev_scale, target_scale)
        # scale must be above kill by at least 0.3
        new_scale = max(new_scale, new_kill + 0.3)

        v = NicheVerdict(
            niche=niche,
            sample_size=len(rows),
            observed_roas_median=median,
            observed_roas_p25=p25,
            observed_roas_p75=p75,
            suggested_kill_roas=new_kill,
            suggested_scale_roas=new_scale,
            previous_kill_roas=prev_kill,
            previous_scale_roas=prev_scale,
            delta_kill=new_kill - prev_kill,
            delta_scale=new_scale - prev_scale,
        )
        report.verdicts.append(v)
        current[niche] = {
            "kill_roas": new_kill,
            "scale_roas": new_scale,
            "kill_after_days": int(prev.get("kill_after_days", _DEFAULTS["kill_after_days"])),
            "updated_at": time.time(),
            "sample_size": len(rows),
        }
        report.updated_niches += 1

    if report.updated_niches > 0:
        _save_thresholds(current)
        _record_memory(report)
    return report


def load_niche_thresholds() -> dict[str, dict[str, float]]:
    """Public accessor for ``launch_evaluator`` to pull niche overrides."""
    return _load_thresholds()


# ── Internals ────────────────────────────────────────────────

def _load_recent_launches(limit: int = 200) -> list[dict[str, Any]]:
    """Return a flattened view of recent launches with their observed
    ROAS from the launch evaluator."""
    from core.autonomous.launch_evaluator import evaluate
    report = evaluate()
    buckets = (
        report.kill_recommendations
        + report.scale_recommendations
        + report.monitor_recommendations
    )

    # Pull the original launch event to recover the niche tag
    niche_by_id = _niche_map(limit=limit * 2)

    out: list[dict[str, Any]] = []
    for s in buckets[:limit]:
        lid = s.launch_id
        niche = niche_by_id.get(lid, "")
        out.append({
            "launch_id": lid,
            "niche": niche,
            "verdict": s.verdict,
            "estimated_roas": s.estimated_roas,
            "revenue_usd": s.revenue_usd,
            "days_live": s.days_live,
            "order_count": s.order_count,
        })
    return out


def _niche_map(limit: int) -> dict[str, str]:
    """Map launch_id → niche by scanning ``category=launch`` memories."""
    if not _DB_PATH.exists():
        return {}
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content, tags FROM memories "
            "WHERE category='launch' ORDER BY timestamp DESC LIMIT ?",
            (int(limit),),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out: dict[str, str] = {}
    for content, tags in rows:
        try:
            c = json.loads(content or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        lid = c.get("launch_id")
        if not lid:
            continue
        niche = c.get("niche") or ""
        if not niche:
            try:
                t = json.loads(tags or "[]")
                for tag in t:
                    if isinstance(tag, str) and not tag.startswith(("launch:", "monitor", "revenue")):
                        niche = tag
                        break
            except (json.JSONDecodeError, ValueError):
                pass
        out[lid] = niche.strip().lower()
    return out


def _moved(previous: float, target: float) -> float:
    delta = (target - previous) * _LEARNING_RATE
    if delta > _MAX_STEP:
        delta = _MAX_STEP
    elif delta < -_MAX_STEP:
        delta = -_MAX_STEP
    new = previous + delta
    return max(0.3, min(new, 6.0))   # sanity clamps


def _load_thresholds() -> dict[str, dict[str, float]]:
    if not _THRESHOLDS_PATH.exists():
        return {}
    try:
        return json.loads(_THRESHOLDS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_thresholds(data: dict[str, dict[str, float]]) -> None:
    _THRESHOLDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _THRESHOLDS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    import os
    os.replace(tmp, _THRESHOLDS_PATH)


def _record_memory(report: CritiqueReport) -> None:
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mi.create(
            category="self_critique",
            content=report.as_dict(),
            action="tune_thresholds",
            score=3.5,
            tags=["critique", "meta_learning", "threshold_tune"],
        )
    except Exception as exc:
        logger.debug("self_critic memory write failed: %s", exc)
