"""Catalog every Shopify tag written by a Phase 7 wireup.

Operators routinely ask "what tags can I filter the catalog by?".
Until this module, the answer required grep-diving 17 different
``*_applier.py`` files. Now ``catalog_tags()`` returns a single
unified list.

The catalog is AST-derived (we walk every ``engines/*/``
``*_applier.py`` file and collect tag-namespace string literals)
so it stays accurate as wireups are added/removed -- no manual
list to keep in sync.

Tag format convention (every Phase 7 applier follows it):

  ``namespace:value`` -- e.g. ``risk:high``, ``cohort:2026-05``,
  ``audience:high_value``, ``profit:high_roi``.

Pattern: lowercase alphanumeric + underscores on each side of
ONE colon. Excludes literals that incidentally look tag-shaped
but aren't tags (e.g. log-level codes).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TagEntry:
    tag: str
    engine: str
    applier_file: str  # relative path
    capability: str    # SHOPIFY_UPDATE_PRODUCT etc., best-effort
    target: str        # "product" / "customer" / "order" / "unknown"


@dataclass
class TagCatalog:
    entries: list[TagEntry] = field(default_factory=list)
    engines_scanned: int = 0
    by_namespace: dict[str, list[TagEntry]] = field(default_factory=dict)
    by_target: dict[str, list[TagEntry]] = field(default_factory=dict)

    @property
    def total_tags(self) -> int:
        return len(self.entries)

    @property
    def total_namespaces(self) -> int:
        return len(self.by_namespace)


# Tag-namespace literal pattern: word:word (colon convention)
# OR word-word-... (dash convention used by customer_segmentation
# for shopai-segment-{slug}). Excludes URLs (no ://), excludes
# capability constants (which are all-caps).
_TAG_PATTERN = re.compile(r"^[a-z][a-z0-9_]*:[a-z0-9_]+$")
# Permissive dash-prefix pattern for _TAG_PREFIX = "shopai-segment-"
# style constants (the trailing dash signals dynamic suffix).
_TAG_PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*-$")
# Full dash-style tag pattern for _TAG_X = "shopai-return-approved"
# style. Requires 2+ dashes so we don't match "https-only" or
# single-word-dash legitimate non-tags.
_TAG_DASH_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(-[a-z0-9_]+){2,}$"
)

# Map SHOPIFY_X capability to the entity it touches.
_CAPABILITY_TO_TARGET = {
    "SHOPIFY_UPDATE_PRODUCT": "product",
    "SHOPIFY_CREATE_PRODUCT": "product",
    "SHOPIFY_TAG_CUSTOMER": "customer",
    "SHOPIFY_TAG_ORDER": "order",
}


def catalog_tags(engines_dir: str = "engines") -> TagCatalog:
    """Walk every engines/*/*_applier.py file and build the catalog.

    Includes ``tag_applier.py`` (the canonical name) AND any
    other ``*_applier.py`` (e.g. ``customer_applier.py`` in
    customer_segmentation, ``winner_applier.py`` in
    product_research). Excludes minters/payers which don't
    write tags.

    Args:
        engines_dir: Root engines directory (default ``engines``).

    Returns:
        Populated :class:`TagCatalog`.
    """
    root = Path(engines_dir)
    catalog = TagCatalog()
    if not root.exists() or not root.is_dir():
        return catalog

    applier_paths: list[Path] = []
    for engine_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for path in sorted(engine_dir.glob("*_applier.py")):
            applier_paths.append(path)

    seen_engines: set[str] = set()
    for applier_path in applier_paths:
        engine_name = applier_path.parent.name
        # Count each engine ONCE even if it has multiple appliers
        if engine_name not in seen_engines:
            catalog.engines_scanned += 1
            seen_engines.add(engine_name)
        try:
            source = applier_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue

        capability = _extract_capability(tree)
        target = _CAPABILITY_TO_TARGET.get(capability, "unknown")
        tags = _extract_tag_literals(tree)

        for tag in sorted(tags):
            entry = TagEntry(
                tag=tag,
                engine=engine_name,
                applier_file=str(applier_path).replace("\\", "/"),
                capability=capability,
                target=target,
            )
            catalog.entries.append(entry)
            namespace = _tag_namespace(tag)
            catalog.by_namespace.setdefault(namespace, []).append(entry)
            catalog.by_target.setdefault(target, []).append(entry)

    return catalog


def _tag_namespace(tag: str) -> str:
    """Extract the namespace from a tag literal.

    Supports two Shopify-tag conventions:
      * ``namespace:value`` -- prefix before the colon
      * ``namespace-value`` -- prefix before the LAST dash
        (concrete tag, e.g. ``shopai-return-approved`` -> ns
        ``shopai-return``)
      * ``namespace-*`` -- prefix as-is, * marker stripped
        (dynamic tag, e.g. ``shopai-segment-*`` -> ns
        ``shopai-segment``)
    """
    if ":" in tag:
        return tag.split(":", 1)[0]
    if "-" not in tag:
        return tag
    if tag.endswith("*"):
        # Dynamic: strip the trailing "-*" or "*" and keep the rest
        clean = tag[:-1].rstrip("-")
        return clean
    # Concrete: strip the final segment to get the namespace
    return tag.rsplit("-", 1)[0]


def _extract_capability(tree: ast.AST) -> str:
    """Find the FIRST SHOPIFY_X capability the applier references."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "Capability"
                and isinstance(node.attr, str)
                and node.attr.startswith("SHOPIFY_")
            ):
                return node.attr
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("SHOPIFY_") and "_" in node.value[8:]:
                # capability="SHOPIFY_UPDATE_PRODUCT" string form
                return node.value
    return "unknown"


def _extract_tag_literals(tree: ast.AST) -> set[str]:
    """Collect tag literals wired to a Shopify tag write.

    Detection priority:
      1. Module-level ``_FOO_TAG = "ns:value"`` assignments.
      2. f-string heads anywhere with ``f"namespace:{...}"`` form
         where namespace is alpha + underscore only.

    Explicitly EXCLUDES error-message prefixes like
    ``adapter_failed:`` and ``adapter_raised:`` because those
    appear in error formatting, not Shopify writes. Filter by
    blacklist after collection.
    """
    out: set[str] = set()
    # Blacklist of f-string prefixes that LOOK like namespaces but
    # are actually error message codes, log keys, or internal
    # identifiers -- never reach Shopify as tags.
    error_prefixes = {
        "adapter_failed", "adapter_raised", "adapter_raise",
        "adapter_rejected", "enqueue_raised", "enqueue_raise",
        "engine_output_not_successful", "engine_output",
        "product_optimization",  # internal action_type, not tag
        "store_design",
    }

    # Pass 1: module-level constant assignments. Three patterns:
    #   - _TAG = "ns:value"               -> stored verbatim
    #   - _TAG_X = "shopai-return-X"      -> stored verbatim
    #   - _TAG_PREFIX = "ns-"             -> stored as "ns-*"
    # (Caller-side: the constant must start with _ and contain TAG
    # somewhere in the name -- this rules out arbitrary string
    # constants like _DEFAULT_SETTING.)
    for node in getattr(tree, "body", []) or []:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        literal = node.value.value
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if "TAG" not in name:
                continue
            if _TAG_PATTERN.match(literal):
                out.add(literal)
                break
            if _TAG_DASH_PATTERN.match(literal):
                out.add(literal)
                break
            if (
                "PREFIX" in name
                and _TAG_PREFIX_PATTERN.match(literal)
            ):
                ns = literal.rstrip("-")
                if ns and ns not in error_prefixes:
                    out.add(f"{ns}-*")
                break

    # Pass 2: collect f-string heads with namespace prefix.
    # Only accept lowercase-only prefixes (the convention) and
    # exclude common error-message false positives.
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            head = ""
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    head += part.value
                else:
                    break
            if head and ":" in head:
                prefix, _, _ = head.partition(":")
                if (
                    prefix
                    and prefix.islower()
                    and prefix.replace("_", "").isalnum()
                    and prefix not in error_prefixes
                ):
                    out.add(f"{prefix}:*")

    # Pass 3: tag-literals inside list/tuple expressions (handles
    # appliers that inline ["ns:value"] without a _FOO_TAG constant)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                if not _TAG_PATTERN.match(elt.value):
                    continue
                prefix = elt.value.split(":", 1)[0]
                if prefix not in error_prefixes:
                    out.add(elt.value)

    # Pass 4: tag-literals passed as arguments to function calls
    # (e.g. tags.append("fraud-review") inside a helper). Restricted
    # to dash-style tags with 2+ dashes to avoid false positives
    # on arbitrary 2-word literals.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if not _TAG_DASH_PATTERN.match(arg.value):
                    continue
                head = arg.value.split("-", 1)[0]
                if head not in error_prefixes:
                    out.add(arg.value)

    return out
