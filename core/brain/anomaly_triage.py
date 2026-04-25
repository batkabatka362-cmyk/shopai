"""Anomaly triage — classify and route surprise events.

surprise_detector (v8-D2) emits SurpriseEvent with magnitude and
a narrative, but nothing decides *what to do* with each anomaly.
A 4σ ROAS spike deserves a victory lap; a 4σ refund spike demands
immediate attention. Without a triage layer the daemon treated
both the same way.

AnomalyTriage classifies each incoming anomaly into:

  • celebrate  — positive surprise the owner should notice
  • escalate   — negative surprise needing human attention
  • investigate — unclear; queue counterfactual / debate
  • dismiss     — low magnitude or recurrence; no action

Classification rules (deterministic, pure Python):

  1. If magnitude < 0.3 → dismiss
  2. If signature contains 'refund' or 'churn' or z < -2 → escalate
  3. If signature contains 'roas' or 'revenue' and z > +2 → celebrate
  4. If kind == 'novel' AND magnitude > 0.7 → investigate
  5. Otherwise → investigate at lower priority

Each triaged item carries a recommended subsystem to route to
(ethics_gate / debate / metacognition / opportunity_scout etc.)
so the dispatcher picks the right tool without further logic.

APIs:

  triage(event)            → TriageVerdict
  triage_batch(events)     → list[TriageVerdict] (priority-sorted)
  stats()                   → counts per verdict class
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


VerdictClass = Literal["celebrate", "escalate", "investigate", "dismiss"]

_BAD_TOKENS = ("refund", "churn", "stockout", "breach", "error",
                "crash", "violation")
_GOOD_TOKENS = ("roas", "revenue", "scale", "win", "signup")


@dataclass
class SurpriseLike:
    """Minimal duck-type the triage consumes — matches surprise_detector.
    SurpriseEvent shape (kind, signature, magnitude, z_score)."""
    signature: str
    magnitude: float
    kind: str = "outlier"
    z_score: float | None = None
    narrative: str = ""


@dataclass
class TriageVerdict:
    signature: str
    verdict: VerdictClass
    priority: float                  # 0..1
    route: str                       # subsystem name
    narrative: str = ""
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "verdict": self.verdict,
            "priority": round(self.priority, 3),
            "route": self.route,
            "narrative": self.narrative,
            "reasons": list(self.reasons),
        }


# ── Classifier ─────────────────────────────────────────────

_BAD_RE = re.compile(
    "|".join(re.escape(t) for t in _BAD_TOKENS), re.IGNORECASE,
)
_GOOD_RE = re.compile(
    "|".join(re.escape(t) for t in _GOOD_TOKENS), re.IGNORECASE,
)


def triage(event: Any) -> TriageVerdict:
    """Classify a SurpriseEvent-like object."""
    sig = str(getattr(event, "signature", "") or "").strip()
    magnitude = float(getattr(event, "magnitude", 0.0) or 0.0)
    kind = str(getattr(event, "kind", "outlier") or "outlier")
    z = getattr(event, "z_score", None)
    narrative = str(getattr(event, "narrative", "") or "")

    reasons: list[str] = []

    # 1. Low magnitude → dismiss.
    if magnitude < 0.3:
        return TriageVerdict(
            signature=sig, verdict="dismiss",
            priority=magnitude, route="noop",
            narrative=narrative,
            reasons=["magnitude < 0.3"],
        )

    is_bad = bool(_BAD_RE.search(sig) or _BAD_RE.search(narrative))
    is_good = bool(_GOOD_RE.search(sig) or _GOOD_RE.search(narrative))
    z_negative = z is not None and z < -2
    z_positive = z is not None and z > 2

    # 2. Negative signal → escalate.
    if is_bad or z_negative:
        reasons.append("negative signal token" if is_bad else "z<-2")
        priority = min(1.0, 0.7 + magnitude * 0.3)
        return TriageVerdict(
            signature=sig, verdict="escalate",
            priority=priority, route="ethics_gate",
            narrative=narrative,
            reasons=reasons,
        )

    # 3. Strong positive signal → celebrate.
    if (is_good and z_positive) or (is_good and magnitude >= 0.7):
        reasons.append("positive signal + strong magnitude")
        return TriageVerdict(
            signature=sig, verdict="celebrate",
            priority=min(1.0, 0.5 + magnitude * 0.5),
            route="opportunity_scout",
            narrative=narrative,
            reasons=reasons,
        )

    # 4. Novel + high magnitude → investigate.
    if kind == "novel" and magnitude > 0.7:
        reasons.append("novel + high magnitude")
        return TriageVerdict(
            signature=sig, verdict="investigate",
            priority=magnitude, route="debate",
            narrative=narrative,
            reasons=reasons,
        )

    # 5. Default: investigate at lower priority.
    return TriageVerdict(
        signature=sig, verdict="investigate",
        priority=magnitude * 0.6, route="metacognition",
        narrative=narrative,
        reasons=["default investigation"],
    )


def triage_batch(events: list[Any]) -> list[TriageVerdict]:
    verdicts = [triage(e) for e in events]
    verdicts.sort(key=lambda v: -v.priority)
    return verdicts


def stats(verdicts: list[TriageVerdict]) -> dict[str, int]:
    counts = {
        "celebrate": 0, "escalate": 0,
        "investigate": 0, "dismiss": 0,
    }
    for v in verdicts:
        counts[v.verdict] = counts.get(v.verdict, 0) + 1
    return counts
