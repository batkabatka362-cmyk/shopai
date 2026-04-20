"""Relation extractor — pull (subject, verb, object) triples from text.

Owners and engines emit prose that contains *facts*: "Product P1 is a
winner in pet niche", "Customer seg-42 prefers bundle deals". Without
extraction those facts stay as unstructured strings; the knowledge
graph can't link them.

This extractor runs a rule-based pattern set over the input:

  1. Pattern "<S> is/was <O>"                    → (S, "is", O)
  2. Pattern "<S> has/contains <O>"              → (S, "has", O)
  3. Pattern "<S> prefers/likes/chooses <O>"     → (S, "prefers", O)
  4. Pattern "<S> drives/causes <O>"             → (S, "causes", O)
  5. Pattern "<S> kills/terminates <O>"          → (S, "kills", O)

Each rule is registerable; callers can extend with domain patterns.
Deterministic, LLM-free, pure stdlib.

Output ``Relation`` dataclass carries confidence and source_phrase
so downstream knowledge_graph inserts are auditable. Complements
``knowledge_ingest`` (which ingests prose into memory) by producing
*structured triples*.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("memory.relation_extractor")


@dataclass
class Relation:
    subject: str
    verb: str
    obj: str
    confidence: float
    source_phrase: str
    rule_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "verb": self.verb,
            "object": self.obj,
            "confidence": round(self.confidence, 4),
            "source_phrase": self.source_phrase,
            "rule_id": self.rule_id,
        }


@dataclass
class ExtractionRule:
    id: str
    pattern: re.Pattern
    verb: str
    confidence: float = 0.7
    description: str = ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).strip(".,:;!?\"'")


def _compile(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


_DEFAULT_RULES: tuple[ExtractionRule, ...] = (
    ExtractionRule(
        id="is",
        pattern=_compile(
            r"(?P<subject>[A-Za-z0-9_.\- ]{2,64})\s+"
            r"(?:is|are|was|were)\s+"
            r"(?:a\s+|an\s+|the\s+)?"
            r"(?P<object>[A-Za-z0-9_.\- ]{2,64})",
        ),
        verb="is",
        description="Copula relation",
    ),
    ExtractionRule(
        id="has",
        pattern=_compile(
            r"(?P<subject>[A-Za-z0-9_.\- ]{2,64})\s+"
            r"(?:has|have|had|contains?)\s+"
            r"(?P<object>[A-Za-z0-9_.\- ]{2,64})",
        ),
        verb="has",
        description="Composition relation",
    ),
    ExtractionRule(
        id="prefers",
        pattern=_compile(
            r"(?P<subject>[A-Za-z0-9_.\- ]{2,64})\s+"
            r"(?:prefers?|likes?|chooses?|favou?rs?)\s+"
            r"(?P<object>[A-Za-z0-9_.\- ]{2,64})",
        ),
        verb="prefers",
        description="Preference relation",
    ),
    ExtractionRule(
        id="causes",
        pattern=_compile(
            r"(?P<subject>[A-Za-z0-9_.\- ]{2,64})\s+"
            r"(?:drives?|causes?|leads?\s+to|triggers?)\s+"
            r"(?P<object>[A-Za-z0-9_.\- ]{2,64})",
        ),
        verb="causes",
        description="Causal relation",
    ),
    ExtractionRule(
        id="kills",
        pattern=_compile(
            r"(?P<subject>[A-Za-z0-9_.\- ]{2,64})\s+"
            r"(?:kills?|pauses?|terminates?|stops?)\s+"
            r"(?P<object>[A-Za-z0-9_.\- ]{2,64})",
        ),
        verb="kills",
        description="Kill relation",
    ),
)


class RelationExtractor:
    def __init__(
        self,
        *,
        rules: Iterable[ExtractionRule] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._rules = list(
            rules if rules is not None else _DEFAULT_RULES,
        )

    def register_rule(self, rule: ExtractionRule) -> None:
        with self._lock:
            self._rules.append(rule)

    def unregister_rule(self, rule_id: str) -> bool:
        with self._lock:
            before = len(self._rules)
            self._rules = [
                r for r in self._rules if r.id != rule_id
            ]
            return len(self._rules) < before

    # ── Extract ──────────────────────────────────────────

    def extract(self, text: str) -> list[Relation]:
        if not text:
            return []
        out: list[Relation] = []
        with self._lock:
            rules = list(self._rules)
        seen: set[tuple[str, str, str]] = set()
        # Iterate sentences to keep subject/object small
        for sentence in re.split(r"[.!?]+", text):
            sentence = sentence.strip()
            if not sentence:
                continue
            for rule in rules:
                for match in rule.pattern.finditer(sentence):
                    subj = _clean(match.group("subject"))
                    obj = _clean(match.group("object"))
                    if not subj or not obj:
                        continue
                    key = (
                        subj.lower(), rule.verb, obj.lower(),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(Relation(
                        subject=subj,
                        verb=rule.verb,
                        obj=obj,
                        confidence=rule.confidence,
                        source_phrase=sentence,
                        rule_id=rule.id,
                    ))
        return out

    def extract_batch(
        self, texts: Iterable[str],
    ) -> list[Relation]:
        out: list[Relation] = []
        for t in texts:
            out.extend(self.extract(t))
        return out

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "rules": len(self._rules),
                "rule_ids": sorted(
                    r.id for r in self._rules
                ),
            }
