"""Skill transfer — port a learned skill from one context to another.

multi_store_federator (v27-D4) pools rule-level observations across
stores. skill_transfer goes a level higher: given a skill that works
well in store/niche A, should it work in B? And with what confidence
should we try it?

Approach:

  1. Each skill carries a ``learned_context`` fingerprint
     (key=value pairs capturing the niche/trait/environment where
     it was learned).
  2. A ``target_context`` is provided at query time.
  3. Context similarity (Jaccard on key=value pairs, same as
     federator) acts as the transfer confidence multiplier.
  4. An optional ``floor_similarity`` below which we refuse to
     transfer at all (the contexts are too different).

The module is stateful only insofar as it holds a registry of
skills + their learned contexts. Actual application is delegated —
this module just scores and recommends.

Pure stdlib. Deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.skill_transfer")


@dataclass
class TransferableSkill:
    name: str
    learned_context: dict[str, Any]
    original_win_rate: float
    uses: int = 0
    description: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("TransferableSkill.name required")
        if not 0 <= self.original_win_rate <= 1:
            raise ValueError("original_win_rate must be 0..1")
        if self.uses < 0:
            raise ValueError("uses must be ≥ 0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "learned_context": dict(self.learned_context),
            "original_win_rate": round(self.original_win_rate, 4),
            "uses": self.uses,
            "description": self.description,
            "tags": list(self.tags),
        }


@dataclass
class TransferRecommendation:
    skill: TransferableSkill
    similarity: float
    transfer_confidence: float    # original_win_rate × similarity
    verdict: str                  # "strong" | "moderate" | "weak" | "refuse"
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill.as_dict(),
            "similarity": round(self.similarity, 4),
            "transfer_confidence": round(
                self.transfer_confidence, 4,
            ),
            "verdict": self.verdict,
            "notes": list(self.notes),
        }


# ── Similarity ───────────────────────────────────────────

def _trait_similarity(
    a: dict[str, Any], b: dict[str, Any],
) -> float:
    if not a or not b:
        return 0.0
    a_pairs = {(k, str(v)) for k, v in a.items()}
    b_pairs = {(k, str(v)) for k, v in b.items()}
    union = a_pairs | b_pairs
    if not union:
        return 0.0
    return len(a_pairs & b_pairs) / len(union)


class SkillTransfer:
    def __init__(
        self,
        *,
        floor_similarity: float = 0.2,
        strong_threshold: float = 0.6,
        moderate_threshold: float = 0.3,
    ) -> None:
        if not 0 <= floor_similarity <= 1:
            raise ValueError("floor_similarity must be 0..1")
        if not 0 <= moderate_threshold <= strong_threshold <= 1:
            raise ValueError(
                "thresholds must satisfy "
                "0 ≤ moderate ≤ strong ≤ 1",
            )
        self._floor = float(floor_similarity)
        self._strong = float(strong_threshold)
        self._moderate = float(moderate_threshold)
        self._skills: dict[str, TransferableSkill] = {}

    # ── Registration ─────────────────────────────────────

    def register(
        self, skill: TransferableSkill, overwrite: bool = False,
    ) -> None:
        if skill.name in self._skills and not overwrite:
            raise ValueError(
                f"skill {skill.name!r} already registered",
            )
        self._skills[skill.name] = skill

    def unregister(self, name: str) -> bool:
        return self._skills.pop(name, None) is not None

    def skills(self) -> list[TransferableSkill]:
        return list(self._skills.values())

    # ── Transfer ─────────────────────────────────────────

    def evaluate(
        self,
        target_context: dict[str, Any],
        *,
        tags: Iterable[str] = (),
    ) -> list[TransferRecommendation]:
        tag_set = {str(t) for t in tags if t}
        out: list[TransferRecommendation] = []
        for sk in self._skills.values():
            if tag_set and not tag_set.issubset(set(sk.tags)):
                continue
            sim = _trait_similarity(sk.learned_context, target_context)
            tc = sk.original_win_rate * sim
            notes: list[str] = []
            if sim < self._floor:
                verdict = "refuse"
                notes.append(
                    f"similarity {sim:.2f} below floor "
                    f"{self._floor:.2f}",
                )
            elif tc >= self._strong:
                verdict = "strong"
            elif tc >= self._moderate:
                verdict = "moderate"
            else:
                verdict = "weak"
            out.append(TransferRecommendation(
                skill=sk,
                similarity=sim,
                transfer_confidence=tc,
                verdict=verdict,
                notes=notes,
            ))
        out.sort(key=lambda r: -r.transfer_confidence)
        return out

    def best(
        self,
        target_context: dict[str, Any],
        *,
        tags: Iterable[str] = (),
    ) -> TransferRecommendation | None:
        ranked = self.evaluate(target_context, tags=tags)
        # Best non-refused
        for r in ranked:
            if r.verdict != "refuse":
                return r
        return None

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "skills": len(self._skills),
            "floor_similarity": self._floor,
            "strong_threshold": self._strong,
            "moderate_threshold": self._moderate,
        }


# ── Convenience helpers ───────────────────────────────────

def transfer_from_federator(
    federator: Any,
    target_store: str,
) -> list[TransferRecommendation]:
    """Adapter: given a multi_store_federator + target store id,
    pull the federator's top rules and evaluate their transferability.
    federator is typed as Any to avoid a hard import dependency."""
    try:
        best = federator.best_rules_for(target_store, top_n=10)
    except Exception as exc:
        logger.debug("federator.best_rules_for failed: %s", exc)
        return []
    out: list[TransferRecommendation] = []
    target_store_spec = None
    try:
        for s in federator.stores():
            if s.store_id == target_store:
                target_store_spec = s
                break
    except Exception:
        target_store_spec = None
    if target_store_spec is None:
        return []
    target_traits = target_store_spec.traits or {}
    for report in best:
        # Federator's report already carries the target score.
        # Wrap it as a lightweight TransferableSkill for uniform output.
        sk = TransferableSkill(
            name=report.rule_id,
            learned_context=target_traits,
            original_win_rate=max(0.0, min(1.0, report.federated_score)),
            uses=sum(c.get("uses", 0) for c in report.contributors),
        )
        # Similarity here is 1.0 because federator already weighted
        # by similarity in its score — surface that as context.
        out.append(TransferRecommendation(
            skill=sk,
            similarity=1.0,
            transfer_confidence=sk.original_win_rate,
            verdict=(
                "strong" if sk.original_win_rate >= 0.6
                else "moderate" if sk.original_win_rate >= 0.3
                else "weak"
            ),
            notes=[
                "imported from multi_store_federator",
            ],
        ))
    return out
