"""Principle extractor — distil many rules into one higher-order rule.

abstraction_ladder moves rules up the specificity stack but keeps
the individual rules around. Over time the brain accumulates many
similar rules:

  * "kill if ROAS < 1.5 after day 3"
  * "kill if ROAS < 1.3 after day 3 with low-AOV"
  * "kill if ROAS < 1.7 after day 3 with high-spend"

Owners would rather read one *principle* — "kill losing-ad products
around day 3 when ROAS stays below the break-even band" — than ten
threshold rules. The principle is what the brain actually learned.

``PrincipleExtractor`` takes a bundle of rules (each with antecedent
clauses + consequent), groups them by semantic signature (shared
verbs and terms), and emits a ``Principle`` that:

  • summarises the shared *consequent*
  • names the shared *conditions*
  • lists variable thresholds (so the principle captures the range)
  • keeps provenance (the child rule ids)

Principles feed weekly_digest + self_narrative for owner-facing prose.
Pure stdlib, deterministic, LLM-free (regex + set operations).
"""
from __future__ import annotations

import re
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.principle_extractor")


@dataclass
class Rule:
    id: str
    antecedent: str          # e.g. "roas < 1.5 AND days >= 3"
    consequent: str          # e.g. "kill"
    support: int = 1
    confidence: float = 0.5

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "antecedent": self.antecedent,
            "consequent": self.consequent,
            "support": self.support,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class Principle:
    id: str
    summary: str              # one-line human-readable principle
    consequent: str
    shared_terms: tuple[str, ...]
    threshold_ranges: dict[str, tuple[float, float]]
    child_ids: tuple[str, ...]
    support_total: int
    avg_confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "consequent": self.consequent,
            "shared_terms": list(self.shared_terms),
            "threshold_ranges": {
                k: [round(v[0], 4), round(v[1], 4)]
                for k, v in self.threshold_ranges.items()
            },
            "child_ids": list(self.child_ids),
            "support_total": self.support_total,
            "avg_confidence": round(self.avg_confidence, 4),
        }


_STOPWORDS = {
    "and", "or", "the", "a", "an", "is", "are", "of", "if",
    "then", "when", "with", "to", "at", "on", "in",
}
_CLAUSE_SPLIT = re.compile(r"\s+(?:and|&&|,)\s+", re.IGNORECASE)
_METRIC_CLAUSE = re.compile(
    r"(?P<key>[a-z_]+)\s*(?P<op>[<>]=?|=)\s*"
    r"(?P<val>-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _normalise_terms(text: str) -> set[str]:
    words = re.findall(r"[a-z_]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _extract_thresholds(
    antecedent: str,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for match in _METRIC_CLAUSE.finditer(antecedent):
        key = match.group("key").lower()
        try:
            out[key] = float(match.group("val"))
        except ValueError:
            continue
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


class PrincipleExtractor:
    def __init__(
        self,
        *,
        min_rules: int = 2,
        similarity_threshold: float = 0.5,
    ) -> None:
        if min_rules < 2:
            raise ValueError("min_rules must be ≥ 2")
        if not 0.0 < similarity_threshold <= 1.0:
            raise ValueError(
                "similarity_threshold must be in (0, 1]",
            )
        self._lock = threading.Lock()
        self._min_rules = int(min_rules)
        self._sim_threshold = float(similarity_threshold)

    # ── Extract ──────────────────────────────────────────

    def extract(
        self, rules: Iterable[Rule],
    ) -> list[Principle]:
        rule_list = [r for r in rules if r.antecedent and r.consequent]
        if len(rule_list) < self._min_rules:
            return []
        # Group by consequent first
        by_conseq: dict[str, list[Rule]] = {}
        for r in rule_list:
            by_conseq.setdefault(r.consequent.lower(), []).append(r)
        principles: list[Principle] = []
        for conseq, bucket in by_conseq.items():
            if len(bucket) < self._min_rules:
                continue
            principles.extend(self._cluster(conseq, bucket))
        principles.sort(key=lambda p: -p.support_total)
        return principles

    def _cluster(
        self, consequent: str, rules: list[Rule],
    ) -> list[Principle]:
        remaining = list(rules)
        out: list[Principle] = []
        while len(remaining) >= self._min_rules:
            seed = remaining[0]
            seed_terms = _normalise_terms(seed.antecedent)
            cluster: list[Rule] = [seed]
            leftover: list[Rule] = []
            for r in remaining[1:]:
                terms = _normalise_terms(r.antecedent)
                if (
                    _jaccard(seed_terms, terms)
                    >= self._sim_threshold
                ):
                    cluster.append(r)
                else:
                    leftover.append(r)
            if len(cluster) < self._min_rules:
                # couldn't grow a principle from this seed; discard
                remaining = leftover
                continue
            principle = self._principle_from_cluster(
                consequent, cluster,
            )
            out.append(principle)
            remaining = leftover
        return out

    def _principle_from_cluster(
        self, consequent: str, cluster: list[Rule],
    ) -> Principle:
        # Shared terms: intersection across all rules' antecedent
        # terms
        term_sets = [
            _normalise_terms(r.antecedent) for r in cluster
        ]
        shared = term_sets[0]
        for ts in term_sets[1:]:
            shared = shared & ts
        shared_list = tuple(sorted(shared))
        # Threshold ranges
        ranges: dict[str, list[float]] = {}
        for r in cluster:
            for key, val in _extract_thresholds(r.antecedent).items():
                ranges.setdefault(key, []).append(val)
        threshold_ranges = {
            key: (min(vals), max(vals))
            for key, vals in ranges.items()
        }
        # Summary
        if shared_list:
            term_bits = ", ".join(shared_list[:4])
        else:
            term_bits = "context terms"
        range_bits = ", ".join(
            f"{k}∈[{lo:g},{hi:g}]"
            for k, (lo, hi) in threshold_ranges.items()
        )
        summary = (
            f"{consequent} when {term_bits}"
            + (f" with {range_bits}" if range_bits else "")
        )
        support_total = sum(r.support for r in cluster)
        avg_conf = (
            sum(r.confidence for r in cluster) / len(cluster)
        )
        return Principle(
            id=uuid.uuid4().hex,
            summary=summary,
            consequent=consequent,
            shared_terms=shared_list,
            threshold_ranges=threshold_ranges,
            child_ids=tuple(r.id for r in cluster),
            support_total=support_total,
            avg_confidence=avg_conf,
        )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "min_rules": self._min_rules,
                "similarity_threshold": self._sim_threshold,
            }
