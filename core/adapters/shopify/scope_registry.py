"""Aggregator over the Shopify adapter OAuth scope manifest.

Every concrete Shopify adapter declares the OAuth scopes it needs
via the ``required_scopes`` class attribute on
:class:`ShopifyBaseAdapter` (extends the BaseAdapter contract).
This module aggregates those declarations across the entire
adapter bootstrap so an operator can answer:

  * "Which scopes does this app need to install on a new
    merchant?" — union via :func:`all_required_scopes`.
  * "Which adapters need this specific scope?" — reverse index
    via :func:`scopes_by_adapter`.
  * "Which adapters haven't declared scopes yet?" — gap report
    via :func:`undeclared_adapters`.

Operators previously had to read every adapter file's docstring
to find scope hints. Now ``shopai shopify scopes`` answers the
install-manifest question in one command.

Scope hygiene matters because:
  * Over-requesting (declaring scopes the app doesn't actually
    use) makes merchants nervous and Shopify's review team flag
    it.
  * Under-requesting (missing a scope an adapter actually needs)
    causes the adapter to fail with ``ACCESS_DENIED`` at the
    first live call — silent until production.

The registry can't infer scopes from API calls automatically
(Shopify's docs map GraphQL fields to scopes via human-readable
prose), so each adapter must declare them explicitly. The
``undeclared_adapters`` report surfaces wireup gaps so the
manifest gets filled in over time.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.adapters.shopify._base import ShopifyBaseAdapter
from core.adapters.shopify.bootstrap import _SHOPIFY_ADAPTER_CLASSES


@dataclass(frozen=True)
class ScopeManifest:
    """Aggregated scope manifest across registered adapters.

    ``scope_independent_adapters`` lists adapters that have
    explicitly declared they need no extra OAuth scope (e.g.
    app-level features or context-dependent surfaces). They
    appear in ``by_adapter`` with an empty list, but NOT in
    ``undeclared_adapters`` — distinguishing "intentionally
    empty" from "rollout gap".
    """

    all_scopes: frozenset[str]
    by_scope: dict[str, list[str]]
    by_adapter: dict[str, list[str]]
    undeclared_adapters: list[str]
    scope_independent_adapters: list[str]
    total_adapters: int


def collect_manifest(
    adapter_classes: tuple = _SHOPIFY_ADAPTER_CLASSES,
) -> ScopeManifest:
    """Walk every registered Shopify adapter and aggregate the
    OAuth scope manifest.

    Tests can inject ``adapter_classes`` to scope the audit to a
    subset. Production callers leave the default.
    """
    all_scopes: set[str] = set()
    by_scope: dict[str, set[str]] = {}
    by_adapter: dict[str, list[str]] = {}
    undeclared: list[str] = []
    independent: list[str] = []

    for cls in adapter_classes:
        if not issubclass(cls, ShopifyBaseAdapter):
            continue
        # Use the class-level attribute directly — avoids
        # constructing the adapter (which can require credentials).
        scopes = getattr(cls, "required_scopes", frozenset())
        # Sentinel for adapters that legitimately need no extra
        # OAuth scope (app-level features, or context-dependent
        # surfaces like bulk and generic_tags). When set, the
        # registry treats the adapter as "declared, no scopes
        # needed" — surfacing it as a known wireup rather than a
        # rollout gap.
        scope_independent = bool(
            getattr(cls, "scope_independent", False),
        )
        adapter_name = _adapter_registry_name(cls)
        if not scopes and not scope_independent:
            undeclared.append(adapter_name)
            by_adapter[adapter_name] = []
            continue
        if scope_independent:
            independent.append(adapter_name)
        scope_list = sorted(scopes)
        by_adapter[adapter_name] = scope_list
        for scope in scopes:
            all_scopes.add(scope)
            by_scope.setdefault(scope, set()).add(adapter_name)

    return ScopeManifest(
        all_scopes=frozenset(all_scopes),
        by_scope={
            s: sorted(adapters)
            for s, adapters in by_scope.items()
        },
        by_adapter=by_adapter,
        undeclared_adapters=sorted(undeclared),
        scope_independent_adapters=sorted(independent),
        total_adapters=len(adapter_classes),
    )


def all_required_scopes() -> frozenset[str]:
    """Flat union of every OAuth scope any adapter needs."""
    return collect_manifest().all_scopes


def scopes_by_adapter() -> dict[str, list[str]]:
    """``{adapter_name: [scopes...]}`` — per-adapter declarations
    sorted alphabetically. Adapters without declared scopes return
    empty list."""
    return collect_manifest().by_adapter


def undeclared_adapters() -> list[str]:
    """Adapters that haven't wired ``required_scopes`` yet —
    the gap list for the scope-coverage rollout."""
    return collect_manifest().undeclared_adapters


def _adapter_registry_name(cls: type) -> str:
    """Resolve the registry key — ``cls.name`` if set on the
    class, else the class name itself. Used by the manifest for
    consistent identification."""
    name = getattr(cls, "name", "")
    if isinstance(name, str) and name:
        return name
    return cls.__name__
