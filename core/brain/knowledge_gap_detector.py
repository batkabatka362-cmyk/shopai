"""Knowledge gap detector — surface questions the brain should answer.

curiosity_engine flags high-prediction-error events. But an AGI-tier
brain should also notice what it *doesn't know*: facts that are
absent, uncertainties that never got resolved, decisions repeatedly
made without ground truth. This detector pulls from five signal
sources (all dependency-injected for tests):

  • unresolved_claims    — conflicts still unresolved in the belief
                            merger → ask owner or gather source
  • repeated_probes      — curiosity items popped many times with no
                            final resolution → need a longer probe
  • low_evidence_decisions — decisions taken with evidence_score < X
                              → gather before repeating
  • stale_knowledge      — knowledge_graph facts older than N days on
                            high-churn predicates
  • drift_without_cause  — concept_drift events without a matching
                            causal_graph driver → unexplained shift

Emits ranked ``KnowledgeGap`` records with severity + recommended
probe. Pure stdlib, deterministic, tests mock the providers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.knowledge_gap_detector")


Severity = Literal["info", "warning", "critical"]


@dataclass
class KnowledgeGap:
    key: str
    source: str
    severity: Severity
    detail: str
    recommended_probe: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source": self.source,
            "severity": self.severity,
            "detail": self.detail,
            "recommended_probe": self.recommended_probe,
            "metadata": dict(self.metadata),
        }


@dataclass
class GapReport:
    gaps: list[KnowledgeGap] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for g in self.gaps if g.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for g in self.gaps if g.severity == "warning")

    def as_dict(self) -> dict[str, Any]:
        return {
            "gaps": [g.as_dict() for g in self.gaps],
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "total": len(self.gaps),
        }


# ── Severity helpers ─────────────────────────────────────

_RANK = {"info": 0, "warning": 1, "critical": 2}


def _cap_severity(sev: Severity) -> Severity:
    if sev not in _RANK:
        return "info"
    return sev


class KnowledgeGapDetector:
    def __init__(
        self,
        *,
        unresolved_claims_provider: Callable[[], Iterable[dict[str, Any]]]
            | None = None,
        repeated_probes_provider: Callable[[], Iterable[dict[str, Any]]]
            | None = None,
        low_evidence_decisions_provider: Callable[[], Iterable[dict[str, Any]]]
            | None = None,
        stale_knowledge_provider: Callable[[], Iterable[dict[str, Any]]]
            | None = None,
        drift_without_cause_provider: Callable[[], Iterable[dict[str, Any]]]
            | None = None,
        max_gaps: int = 50,
    ) -> None:
        if max_gaps < 1:
            raise ValueError("max_gaps must be ≥ 1")
        self._unresolved_claims = unresolved_claims_provider
        self._repeated_probes = repeated_probes_provider
        self._low_evidence = low_evidence_decisions_provider
        self._stale_knowledge = stale_knowledge_provider
        self._drift_without_cause = drift_without_cause_provider
        self._max_gaps = int(max_gaps)

    # ── Safe provider wrapper ─────────────────────────────

    def _safe(
        self,
        fn: Callable[[], Iterable[dict[str, Any]]] | None,
    ) -> list[dict[str, Any]]:
        if fn is None:
            return []
        try:
            return list(fn())
        except Exception as exc:
            logger.debug("gap provider failed: %s", exc)
            return []

    # ── Per-source scanners ──────────────────────────────

    def _scan_unresolved_claims(self) -> list[KnowledgeGap]:
        out: list[KnowledgeGap] = []
        for item in self._safe(self._unresolved_claims):
            subject = str(item.get("subject", ""))
            predicate = str(item.get("predicate", ""))
            if not subject or not predicate:
                continue
            verdict = str(item.get("verdict", ""))
            severity: Severity = (
                "critical" if verdict == "conflicted" else "warning"
            )
            out.append(KnowledgeGap(
                key=f"claim:{subject}.{predicate}",
                source="belief_propagator",
                severity=severity,
                detail=(
                    f"{subject}.{predicate} still {verdict}"
                ),
                recommended_probe=(
                    f"gather ground truth for {subject}.{predicate}"
                ),
                metadata=dict(item),
            ))
        return out

    def _scan_repeated_probes(self) -> list[KnowledgeGap]:
        out: list[KnowledgeGap] = []
        for item in self._safe(self._repeated_probes):
            probe_id = str(item.get("id", ""))
            repeats = int(item.get("repeat_count", 0) or 0)
            if repeats < 3:
                continue
            severity: Severity = (
                "critical" if repeats >= 10 else "warning"
            )
            out.append(KnowledgeGap(
                key=f"probe:{probe_id}",
                source="curiosity_engine",
                severity=severity,
                detail=(
                    f"probe {probe_id} unresolved "
                    f"after {repeats} attempts"
                ),
                recommended_probe="schedule a deeper investigation",
                metadata=dict(item),
            ))
        return out

    def _scan_low_evidence_decisions(self) -> list[KnowledgeGap]:
        out: list[KnowledgeGap] = []
        for item in self._safe(self._low_evidence):
            did = str(item.get("id", ""))
            score = float(item.get("evidence_score", 0) or 0)
            if score >= 0.5:
                continue
            severity: Severity = (
                "critical" if score < 0.25 else "warning"
            )
            out.append(KnowledgeGap(
                key=f"decision:{did}",
                source="evidence_sufficiency",
                severity=severity,
                detail=(
                    f"decision {did} relied on weak evidence "
                    f"({score:.2f})"
                ),
                recommended_probe=(
                    "gather more samples before repeating this class"
                ),
                metadata=dict(item),
            ))
        return out

    def _scan_stale_knowledge(self) -> list[KnowledgeGap]:
        out: list[KnowledgeGap] = []
        for item in self._safe(self._stale_knowledge):
            subject = str(item.get("subject", ""))
            predicate = str(item.get("predicate", ""))
            age_days = float(item.get("age_days", 0) or 0)
            if age_days < 30:
                continue
            severity: Severity = (
                "warning" if age_days < 90 else "critical"
            )
            out.append(KnowledgeGap(
                key=f"stale:{subject}.{predicate}",
                source="knowledge_graph",
                severity=severity,
                detail=(
                    f"{subject}.{predicate} unrefreshed "
                    f"for {age_days:.0f} days"
                ),
                recommended_probe="re-query the source adapter",
                metadata=dict(item),
            ))
        return out

    def _scan_drift_without_cause(self) -> list[KnowledgeGap]:
        out: list[KnowledgeGap] = []
        for item in self._safe(self._drift_without_cause):
            feature = str(item.get("feature", ""))
            psi = float(item.get("psi", 0) or 0)
            if psi < 0.1:
                continue
            severity: Severity = (
                "critical" if psi >= 0.2 else "warning"
            )
            out.append(KnowledgeGap(
                key=f"drift:{feature}",
                source="concept_drift+causal_graph",
                severity=severity,
                detail=(
                    f"{feature} drifted (PSI={psi:.3f}) but has no "
                    "known causal driver"
                ),
                recommended_probe=(
                    f"add {feature} to causal_graph observations"
                ),
                metadata=dict(item),
            ))
        return out

    # ── Detect ───────────────────────────────────────────

    def detect(self) -> GapReport:
        gaps: list[KnowledgeGap] = []
        gaps.extend(self._scan_unresolved_claims())
        gaps.extend(self._scan_repeated_probes())
        gaps.extend(self._scan_low_evidence_decisions())
        gaps.extend(self._scan_stale_knowledge())
        gaps.extend(self._scan_drift_without_cause())
        # Sort by severity desc, then source name for stability
        gaps.sort(
            key=lambda g: (-_RANK[g.severity], g.source, g.key),
        )
        return GapReport(gaps=gaps[: self._max_gaps])

    def stats(self) -> dict[str, Any]:
        return {
            "max_gaps": self._max_gaps,
            "providers": sum(
                1 for p in (
                    self._unresolved_claims,
                    self._repeated_probes,
                    self._low_evidence,
                    self._stale_knowledge,
                    self._drift_without_cause,
                )
                if p is not None
            ),
        }
