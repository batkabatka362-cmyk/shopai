"""Capability dataclass + registry singleton + query API.

See ``__init__.py`` for the why and high-level usage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CapabilityKind:
    """Enumeration of capability kinds.

    Plain string constants (not ``enum.Enum``) so the JSON
    serialisation stays human-readable and adding a new kind
    doesn't require migrating enum values.
    """

    # An engine module exposing ``run(input_envelope)``. The
    # core unit of business logic.
    ENGINE = "engine"

    # A writer / applier module that pushes an action to
    # Shopify (or another external surface) and records via
    # Pattern Z. ``apply_X`` functions live here.
    APPLIER = "applier"

    # A generator that builds friendly call-shape dicts from
    # high-level params. Pairs with an applier (e.g.
    # ``generate_policies`` + ``apply_policies``).
    GENERATOR = "generator"

    # A niche-aware seeder that produces starter data
    # (products, collections, ...) for a fresh store.
    SEEDER = "seeder"

    # An orchestrator that chains generators + appliers + side
    # effects (e.g. ``launch_store``).
    ORCHESTRATOR = "orchestrator"

    # An adapter capability bound to the AdapterRouter
    # (Capability enum entries in ``core.adapters.base``).
    ADAPTER = "adapter"

    # An audit module that reads state + reports
    # gaps / silent-failures (e.g. launch_audit, pattern_s).
    AUDIT = "audit"

    # An engine-side hydrator that auto-fetches data from
    # Shopify when caller leaves input empty.
    HYDRATOR = "hydrator"

    # An enrichment module that augments existing data
    # (SEO meta, descriptions, tags).
    ENRICHER = "enricher"


@dataclass
class Capability:
    """A single substrate capability declared in the registry.

    Required fields (``name``, ``kind``, ``description``,
    ``when_to_use``, ``module_path``) earn presence in the
    catalog. Optional fields earn leverage when an LLM planner
    or operator needs to compose / verify.

    ``when_to_use`` is the LLM-readable answer to "if my goal
    involves X, is this relevant?" -- write it as if you were
    explaining the capability to an autonomous agent that has
    never seen the codebase.
    """

    # ── Required ──────────────────────────────────────────
    name: str
    kind: str
    description: str
    when_to_use: str
    module_path: str  # e.g. "engines.store_setup.launch_orchestrator:launch_store"

    # ── Optional metadata ─────────────────────────────────
    # Inputs / outputs are loose dicts so the schema can grow
    # without breaking registrations. Future iterations can
    # tighten this into TypedDicts or jsonschema.
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)

    # Side effects this capability has. Free-form strings so
    # an LLM can reason about them. Examples:
    #   ["creates Shopify discount codes",
    #    "records to MemoryIntel + DataArch via Pattern Z"]
    side_effects: list[str] = field(default_factory=list)

    # Shopify scopes this capability needs (for adapters /
    # appliers).
    scopes_used: list[str] = field(default_factory=list)

    # Audit-check keys this capability closes when it succeeds
    # (links to launch_audit / pattern_X audit modules).
    audit_checks_closed: list[str] = field(default_factory=list)

    # Capabilities this one composes with -- consumers of this
    # capability's output, or chains-of producers feeding it.
    # Used by the planner to build pipelines.
    composes_with: list[str] = field(default_factory=list)

    # A minimal usable example input dict. An LLM imitating
    # this can call the capability without reading the source.
    example_input: dict[str, Any] = field(default_factory=dict)

    # Free-form tags for find() filtering: "launch",
    # "post-launch", "design", "products", "discounts", ...
    tags: list[str] = field(default_factory=list)

    # CLI surface(s) that expose this capability to operators.
    # An LLM planner can use this to suggest a one-liner.
    cli_commands: list[str] = field(default_factory=list)

    # Composition contract: when this capability is a
    # downstream applier of an upstream peer (generator /
    # engine), ``composes_input`` names the kwarg that
    # receives the upstream's output. The multi-step
    # executor reads this + replaces the corresponding
    # suggested_args entry with the prior step's result.
    #
    # Example:
    #   apply_policies.composes_input = "policies"
    #   apply_design.composes_input = "engine_output"
    #
    # Empty string ("") means no piping -- the step runs
    # independently with its example_input or operator-
    # supplied args.
    composes_input: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict.

        Used by ``shopai capabilities --json`` and any future
        consumer (planner context, daily-brief snapshot, ...).
        """
        return {
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "module_path": self.module_path,
            "inputs": dict(self.inputs),
            "outputs": dict(self.outputs),
            "side_effects": list(self.side_effects),
            "scopes_used": list(self.scopes_used),
            "audit_checks_closed": list(self.audit_checks_closed),
            "composes_with": list(self.composes_with),
            "example_input": dict(self.example_input),
            "tags": list(self.tags),
            "cli_commands": list(self.cli_commands),
            "composes_input": self.composes_input,
        }


