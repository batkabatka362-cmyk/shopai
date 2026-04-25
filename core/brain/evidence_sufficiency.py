"""Evidence sufficiency — is there enough to decide yet?

answer_synthesizer (v19-D7) builds a bundle of facts and emits a
confidence score. evidence_sufficiency answers the meta-question
*before* synthesising: 'do we have enough evidence to even
attempt an answer?'. Stops the brain from grinding on a question
where the inputs are too thin to say anything useful.

Four dimensions the checker evaluates:

  coverage          — number of distinct sources (policy, reward,
                      search, rule, memory) contributing
  volume            — total weighted evidence units
  recency           — at least one fact ≤ recency_window_s old
  diversity         — Shannon entropy over source distribution
                      (avoids 50 rows from one source dominating)

Each dimension gets a 0-1 score; overall_sufficiency is their
weighted mean. verdict thresholds:

  decide     overall ≥ 0.7 AND coverage_score ≥ 0.5
  gather     0.4 ≤ overall < 0.7
  abstain    overall < 0.4

The engine surfaces the weakest dimension so the caller knows
which evidence to collect next. Pure stdlib, zero LLM.
"""
from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


Verdict = Literal["decide", "gather", "abstain"]


@dataclass
class EvidenceFact:
    source: str
    weight: float = 0.5
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "weight": round(self.weight, 3),
            "ts": self.ts,
        }


@dataclass
class SufficiencyReport:
    verdict: Verdict
    overall: float
    coverage_score: float
    volume_score: float
    recency_score: float
    diversity_score: float
    weakest_dimension: str
    n_facts: int
    sources: list[str] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "overall": round(self.overall, 3),
            "coverage_score": round(self.coverage_score, 3),
            "volume_score": round(self.volume_score, 3),
            "recency_score": round(self.recency_score, 3),
            "diversity_score": round(self.diversity_score, 3),
            "weakest_dimension": self.weakest_dimension,
            "n_facts": self.n_facts,
            "sources": list(self.sources),
            "note": self.note,
        }


# ── Checker ────────────────────────────────────────────────

_DEFAULT_MIN_SOURCES = 3
_DEFAULT_MIN_VOLUME = 2.0
_DEFAULT_RECENCY_WINDOW_S = 30 * 86_400      # 30 days
_DEFAULT_WEIGHTS = {
    "coverage": 1.0,
    "volume": 1.0,
    "recency": 0.7,
    "diversity": 0.8,
}


def check(
    facts: Iterable[EvidenceFact | dict[str, Any]],
    *,
    min_sources: int = _DEFAULT_MIN_SOURCES,
    min_volume: float = _DEFAULT_MIN_VOLUME,
    recency_window_s: float = _DEFAULT_RECENCY_WINDOW_S,
    weights: dict[str, float] | None = None,
    now: float | None = None,
) -> SufficiencyReport:
    weights = weights or _DEFAULT_WEIGHTS
    now = now or time.time()
    coerced: list[EvidenceFact] = []
    for f in facts:
        if isinstance(f, EvidenceFact):
            coerced.append(f)
        elif isinstance(f, dict):
            coerced.append(EvidenceFact(
                source=str(f.get("source", "unknown")),
                weight=float(f.get("weight", 0.5)),
                ts=float(f.get("ts", 0.0)),
            ))
    n = len(coerced)
    if n == 0:
        return SufficiencyReport(
            verdict="abstain",
            overall=0.0,
            coverage_score=0.0, volume_score=0.0,
            recency_score=0.0, diversity_score=0.0,
            weakest_dimension="coverage", n_facts=0,
            sources=[], note="no evidence",
        )

    source_counts: Counter[str] = Counter(
        f.source for f in coerced if f.source
    )
    sources = sorted(source_counts.keys())

    # Coverage: fraction of min_sources reached
    coverage = min(1.0, len(sources) / max(1, min_sources))

    # Volume: saturating ratio to min_volume
    total_weight = sum(f.weight for f in coerced)
    volume = min(1.0, total_weight / max(0.1, min_volume))

    # Recency: at least one fact within the window
    if any(
        f.ts > 0 and (now - f.ts) <= recency_window_s
        for f in coerced
    ):
        recency = 1.0
    else:
        # If no ts at all, don't penalise heavily
        missing_ts = all(f.ts <= 0 for f in coerced)
        recency = 0.5 if missing_ts else 0.2

    # Diversity: normalised Shannon entropy over source distribution
    diversity = _normalised_entropy(source_counts)

    # Weighted overall
    components = {
        "coverage": coverage,
        "volume": volume,
        "recency": recency,
        "diversity": diversity,
    }
    total_w = sum(weights.get(k, 1.0) for k in components)
    overall = (
        sum(components[k] * weights.get(k, 1.0) for k in components)
        / max(1e-6, total_w)
    )

    weakest = min(components.items(), key=lambda kv: kv[1])[0]

    if overall >= 0.7 and coverage >= 0.5:
        verdict: Verdict = "decide"
    elif overall >= 0.4:
        verdict = "gather"
    else:
        verdict = "abstain"

    return SufficiencyReport(
        verdict=verdict,
        overall=overall,
        coverage_score=coverage,
        volume_score=volume,
        recency_score=recency,
        diversity_score=diversity,
        weakest_dimension=weakest,
        n_facts=n,
        sources=sources,
        note=f"weakest: {weakest}",
    )


# ── Helpers ────────────────────────────────────────────────

def _normalised_entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    k = len(counts)
    if k <= 1:
        return 0.0
    probs = [c / total for c in counts.values()]
    entropy = -sum(p * math.log(p) for p in probs if p > 0)
    max_entropy = math.log(k)
    return entropy / max_entropy if max_entropy > 0 else 0.0
