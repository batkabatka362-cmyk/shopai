"""Analogy mapper — transfer a past playbook onto a new situation.

case_based_reasoner uses *feature* similarity. Analogy goes one level
deeper: it matches the *relational structure* of the situation. Two
launches look analogous not because niche or price match but because
the *shape* does — "cheap impulse-buy in crowded market" analogous to
another "cheap impulse-buy in crowded market".

A structural signature is a set of relations over named roles:

    {
        "roles":     {"product": "..."},
        "relations": [
            ("product", "in_category", "audio"),
            ("product", "price_tier", "cheap"),
            ("market", "saturation", "high"),
        ],
    }

map(query, template) returns a score 0..1 computed by how many template
relations the query satisfies after an optimal role-binding. The binding
itself comes back so the caller can plug concrete query-side role
values into the template's recipe.

Usage:

    templates = [Template("cheap_impulse",
                          roles=("product", "market"),
                          relations=[...],
                          recipe={"action": "scale_fast"})]

    best = mapper.best_match(query_situation)
    if best and best.score > 0.7:
        execute(best.template.recipe, bindings=best.bindings)

Pure stdlib. Deterministic. No LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations
from typing import Any


Relation = tuple[str, str, Any]   # (role, predicate, value)


@dataclass
class Template:
    name: str
    roles: tuple[str, ...]
    relations: list[Relation] = field(default_factory=list)
    recipe: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "roles": list(self.roles),
            "relations": [list(r) for r in self.relations],
            "recipe": self.recipe,
            "tags": list(self.tags),
        }


@dataclass
class Situation:
    """A bag of relations observed about the current world. Roles
    are the canonical entity names; each relation asserts that a role
    has a given predicate-value."""
    roles: tuple[str, ...]
    relations: list[Relation] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "roles": list(self.roles),
            "relations": [list(r) for r in self.relations],
        }


@dataclass
class Match:
    template: Template
    score: float
    bindings: dict[str, str]         # template_role → situation_role
    matched: int
    total: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "template": self.template.name,
            "score": round(self.score, 4),
            "bindings": dict(self.bindings),
            "matched": self.matched,
            "total": self.total,
        }


# ── Scoring ───────────────────────────────────────────────

def _score_binding(
    template: Template,
    situation: Situation,
    binding: dict[str, str],
) -> int:
    """Count how many template relations are satisfied by substituting
    template roles with the situation-side roles from the binding."""
    sit_rel_set = {
        (role, pred, value)
        for role, pred, value in situation.relations
    }
    hits = 0
    for role, pred, value in template.relations:
        mapped = binding.get(role, role)
        if (mapped, pred, value) in sit_rel_set:
            hits += 1
    return hits


def map_one(template: Template, situation: Situation) -> Match:
    """Optimal role binding by brute-force permutation (template roles
    are small — typically 2-3, so exhaustive search is fine)."""
    total = max(1, len(template.relations))
    if not template.roles:
        hits = _score_binding(template, situation, {})
        return Match(
            template=template, score=hits / total,
            bindings={}, matched=hits, total=total,
        )
    # Generate permutations of situation roles of length len(template.roles)
    sit_roles = list(situation.roles)
    if len(sit_roles) < len(template.roles):
        # Pad with template roles themselves so unbound roles still
        # match by name if the caller happens to use the same label.
        sit_roles = sit_roles + [r for r in template.roles
                                  if r not in sit_roles]
    best_hits = -1
    best_binding: dict[str, str] = {}
    for perm in permutations(sit_roles, len(template.roles)):
        binding = dict(zip(template.roles, perm))
        hits = _score_binding(template, situation, binding)
        if hits > best_hits:
            best_hits = hits
            best_binding = binding
    return Match(
        template=template, score=best_hits / total,
        bindings=best_binding,
        matched=best_hits, total=total,
    )


# ── Mapper ────────────────────────────────────────────────

class AnalogyMapper:
    def __init__(self) -> None:
        self._templates: dict[str, Template] = {}

    def register(self, template: Template) -> None:
        if not template.name:
            raise ValueError("template.name required")
        if template.name in self._templates:
            raise ValueError(
                f"template {template.name!r} already registered",
            )
        self._templates[template.name] = template

    def unregister(self, name: str) -> bool:
        return self._templates.pop(name, None) is not None

    def templates(self) -> list[Template]:
        return list(self._templates.values())

    def match_all(
        self, situation: Situation,
    ) -> list[Match]:
        matches = [
            map_one(t, situation)
            for t in self._templates.values()
        ]
        matches.sort(key=lambda m: -m.score)
        return matches

    def best_match(
        self,
        situation: Situation,
        *,
        min_score: float = 0.5,
    ) -> Match | None:
        matches = self.match_all(situation)
        if not matches:
            return None
        top = matches[0]
        return top if top.score >= min_score else None
