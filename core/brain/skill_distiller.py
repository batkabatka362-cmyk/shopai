"""Skill distiller — auto-promote case clusters into named skills.

case_based_reasoner accumulates (situation, action, outcome) tuples.
When N similar cases agree on the same winning action, that's a
*skill* waiting to be named. The distiller:

  1. Walks the case base.
  2. Buckets cases by canonical (action, signature) — signature = a
     small set of key=value pairs of the situation.
  3. For each bucket with ≥ ``min_support`` cases AND mean outcome
     ≥ ``min_score``, emits a ``DistillationCandidate``.
  4. Optionally registers the candidate into the ``skill_library``
     as a precondition-gated Skill, where the precondition is a
     literal exact-match against the discovered signature.

The distiller is *suggestive*, not prescriptive: it returns
candidates by default; the caller decides whether to commit them via
``promote_all()``. Pure stdlib. Deterministic.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.skill_distiller")


@dataclass
class DistillationCandidate:
    name: str
    action: str
    signature: dict[str, Any]
    support: int
    mean_score: float
    sample_case_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "action": self.action,
            "signature": dict(self.signature),
            "support": self.support,
            "mean_score": round(self.mean_score, 4),
            "sample_case_ids": list(self.sample_case_ids),
        }


@dataclass
class DistillationReport:
    inspected: int
    candidates: list[DistillationCandidate] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "inspected": self.inspected,
            "candidates": [c.as_dict() for c in self.candidates],
        }


# ── Helpers ───────────────────────────────────────────────

def _canonicalise(
    situation: dict[str, Any], keys: Iterable[str] | None,
) -> dict[str, Any]:
    """Project a situation onto the configured keys (or all keys when
    none specified) and stringify values for deterministic equality."""
    if not isinstance(situation, dict):
        return {}
    selected = situation
    if keys is not None:
        selected = {
            k: situation[k]
            for k in keys
            if k in situation
        }
    return {k: str(v) for k, v in sorted(selected.items())}


def _signature_str(sig: dict[str, Any]) -> str:
    return "|".join(f"{k}={v}" for k, v in sorted(sig.items()))


def _name_for(action: str, sig: dict[str, Any]) -> str:
    short = (
        "_".join(f"{k}-{v}" for k, v in sorted(sig.items()))[:80]
        if sig else "any"
    )
    return f"distilled.{action}.{short}"


# ── Distiller ─────────────────────────────────────────────

class SkillDistiller:
    def __init__(
        self,
        *,
        case_reasoner: Any = None,
        skill_library: Any = None,
    ) -> None:
        # Both are dependency-injected for testability; fall back to
        # the lazy singletons in production.
        self._case_reasoner = case_reasoner
        self._skill_library = skill_library

    def _cases(self) -> list[Any]:
        if self._case_reasoner is not None:
            return self._case_reasoner._all_cases()  # noqa: SLF001
        try:
            from core.memory.case_based_reasoner import CaseBasedReasoner
            self._case_reasoner = CaseBasedReasoner()
            return self._case_reasoner._all_cases()  # noqa: SLF001
        except Exception as exc:
            logger.debug("case base unavailable: %s", exc)
            return []

    def _library(self):
        if self._skill_library is not None:
            return self._skill_library
        try:
            from core.brain.skill_library import SkillLibrary
            self._skill_library = SkillLibrary()
            return self._skill_library
        except Exception as exc:
            logger.debug("skill library unavailable: %s", exc)
            return None

    # ── Distill ──────────────────────────────────────────

    def distill(
        self,
        *,
        signature_keys: Iterable[str] | None = None,
        min_support: int = 5,
        min_score: float = 3.0,
    ) -> DistillationReport:
        if min_support < 2:
            raise ValueError("min_support must be ≥ 2")
        cases = self._cases()
        buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {"sigs": None, "scores": [], "ids": []},
        )
        for c in cases:
            action = str(getattr(c, "action", "") or "")
            sit = getattr(c, "situation", {}) or {}
            sig = _canonicalise(sit, signature_keys)
            sig_str = _signature_str(sig)
            key = (action, sig_str)
            entry = buckets[key]
            if entry["sigs"] is None:
                entry["sigs"] = sig
            try:
                entry["scores"].append(float(
                    getattr(c, "outcome_score", 0.0) or 0.0,
                ))
            except (TypeError, ValueError):
                continue
            cid = getattr(c, "id", None)
            if cid:
                entry["ids"].append(str(cid))

        candidates: list[DistillationCandidate] = []
        for (action, sig_str), entry in buckets.items():
            scores = entry["scores"]
            if len(scores) < min_support:
                continue
            mean_score = sum(scores) / len(scores) if scores else 0.0
            if mean_score < min_score:
                continue
            if not action:
                continue
            sig = entry["sigs"] or {}
            candidates.append(DistillationCandidate(
                name=_name_for(action, sig),
                action=action,
                signature=dict(sig),
                support=len(scores),
                mean_score=mean_score,
                sample_case_ids=entry["ids"][:5],
            ))
        candidates.sort(
            key=lambda c: (-c.mean_score, -c.support),
        )
        return DistillationReport(
            inspected=len(cases),
            candidates=candidates,
        )

    # ── Promote ──────────────────────────────────────────

    def promote_all(
        self,
        report: DistillationReport,
        *,
        overwrite: bool = False,
    ) -> int:
        """Register each candidate as a Skill in the skill library.
        Returns the count successfully registered."""
        lib = self._library()
        if lib is None:
            return 0
        n = 0
        try:
            from core.brain.skill_library import Skill
        except Exception as exc:
            logger.debug("Skill class unavailable: %s", exc)
            return 0
        for cand in report.candidates:
            try:
                lib.register(
                    Skill(
                        name=cand.name,
                        preconditions=dict(cand.signature),
                        description=(
                            f"Auto-distilled from {cand.support} cases "
                            f"(mean score {cand.mean_score:.2f})"
                        ),
                        tags=("distilled",),
                    ),
                    overwrite=overwrite,
                )
                n += 1
            except ValueError:
                # Already registered & overwrite=False — skip silently
                continue
            except Exception as exc:
                logger.debug(
                    "promote %s failed: %s", cand.name, exc,
                )
                continue
        return n

    def stats(self) -> dict[str, Any]:
        cases = self._cases()
        return {
            "case_count": len(cases),
            "library_attached": self._library() is not None,
        }