class _Registry:
    """Module-level singleton holding all registered
    capabilities. Mutable on purpose -- registration happens
    at import time, and tests can ``clear()`` between cases.
    """

    def __init__(self) -> None:
        self._by_name: dict[str, Capability] = {}

    # ── Mutation ──────────────────────────────────────────

    def register(self, cap: Capability) -> None:
        """Add or overwrite a capability by name.

        Idempotent on purpose: a module reloaded by pytest /
        importlib doesn't bloat the registry. Last write wins.
        """
        if not cap.name or not isinstance(cap.name, str):
            raise ValueError(
                "Capability.name is required and must be str"
            )
        self._by_name[cap.name] = cap

    def clear(self) -> None:
        """Drop every registration. Used by test fixtures."""
        self._by_name.clear()

    # ── Read ─────────────────────────────────────────────

    def get(self, name: str) -> Capability | None:
        return self._by_name.get(name)

    def all(self) -> list[Capability]:
        """Stable iteration order (alphabetical by name) so
        callers / tests / LLM context blocks see deterministic
        output."""
        return [self._by_name[k] for k in sorted(self._by_name)]

    def names(self) -> list[str]:
        return sorted(self._by_name)

    def count(self) -> int:
        return len(self._by_name)

    # ── Query ─────────────────────────────────────────────

    def find(
        self,
        *,
        kind: str | None = None,
        tag: str | None = None,
        closes_audit: str | None = None,
        composes_with: str | None = None,
        query: str | None = None,
    ) -> list[Capability]:
        """Filter capabilities by one or more criteria.

        Empty / None filters are skipped (logical AND across
        the supplied ones). ``query`` does substring +
        token-AND match across name + description +
        when_to_use + tags + side_effects.

        Query fallback: when the strict AND match returns
        zero results, fall back to OR-match (any token
        present). This handles long queries like "cash flow
        forecast" where no single capability contains every
        token but several contain SOME tokens. Discovery
        beats silence.

        Returns a list in the stable order from ``all()``.
        """
        results = self.all()
        if kind:
            results = [c for c in results if c.kind == kind]
        if tag:
            tag_l = tag.lower()
            results = [
                c for c in results
                if any(t.lower() == tag_l for t in c.tags)
            ]
        if closes_audit:
            results = [
                c for c in results
                if closes_audit in c.audit_checks_closed
            ]
        if composes_with:
            results = [
                c for c in results
                if composes_with in c.composes_with
            ]
        if query:
            q = query.lower().strip()
            if q:
                # Strict AND first
                strict = [
                    c for c in results
                    if _matches_query(c, q)
                ]
                if strict:
                    return strict
                # Fallback: OR-match. Only fires when
                # strict returned zero.
                results = [
                    c for c in results
                    if _matches_query_any_token(c, q)
                ]
        return results


_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "to", "for", "of", "and", "or",
    "with", "by", "from", "this", "that", "these", "those",
    "is", "be", "do", "in", "on", "at", "as", "it",
})


import re as _re


def _token_in_blob(token: str, blob: str) -> bool:
    """Word-boundary substring match.

    ``token in blob`` would match 'flow' inside 'workflow' --
    a false positive that pollutes the OR-fallback for
    common 4-letter tokens. Word-boundary regex eliminates
    that without losing accurate full-word hits.
    """
    if not token:
        return False
    # Escape regex meta in token. Wrap with \b on both
    # sides. For tokens ending in non-word chars (rare),
    # the \b still works because \b is at word/non-word
    # transitions.
    pattern = r"\b" + _re.escape(token) + r"\b"
    return bool(_re.search(pattern, blob))


def _matches_query(cap: Capability, q: str) -> bool:
    """Match a free-form phrase against the LLM-readable
    fields.

    Two passes for robustness:

      1. **Exact phrase substring** -- "mobile design" hits
         only capabilities mentioning that exact bigram.
      2. **Token AND** -- "launch the store" splits to
         ['launch', 'store'] (stopwords dropped) and matches
         only capabilities whose blob contains BOTH tokens.
         AND-across-tokens is narrower than OR but produces
         a more useful planner-relevant signal: an operator
         saying "design the store for mobile" gets
         store_design_engine specifically, not every entry
         containing "store".

    Single-token queries reduce to a simple substring check
    on that token, which is the right behaviour for short
    phrases like "mobile" or "policies".

    When the registry grows large enough to need semantic
    search, swap this for an embedding lookup behind the
    same call site -- the contract ("free-form phrase ->
    relevant capabilities") doesn't change.
    """
    haystacks = [
        cap.name,
        cap.description,
        cap.when_to_use,
        " ".join(cap.tags),
        " ".join(cap.side_effects),
    ]
    blob = " ".join(haystacks).lower()

    # Exact phrase
    if q in blob:
        return True

    # Token AND with word-boundary match
    tokens = [
        t for t in q.split()
        if len(t) >= 3 and t not in _STOPWORDS
    ]
    if not tokens:
        return False
    return all(_token_in_blob(t, blob) for t in tokens)


def _matches_query_any_token(
    cap: Capability, q: str,
) -> bool:
    """OR-match fallback for ``find()``. Only invoked when
    the strict AND-match returned zero results -- prevents
    silent empty responses for diffuse phrases like
    "cash flow forecast".
    """
    haystacks = [
        cap.name,
        cap.description,
        cap.when_to_use,
        " ".join(cap.tags),
        " ".join(cap.side_effects),
    ]
    blob = " ".join(haystacks).lower()
    tokens = [
        t for t in q.split()
        if len(t) >= 3 and t not in _STOPWORDS
    ]
    if not tokens:
        return False
    return any(_token_in_blob(t, blob) for t in tokens)


# Module-level singleton.
_REGISTRY = _Registry()


def get_registry() -> _Registry:
    """Public accessor for the module-level registry."""
    return _REGISTRY


def register_capability(cap: Capability) -> None:
    """Convenience wrapper for ``get_registry().register(cap)``.

    Designed to be called at module import time:

        from core.capability_registry import (
            Capability, CapabilityKind, register_capability,
        )

        register_capability(Capability(
            name="launch_store",
            kind=CapabilityKind.ORCHESTRATOR,
            ...
        ))
    """
    _REGISTRY.register(cap)
