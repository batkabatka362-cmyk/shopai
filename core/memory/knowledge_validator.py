"""Knowledge validator — cross-source fact contradiction detection.

consolidation (v5) detects contradictory *rules* inside memory
intelligence. The brain also ingests facts from ontology (v7-D5),
knowledge_base, knowledge_ingest — across stores. Two sources
can assert incompatible things about the same subject and nothing
catches it today.

KnowledgeValidator walks a batch of (subject, predicate, object,
source, confidence) claims and flags:

  • direct contradictions   — same (subject, predicate) but
                               objects disagree
  • type conflicts          — entity claimed as two mutually-
                               exclusive types (e.g. Supplier AND
                               Product)
  • range violations        — numeric objects outside a declared
                               allowed band

Each Conflict carries severity (high / medium / low) based on
confidence of competing claims and proposes a resolution
(highest-confidence-wins / owner-review / merge). Pure stdlib.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


Severity = Literal["high", "medium", "low"]


@dataclass
class Claim:
    subject: str
    predicate: str
    object: Any
    source: str
    confidence: float = 0.5

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "source": self.source,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class Conflict:
    kind: str                    # "direct" | "type_conflict" | "range"
    severity: Severity
    subject: str
    predicate: str
    claims: list[Claim] = field(default_factory=list)
    resolution: str = ""         # "highest_confidence" | "owner_review"
                                  # | "merge"
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "subject": self.subject,
            "predicate": self.predicate,
            "claims": [c.as_dict() for c in self.claims],
            "resolution": self.resolution,
            "note": self.note,
        }


@dataclass
class ValidationReport:
    conflicts: list[Conflict] = field(default_factory=list)
    claims_examined: int = 0

    def by_severity(self) -> dict[str, int]:
        out: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for c in self.conflicts:
            out[c.severity] = out.get(c.severity, 0) + 1
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "claims_examined": self.claims_examined,
            "conflict_count": len(self.conflicts),
            "by_severity": self.by_severity(),
            "conflicts": [c.as_dict() for c in self.conflicts],
        }


# ── Validator ──────────────────────────────────────────────

# Mutually-exclusive type pairs for type_conflict detection.
_INCOMPATIBLE_TYPES = {
    frozenset({"Product", "Supplier"}),
    frozenset({"Customer", "Competitor"}),
    frozenset({"Rule", "Fact"}),
}


class KnowledgeValidator:
    def __init__(
        self,
        numeric_ranges: dict[str, tuple[float, float]] | None = None,
        functional_predicates: Iterable[str] | None = None,
    ) -> None:
        # predicate → (lo, hi)
        self._ranges: dict[str, tuple[float, float]] = dict(
            numeric_ranges or {},
        )
        # predicates where conflicting objects are real contradictions
        # (e.g. `name`, `primary_category`); by default treat every
        # predicate as potentially functional.
        self._functional: set[str] = set(
            functional_predicates or [],
        )

    def register_range(
        self, predicate: str, lo: float, hi: float,
    ) -> None:
        self._ranges[predicate] = (float(lo), float(hi))

    def register_functional(self, predicate: str) -> None:
        self._functional.add(predicate)

    # ── Main validation ───────────────────────────────────

    def validate(
        self, claims: Iterable[Claim | dict[str, Any]],
    ) -> ValidationReport:
        coerced = [self._coerce(c) for c in claims]
        coerced = [c for c in coerced if c is not None]
        report = ValidationReport(claims_examined=len(coerced))
        report.conflicts.extend(self._find_direct(coerced))
        report.conflicts.extend(self._find_type_conflicts(coerced))
        report.conflicts.extend(self._find_range_violations(coerced))
        # Sort: high severity first, then most-claims groups
        severity_rank = {"high": 0, "medium": 1, "low": 2}
        report.conflicts.sort(
            key=lambda c: (severity_rank.get(c.severity, 9),
                            -len(c.claims)),
        )
        return report

    # ── Detectors ─────────────────────────────────────────

    def _find_direct(
        self, claims: list[Claim],
    ) -> list[Conflict]:
        buckets: dict[tuple[str, str], list[Claim]] = defaultdict(list)
        for c in claims:
            buckets[(c.subject, c.predicate)].append(c)
        out: list[Conflict] = []
        for (subj, pred), group in buckets.items():
            if len(group) < 2:
                continue
            # Only consider functional predicates OR when any caller
            # registered the predicate as functional.
            objects = {self._object_key(c.object) for c in group}
            if len(objects) < 2:
                continue
            is_functional = (
                not self._functional or pred in self._functional
            )
            if not is_functional:
                continue
            # Severity: high if any claim has confidence > 0.7
            max_conf = max(c.confidence for c in group)
            severity: Severity = (
                "high" if max_conf >= 0.7 else
                "medium" if max_conf >= 0.4 else "low"
            )
            # Resolution: if max_conf >> second_max, highest_confidence
            sorted_confs = sorted(
                (c.confidence for c in group), reverse=True,
            )
            if (len(sorted_confs) >= 2
                    and sorted_confs[0] - sorted_confs[1] >= 0.3):
                resolution = "highest_confidence"
            else:
                resolution = "owner_review"
            out.append(Conflict(
                kind="direct",
                severity=severity,
                subject=subj, predicate=pred,
                claims=group,
                resolution=resolution,
                note=(
                    f"{len(objects)} distinct values for "
                    f"({subj}, {pred})"
                ),
            ))
        return out

    def _find_type_conflicts(
        self, claims: list[Claim],
    ) -> list[Conflict]:
        # Only consider predicate == 'type'
        by_subject: dict[str, list[Claim]] = defaultdict(list)
        for c in claims:
            if c.predicate == "type":
                by_subject[c.subject].append(c)
        out: list[Conflict] = []
        for subj, group in by_subject.items():
            types = {str(c.object) for c in group}
            for incompat_set in _INCOMPATIBLE_TYPES:
                if incompat_set.issubset(types):
                    out.append(Conflict(
                        kind="type_conflict",
                        severity="high",
                        subject=subj, predicate="type",
                        claims=group,
                        resolution="owner_review",
                        note=(f"mutually-exclusive types "
                              f"{sorted(incompat_set)} "
                              f"on same entity"),
                    ))
                    break
        return out

    def _find_range_violations(
        self, claims: list[Claim],
    ) -> list[Conflict]:
        out: list[Conflict] = []
        for c in claims:
            band = self._ranges.get(c.predicate)
            if band is None:
                continue
            lo, hi = band
            try:
                val = float(c.object)
            except (TypeError, ValueError):
                continue
            if val < lo or val > hi:
                out.append(Conflict(
                    kind="range",
                    severity="medium",
                    subject=c.subject, predicate=c.predicate,
                    claims=[c],
                    resolution="owner_review",
                    note=(f"value {val} outside [{lo}, {hi}]"),
                ))
        return out

    # ── Helpers ────────────────────────────────────────────

    @staticmethod
    def _object_key(obj: Any) -> Any:
        """Hashable representation used to compare predicate values."""
        if isinstance(obj, (list, tuple)):
            return tuple(obj)
        if isinstance(obj, dict):
            return tuple(sorted(obj.items()))
        return obj

    @staticmethod
    def _coerce(
        c: Claim | dict[str, Any],
    ) -> Claim | None:
        if isinstance(c, Claim):
            if not c.subject or not c.predicate:
                return None
            return c
        if not isinstance(c, dict):
            return None
        subject = str(c.get("subject") or "").strip()
        predicate = str(c.get("predicate") or "").strip()
        source = str(c.get("source") or "unknown").strip()
        if not subject or not predicate:
            return None
        try:
            confidence = float(c.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        return Claim(
            subject=subject, predicate=predicate,
            object=c.get("object"),
            source=source, confidence=confidence,
        )
