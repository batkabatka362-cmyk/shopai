"""Auto tagger — rule-based tagging of products / orders / customers.

The brain cross-references by tag constantly (niche, price_band,
tier), but Shopify products arrive with bare titles and owner
shorthand. Manual tagging is tedious and inconsistent.

AutoTagger applies a prioritised ruleset to a payload and emits
the union of matched tags. Rules are declarative:

  Rule(
      name="premium",
      match={"price": {"gt": 80}},
      tags=("premium", "high-margin"),
  )

Match operators: exact value, list of acceptable values, {gt,
ge, lt, le} numeric ranges, regex via {regex: "..."} on any
string field, contains via {contains: "..."} for substring match.

APIs:

  register(Rule) / register_many(rules)
  tag(payload) → TagResult(tags_set, matched_rules)
  train_from_examples(examples)  → derive rules from labeled data
      (emits high-precision rules when a tag co-occurs with a single
      distinguishing feature above min_support)
  stats()

Zero LLM. Pure Python. Deterministic. Integrates cleanly with
ontology (v7-D5) — tags can become predicates.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Rule:
    name: str
    match: dict[str, Any]
    tags: tuple[str, ...]
    priority: int = 0
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "match": self.match,
            "tags": list(self.tags),
            "priority": self.priority,
            "description": self.description,
        }


@dataclass
class TagResult:
    tags: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tags": list(self.tags),
            "matched_rules": list(self.matched_rules),
        }


# ── Matcher ────────────────────────────────────────────────

def _matches(expected: Any, observed: Any) -> bool:
    """Return True iff observed satisfies the expected predicate."""
    if isinstance(expected, dict):
        for k, v in expected.items():
            if k == "gt":
                try:
                    if not (float(observed) > float(v)):
                        return False
                except (TypeError, ValueError):
                    return False
            elif k == "ge":
                try:
                    if not (float(observed) >= float(v)):
                        return False
                except (TypeError, ValueError):
                    return False
            elif k == "lt":
                try:
                    if not (float(observed) < float(v)):
                        return False
                except (TypeError, ValueError):
                    return False
            elif k == "le":
                try:
                    if not (float(observed) <= float(v)):
                        return False
                except (TypeError, ValueError):
                    return False
            elif k == "regex":
                if not isinstance(observed, str):
                    return False
                try:
                    if not re.search(str(v), observed, re.IGNORECASE):
                        return False
                except re.error:
                    return False
            elif k == "contains":
                hay = (observed if isinstance(observed, str)
                        else str(observed))
                if str(v).lower() not in hay.lower():
                    return False
            else:
                return False
        return True
    if isinstance(expected, list):
        return observed in expected
    return observed == expected


def _rule_matches(rule: Rule, payload: dict[str, Any]) -> bool:
    for field_name, predicate in rule.match.items():
        if field_name not in payload:
            return False
        if not _matches(predicate, payload[field_name]):
            return False
    return True


# ── Tagger ─────────────────────────────────────────────────

class AutoTagger:
    def __init__(self) -> None:
        self._rules: list[Rule] = []

    def register(self, rule: Rule) -> None:
        if not rule.name:
            raise ValueError("rule name required")
        if not rule.tags:
            raise ValueError("rule must emit at least one tag")
        # Replace by name
        self._rules = [
            r for r in self._rules if r.name != rule.name
        ] + [rule]
        self._rules.sort(key=lambda r: -r.priority)

    def register_many(self, rules: Iterable[Rule]) -> None:
        for r in rules:
            self.register(r)

    def deregister(self, name: str) -> bool:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before

    def rules(self) -> list[Rule]:
        return list(self._rules)

    # ── Tagging ────────────────────────────────────────────

    def tag(self, payload: dict[str, Any]) -> TagResult:
        tags: set[str] = set()
        matched: list[str] = []
        for rule in self._rules:
            if _rule_matches(rule, payload):
                tags.update(rule.tags)
                matched.append(rule.name)
        return TagResult(
            tags=sorted(tags),
            matched_rules=matched,
        )

    # ── Learning from examples ─────────────────────────────

    def train_from_examples(
        self,
        examples: Iterable[dict[str, Any]],
        *,
        min_support: int = 5,
        min_precision: float = 0.9,
    ) -> list[Rule]:
        """Each example is ``{"features": {...}, "tags": [...]}``.
        For every (feature, value, tag) co-occurrence with support
        ≥ min_support AND precision ≥ min_precision, emit a rule.

        Returns the list of newly registered rules."""
        examples = list(examples)
        if not examples:
            return []
        # Count (feature, value, tag) co-occurrences
        feat_val_tag: dict[tuple[str, Any, str], int] = defaultdict(int)
        feat_val_total: dict[tuple[str, Any], int] = defaultdict(int)
        for ex in examples:
            feats = ex.get("features", {})
            tags = ex.get("tags", []) or []
            for f, v in feats.items():
                feat_val_total[(f, _hashable(v))] += 1
                for t in tags:
                    feat_val_tag[(f, _hashable(v), str(t))] += 1
        new_rules: list[Rule] = []
        for (f, v, t), count in feat_val_tag.items():
            if count < min_support:
                continue
            total = feat_val_total.get((f, v), 0)
            if total <= 0:
                continue
            precision = count / total
            if precision < min_precision:
                continue
            rule_name = f"learned:{f}={v}->{t}"
            rule = Rule(
                name=rule_name,
                match={f: v},
                tags=(str(t),),
                priority=0,
                description=(f"support={count} precision="
                              f"{precision:.2f}"),
            )
            self.register(rule)
            new_rules.append(rule)
        return new_rules

    # ── Stats ──────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "rule_count": len(self._rules),
            "rule_names": [r.name for r in self._rules],
        }


def _hashable(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted(v.items()))
    return v
