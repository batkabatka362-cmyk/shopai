"""Goal compiler — natural-language goal → structured plan.

Owner says: *"Энэ Alibaba URL-д байгаа бүтээгдэхүүнг avtods-аар sync
хийж, Shopify-д тавьж, видео хийж, Meta ads-д $20/өдөр launch хийж,
3 өдрийн дараа ROAS<1.5 байвал auto-kill"*. The brain shouldn't have
to ask; it should *compile* that into:

    goals = [Goal("ingest", deadline=15min),
             Goal("publish", deadline=30min, parent=...),
             Goal("ads_launch", deadline=1h, ...),
             Goal("monitor", deadline=3d)]
    kpis  = [KpiSpec("roas", min=1.5, window_days=3, on_breach="kill")]
    budget = {"ads_daily_usd": 20.0}

This module does that *deterministically*, without an LLM, by:

  1. Tokenising the input.
  2. Running a pipeline of regex extractors for every recognised slot
     (URL, currency, percentages, durations, kill conditions, …).
  3. Mapping recognised verbs ("sync", "launch", "kill", "monitor")
     onto a fixed library of Goal templates.
  4. Returning a ``CompiledGoal`` with ordered subgoals, KPI specs,
     budget hints, and an audit trail of which tokens contributed
     to which slot — so callers can show the owner what we heard.

Pure stdlib, deterministic, English + Mongolian-transliteration aware
through a small synonym table. Falls back to a single
``investigate`` subgoal when nothing matches.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.goal_compiler")


KillCondition = Literal["roas_below", "cpa_above", "refund_rate_above", "none"]


@dataclass
class KpiSpec:
    name: str
    direction: Literal["min", "max"]
    threshold: float
    window_days: float
    on_breach: Literal["kill", "alert", "scale"] = "alert"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "direction": self.direction,
            "threshold": self.threshold,
            "window_days": self.window_days,
            "on_breach": self.on_breach,
        }


@dataclass
class SubGoal:
    name: str
    description: str
    deadline_s: float | None = None
    depends_on: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "deadline_s": self.deadline_s,
            "depends_on": list(self.depends_on),
        }


@dataclass
class CompiledGoal:
    raw: str
    subgoals: list[SubGoal] = field(default_factory=list)
    kpis: list[KpiSpec] = field(default_factory=list)
    budget: dict[str, float] = field(default_factory=dict)
    references: dict[str, Any] = field(default_factory=dict)
    trail: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "subgoals": [s.as_dict() for s in self.subgoals],
            "kpis": [k.as_dict() for k in self.kpis],
            "budget": dict(self.budget),
            "references": dict(self.references),
            "trail": list(self.trail),
        }


# ── Synonym tables (English + Mongolian transliteration) ──

_SYNONYMS: dict[str, list[str]] = {
    "sync":     ["sync", "import", "ingest"],
    "publish":  ["publish", "post", "tav"],         # tav* covers Mongolian "tavih"
    "launch":   ["launch", "start"],
    "kill":     ["kill", "auto-kill", "auto_kill", "stop"],
    "monitor":  ["monitor", "watch", "track"],
    "video":    ["video", "vide"],
    "scale":    ["scale", "increase", "grow"],
    "refund":   ["refund", "buts"],
}


_VERB_TO_SUBGOAL: dict[str, tuple[str, str, float | None]] = {
    "sync":    ("ingest",      "Sync the source product into our catalog",      900.0),    # 15 min
    "publish": ("publish",     "Publish the product to Shopify",                1800.0),   # 30 min
    "video":   ("create_video","Generate / source a product video asset",       3600.0),   # 1 h
    "launch":  ("ads_launch",  "Launch the ad campaigns",                       3600.0),   # 1 h
    "scale":   ("scale_ads",   "Scale up ads spend on the winning product",     3600.0),
    "monitor": ("monitor",     "Track key metrics over the watch window",       None),
    "kill":    ("kill_check",  "Evaluate kill conditions and pause if breached",None),
    "refund":  ("refund_check","Process / monitor refund queue",                None),
}


# ── Extractors ────────────────────────────────────────────

_URL_RE = re.compile(r"https?://[^\s\)]+", re.IGNORECASE)
_BUDGET_RE = re.compile(
    r"\$\s*(\d+(?:\.\d+)?)\s*(?:/?\s*(?:day|day|day|udur|өдөр))?",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(min|minute|minutes|hour|hours|hr|day|days|d|week|weeks|w|odur|өдөр)",
    re.IGNORECASE,
)
_ROAS_RE = re.compile(
    r"roas\s*([<>]=?)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_CPA_RE = re.compile(
    r"cpa\s*([<>]=?)\s*\$?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _normalise_word(word: str) -> str | None:
    word = word.lower().strip(".,;:")
    for canonical, syns in _SYNONYMS.items():
        if word == canonical or word in syns:
            return canonical
        for syn in syns:
            if syn.endswith("*"):
                if word.startswith(syn[:-1]):
                    return canonical
            elif syn.endswith(("ih", "ah", "eh", "oh")):
                # Mongolian verb stem: 'tav' matches 'tavih', 'tavi', 'tavi-d'
                if word.startswith(syn):
                    return canonical
    # 'tav' substring rule for Mongolian "tavih" family
    for canonical, syns in _SYNONYMS.items():
        for syn in syns:
            if len(syn) >= 3 and word.startswith(syn):
                return canonical
    return None


def _seconds_for(amount: float, unit: str) -> float:
    unit = unit.lower()
    if unit.startswith("min"):
        return amount * 60.0
    if unit.startswith(("hour", "hr")):
        return amount * 3600.0
    if unit.startswith(("day", "d", "odur", "өдөр")):
        return amount * 86_400.0
    if unit.startswith(("week", "w")):
        return amount * 7 * 86_400.0
    return amount


# ── Compile ───────────────────────────────────────────────

def compile_goal(text: str) -> CompiledGoal:
    """Parse a natural-language goal into a structured plan."""
    raw = (text or "").strip()
    out = CompiledGoal(raw=raw)
    if not raw:
        return out

    trail: list[dict[str, Any]] = []

    # 1. Extract references (URLs)
    urls = _URL_RE.findall(raw)
    if urls:
        out.references["urls"] = urls
        trail.append({"slot": "urls", "matched": urls})

    # 2. Extract budgets — first $N → daily ads cap by default.
    budget_matches = _BUDGET_RE.findall(raw)
    if budget_matches:
        try:
            usd = float(budget_matches[0])
            out.budget["ads_daily_usd"] = usd
            trail.append({"slot": "ads_daily_usd", "matched": usd})
        except ValueError as exc:
            logger.debug("budget parse skipped: %s", exc)

    # 3. Find a "kill window" duration that follows the kill phrase.
    #    e.g. "3 days later if ROAS < 1.5 → kill". The first duration
    #    becomes the monitor window.
    duration_matches = _DURATION_RE.findall(raw)
    monitor_window_s: float | None = None
    if duration_matches:
        amount, unit = duration_matches[0]
        try:
            monitor_window_s = _seconds_for(float(amount), unit)
            trail.append({
                "slot": "monitor_window_s",
                "matched": monitor_window_s,
            })
        except ValueError as exc:
            logger.debug("duration parse skipped: %s", exc)

    # 4. KPI conditions — ROAS / CPA
    for op, value in _ROAS_RE.findall(raw):
        try:
            threshold = float(value)
        except ValueError:
            continue
        on_breach = "kill" if "kill" in raw.lower() else "alert"
        out.kpis.append(KpiSpec(
            name="roas",
            direction="min" if op in ("<", "<=") else "max",
            threshold=threshold,
            window_days=(monitor_window_s or 86_400.0) / 86_400.0,
            on_breach=on_breach,
        ))
        trail.append({
            "slot": "kpi:roas",
            "matched": {"op": op, "threshold": threshold},
        })
    for op, value in _CPA_RE.findall(raw):
        try:
            threshold = float(value)
        except ValueError:
            continue
        on_breach = "kill" if "kill" in raw.lower() else "alert"
        out.kpis.append(KpiSpec(
            name="cpa",
            direction="max" if op in (">", ">=") else "min",
            threshold=threshold,
            window_days=(monitor_window_s or 86_400.0) / 86_400.0,
            on_breach=on_breach,
        ))
        trail.append({
            "slot": "kpi:cpa",
            "matched": {"op": op, "threshold": threshold},
        })

    # 5. Verb → subgoal pipeline. Keep insertion order.
    seen: list[str] = []
    for token in re.findall(r"[A-Za-zӨөҮү_-]+", raw):
        canonical = _normalise_word(token)
        if canonical and canonical in _VERB_TO_SUBGOAL and canonical not in seen:
            seen.append(canonical)

    # Reorder to a sensible execution sequence — sync→publish→video→
    # launch→monitor→kill — but keep subgoals only for verbs we saw.
    canonical_order = [
        "sync", "publish", "video", "launch",
        "scale", "monitor", "kill", "refund",
    ]
    ordered = [v for v in canonical_order if v in seen]
    prev: str | None = None
    for verb in ordered:
        name, desc, deadline = _VERB_TO_SUBGOAL[verb]
        # Monitor + kill inherit the monitor window if specified.
        if name in ("monitor", "kill_check") and monitor_window_s:
            deadline = monitor_window_s
        out.subgoals.append(SubGoal(
            name=name,
            description=desc,
            deadline_s=deadline,
            depends_on=(prev,) if prev else (),
        ))
        prev = name
        trail.append({"slot": "subgoal", "matched": name})

    if not out.subgoals:
        out.subgoals.append(SubGoal(
            name="investigate",
            description="No actionable verbs detected — probe context.",
            deadline_s=900.0,
        ))
        trail.append({"slot": "fallback", "matched": "investigate"})

    out.trail = trail
    return out
