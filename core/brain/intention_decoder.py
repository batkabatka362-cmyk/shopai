"""Intention decoder — terse owner utterance → full intent tree.

goal_compiler compiles an explicit request into a plan. dialog_memory
extracts a flat intent tag per turn. intention_decoder goes a layer
deeper: given a terse owner message like *"kill bad audio ads, also
scale the winner"*, it produces a tree of sub-intents with slots:

    [
      {
        "intent": "kill",
        "targets": ["audio.ads.bad"],
        "slots": {"niche": "audio", "quality": "bad"},
        "confidence": 0.9,
      },
      {
        "intent": "scale",
        "targets": ["winner"],
        "slots": {"subject": "winner"},
        "confidence": 0.7,
      }
    ]

Approach: split the utterance on conjunctions (+ comma + Mongolian
connectors), run each clause through the same intent+slot extractor
dialog_memory already uses, and compute a naive confidence:

    conf = 0.5 + 0.4 × (1 if verb matched) + 0.1 × (1 if slot matched)

Pure stdlib. Deterministic. English + Mongolian-transliteration aware.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger

try:
    from core.brain.dialog_memory import (
        extract_entities as _extract_entities_dm,
        extract_intent as _extract_intent_dm,
    )
except Exception:  # pragma: no cover — dialog_memory always present in prod
    def _extract_intent_dm(_text: str) -> str:
        return "unknown"

    def _extract_entities_dm(_text: str) -> dict[str, Any]:
        return {}


logger = get_logger("brain.intention_decoder")


# Conjunctions that split an utterance into parallel intents. Order
# matters — multi-word matches first.
_SPLIT_RE = re.compile(
    r"\s*(?:,\s+also\b|\band\s+also\b|\s+also\b|;|,\s+then\b|"
    r"\s+then\b|\s+,\s*|\s+;\s*|\s+bas\b|\s+dar\s)",
    re.IGNORECASE,
)


_PRONOUN = re.compile(
    r"\b(it|them|those|that|this|tend|ene|ter|tedge)\b",
    re.IGNORECASE,
)


@dataclass
class SubIntent:
    intent: str
    targets: list[str] = field(default_factory=list)
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    raw: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "targets": list(self.targets),
            "slots": dict(self.slots),
            "confidence": round(self.confidence, 4),
            "raw": self.raw,
        }


@dataclass
class IntentTree:
    raw: str
    sub_intents: list[SubIntent] = field(default_factory=list)
    ambiguous: bool = False

    @property
    def best_intent(self) -> SubIntent | None:
        if not self.sub_intents:
            return None
        return max(self.sub_intents, key=lambda s: s.confidence)

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "sub_intents": [s.as_dict() for s in self.sub_intents],
            "ambiguous": self.ambiguous,
            "best": (
                self.best_intent.as_dict() if self.best_intent else None
            ),
        }


# ── Target extraction ─────────────────────────────────────

_TARGET_TOKENS = re.compile(
    r"(audio|fashion|home|beauty|tech|tools)[\.\w]*"
    r"|\b(winner|loser|hero|bad|good)\b"
    r"|sku[-_:#]?\s*\w+"
    r"|p\d{2,}",
    re.IGNORECASE,
)


def _extract_targets(text: str) -> list[str]:
    found: list[str] = []
    for m in _TARGET_TOKENS.finditer(text or ""):
        token = m.group(0).lower()
        if token not in found:
            found.append(token)
    return found


def _confidence(
    intent: str, slots: dict[str, Any], text: str,
) -> float:
    c = 0.5
    if intent != "unknown":
        c += 0.4
    if slots:
        c += 0.05 * min(2, len(slots))
    # Pronouns without prior context lower confidence.
    if _PRONOUN.search(text or ""):
        c -= 0.1
    return max(0.0, min(1.0, c))


# ── Split helpers ─────────────────────────────────────────

def _split_clauses(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    # Remove trailing punctuation that isn't meaningful.
    cleaned = text.rstrip(".?! ").strip()
    parts = _SPLIT_RE.split(cleaned)
    return [p.strip() for p in parts if p and p.strip()]


# ── Decode ────────────────────────────────────────────────

def decode(text: str) -> IntentTree:
    raw = (text or "").strip()
    tree = IntentTree(raw=raw)
    clauses = _split_clauses(raw)
    if not clauses:
        return tree

    for clause in clauses:
        intent = _extract_intent_dm(clause)
        slots = _extract_entities_dm(clause)
        targets = _extract_targets(clause)
        conf = _confidence(intent, slots, clause)
        tree.sub_intents.append(SubIntent(
            intent=intent,
            targets=targets,
            slots=slots,
            confidence=conf,
            raw=clause,
        ))

    # Ambiguity: more than one sub-intent with confidence ≥ 0.5 and
    # distinct canonical intents.
    high_conf = [
        si for si in tree.sub_intents if si.confidence >= 0.5
    ]
    distinct_intents = {si.intent for si in high_conf}
    tree.ambiguous = len(distinct_intents) > 1
    # Also mark ambiguous when a single sub-intent is "unknown" AND
    # confidence < 0.6 (we really aren't sure what was asked).
    if len(tree.sub_intents) == 1:
        only = tree.sub_intents[0]
        if only.intent == "unknown" and only.confidence < 0.6:
            tree.ambiguous = True
    return tree


# ── Helpers exposed for callers ────────────────────────────

def decode_many(
    texts: Iterable[str],
) -> list[IntentTree]:
    out: list[IntentTree] = []
    for t in texts:
        try:
            out.append(decode(str(t or "")))
        except Exception as exc:
            logger.debug("decode skipped: %s", exc)
    return out
