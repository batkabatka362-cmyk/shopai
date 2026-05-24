"""Classify each writer module by RISK LEVEL.

The bible's risk model:
  * NEW setup is safe (creating a store, configuring an
    adapter, adding an integration). Operator authorized
    that by connecting the API token.
  * MODIFYING already-approved state is risky (changing
    product status, prices, customer data, order
    cancellation). Needs explicit operator approval at
    each fire.
  * SAIJRUULALT (improvement / enrichment) is safe even
    on already-approved state, because it ADDS information
    without overwriting an operator decision.

The catalog of 49 wired engines mixes all three. Operators
need a clean taxonomy so the autonomous cycle can safely
auto-fire the ``additive`` tier while still requiring
approval for the ``modification`` and ``destructive`` tiers.

Risk levels:
  * ``additive``     -- ADDS tags / metafields / new entities
                        without overwriting operator decisions.
                        Examples: tag products with risk:high,
                        mint NEW gift card, ADD customer tag.
                        Safe for autonomous-cycle auto-fire.
  * ``modification`` -- UPDATES already-set fields on existing
                        entities (price, status, variants).
                        Each fire needs operator approval.
                        Examples: product_lifecycle archives,
                        dynamic_pricing price update.
  * ``destructive``  -- DELETES, CANCELS, or otherwise removes
                        operator-approved state. Cannot be
                        autonomous-fire; operator approves
                        EVERY action and the system requires
                        a second confirm. Reserve for narrow
                        recovery flows.
  * ``unknown``      -- Classifier couldn't determine. Treated
                        as ``modification`` until an explicit
                        ``_WRITEBACK_RISK`` constant is added.

Each writer module may declare its risk via a module-level
constant:

    _WRITEBACK_RISK = "additive"     # or "modification" / "destructive"

Otherwise the AST-based heuristic infers from the
arguments shape:
  - ``"tags": [...]``                       -> additive
  - ``"id": ..., "tags": [...]``            -> additive (tag merge)
  - ``"status": "ARCHIVED"`` or other      -> modification
  - ``"price": ...`` / ``"variants": ...`` -> modification
  - ``SHOPIFY_CREATE_PRODUCT`` / mint codes -> additive
  - ``SHOPIFY_*_DELETE`` / cancel orders   -> destructive
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


_ADDITIVE_HINTS = {
    # Tag writes (always additive)
    "SHOPIFY_TAG_CUSTOMER", "SHOPIFY_TAG_ORDER",
    "SHOPIFY_ADD_TAGS",
    # New entity creation (no operator-approved state to overwrite)
    "SHOPIFY_CREATE_PRODUCT", "SHOPIFY_CREATE_DISCOUNT",
    "SHOPIFY_CREATE_GIFT_CARD", "SHOPIFY_CREATE_PAGE",
    "SHOPIFY_CREATE_COLLECTION", "SHOPIFY_UPLOAD_FILE",
    "SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING",
    # Theme files: store_design pattern writes NEW asset/snippet
    # files only -- never overwrites stock theme files
    "SHOPIFY_UPSERT_THEME_FILES",
}
_MODIFICATION_HINTS = {
    "SHOPIFY_UPDATE_PRODUCT", "SHOPIFY_UPDATE_VARIANT",
    "SHOPIFY_UPDATE_VARIANTS", "SHOPIFY_UPDATE_SHOP_POLICY",
    "SHOPIFY_UPDATE_PAGE", "SHOPIFY_UPDATE_COLLECTION",
}
_DESTRUCTIVE_HINTS = {
    "SHOPIFY_DELETE_PRODUCT", "SHOPIFY_CANCEL_ORDER",
    "SHOPIFY_DELETE_CUSTOMER", "SHOPIFY_DELETE_VARIANT",
    "SHOPIFY_DELETE_PAGE", "SHOPIFY_DELETE_COLLECTION",
}

# When SHOPIFY_UPDATE_PRODUCT is used but the payload is ONLY
# {id, tags: [...]} (tag merge), classify as additive even
# though the underlying mutation is "update". Tag additions
# don't overwrite operator-set fields -- they merge.
_MUTATION_FIELD_NAMES_ADDITIVE = {"tags"}


@dataclass
class WriterRisk:
    engine: str
    writer_file: str  # relative
    risk: str  # "additive" | "modification" | "destructive" | "unknown"
    declared: bool  # True if the file declared _WRITEBACK_RISK
    evidence: list[str] = field(default_factory=list)


@dataclass
class RiskCatalog:
    writers: list[WriterRisk] = field(default_factory=list)
    by_risk: dict[str, list[WriterRisk]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.writers)

    def count(self, risk: str) -> int:
        return len(self.by_risk.get(risk, []))


def classify_writers(engines_dir: str = "engines") -> RiskCatalog:
    """Walk every engines/*/*_applier.py and classify by risk.

    Args:
        engines_dir: Root engines directory.

    Returns:
        Populated :class:`RiskCatalog`.
    """
    root = Path(engines_dir)
    catalog = RiskCatalog()
    if not root.exists() or not root.is_dir():
        return catalog

    seen_engines: set[str] = set()
    for engine_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        engine_name = engine_dir.name
        for applier in sorted(engine_dir.glob("*_applier.py")):
            try:
                source = applier.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, SyntaxError):
                continue
            risk, declared, evidence = _classify(tree, source)
            entry = WriterRisk(
                engine=engine_name,
                writer_file=str(applier).replace("\\", "/"),
                risk=risk,
                declared=declared,
                evidence=evidence,
            )
            catalog.writers.append(entry)
            catalog.by_risk.setdefault(risk, []).append(entry)
            seen_engines.add(engine_name)
        # Also pick up minter/payer files
        for writer in sorted(engine_dir.glob("*_minter.py")):
            try:
                source = writer.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, SyntaxError):
                continue
            risk, declared, evidence = _classify(tree, source)
            entry = WriterRisk(
                engine=engine_name,
                writer_file=str(writer).replace("\\", "/"),
                risk=risk,
                declared=declared,
                evidence=evidence,
            )
            catalog.writers.append(entry)
            catalog.by_risk.setdefault(risk, []).append(entry)
            seen_engines.add(engine_name)
        for writer in sorted(engine_dir.glob("*_payer.py")):
            try:
                source = writer.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, SyntaxError):
                continue
            risk, declared, evidence = _classify(tree, source)
            entry = WriterRisk(
                engine=engine_name,
                writer_file=str(writer).replace("\\", "/"),
                risk=risk,
                declared=declared,
                evidence=evidence,
            )
            catalog.writers.append(entry)
            catalog.by_risk.setdefault(risk, []).append(entry)
            seen_engines.add(engine_name)

    return catalog


def _classify(tree: ast.AST, source: str) -> tuple[str, bool, list[str]]:
    """Return (risk_level, declared_explicitly, evidence_lines)."""
    # First: explicit declaration?
    for node in getattr(tree, "body", []) or []:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "_WRITEBACK_RISK"
            ):
                declared_val = node.value.value
                if declared_val in {
                    "additive", "modification", "destructive",
                }:
                    return (
                        declared_val,
                        True,
                        [f"declared: _WRITEBACK_RISK = {declared_val!r}"],
                    )

    # Otherwise: infer from capability hints.
    capabilities = _extract_capabilities(tree)
    evidence: list[str] = []

    has_destructive = capabilities & _DESTRUCTIVE_HINTS
    if has_destructive:
        evidence.append(f"capability: {sorted(has_destructive)}")
        return ("destructive", False, evidence)

    has_modification = capabilities & _MODIFICATION_HINTS
    has_additive = capabilities & _ADDITIVE_HINTS

    if has_modification:
        # SHOPIFY_UPDATE_PRODUCT used only for tag merges = additive
        if _is_only_tag_merge(tree):
            evidence.append(
                f"capability: {sorted(has_modification)} "
                f"but only writes 'tags' field (tag merge)"
            )
            return ("additive", False, evidence)
        # Check for status/price mutations
        mutations = _extract_mutation_fields(tree)
        if mutations:
            evidence.append(
                f"capability: {sorted(has_modification)}, "
                f"mutations: {sorted(mutations)}"
            )
            return ("modification", False, evidence)
        evidence.append(f"capability: {sorted(has_modification)}")
        return ("modification", False, evidence)

    if has_additive:
        evidence.append(f"capability: {sorted(has_additive)}")
        return ("additive", False, evidence)

    return ("unknown", False, ["no clear capability hint found"])


def _extract_capabilities(tree: ast.AST) -> set[str]:
    """Collect every Capability.SHOPIFY_X / "SHOPIFY_X" referenced."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "Capability"
                and isinstance(node.attr, str)
                and node.attr.startswith("SHOPIFY_")
            ):
                out.add(node.attr)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if (
                node.value.startswith("SHOPIFY_")
                and "_" in node.value[8:]
                and len(node.value) < 60  # avoid log strings
            ):
                out.add(node.value)
    return out


def _extract_mutation_fields(tree: ast.AST) -> set[str]:
    """Find dict-key constants in router.execute payloads that
    indicate modification (not just tag merge).

    Looks for dict expressions with keys like ``status``, ``price``,
    ``variants``, etc.
    """
    mutation_keys = {
        "status", "price", "variants", "compareAtPrice",
        "publishedAt", "publishedScope", "vendor", "title",
        "descriptionHtml", "handle", "productType",
    }
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                if key.value in mutation_keys:
                    out.add(key.value)
    return out


def _is_only_tag_merge(tree: ast.AST) -> bool:
    """True iff every router.execute payload dict in the file
    has keys SUBSET OF {id, tags}."""
    found_any_payload = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys: set[str] = set()
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
        if not keys:
            continue
        # We want only payload dicts; filter to ones with "id"
        # (a Shopify entity identifier) plus other Shopify-write
        # field names.
        if "id" not in keys:
            continue
        found_any_payload = True
        allowed = {"id", "tags"}
        if not keys.issubset(allowed):
            return False
    return found_any_payload
