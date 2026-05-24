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


# Tag-namespace literal pattern: word:word. Excludes URLs (no ://),
# excludes capability constants (which are all-caps).
_TAG_PATTERN = re.compile(r"^[a-z][a-z0-9_]*:[a-z0-9_]+$")

# Map SHOPIFY_X capability to the entity it touches.
_CAPABILITY_TO_TARGET = {
    "SHOPIFY_UPDATE_PRODUCT": "product",
    "SHOPIFY_TAG_CUSTOMER": "customer",
    "SHOPIFY_TAG_ORDER": "order",
}


def catalog_tags(engines_dir: str = "engines") -> TagCatalog:
    """Walk engines/*/tag_applier.py files and build the catalog.

    Args:
        engines_dir: Root engines directory (default ``engines``).

    Returns:
        Populated :class:`TagCatalog`.
    """
    root = Path(engines_dir)
    catalog = TagCatalog()
    if not root.exists() or not root.is_dir():
        return catalog

    for applier_path in sorted(root.glob("*/tag_applier.py")):
        catalog.engines_scanned += 1
        engine_name = applier_path.parent.name
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
            namespace = tag.split(":", 1)[0]
            catalog.by_namespace.setdefault(namespace, []).append(entry)
            catalog.by_target.setdefault(target, []).append(entry)

    return catalog


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
    error_prefixes = {
        "adapter_failed", "adapter_raised", "enqueue_raised",
    }

    # Pass 1: module-level _FOO_TAG = "namespace:value" assignments
    for node in getattr(tree, "body", []) or []:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        if not _TAG_PATTERN.match(node.value.value):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.endswith("_TAG"):
                out.add(node.value.value)
                break

    # Pass 2: collect f-string heads with namespace prefix
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
                if prefix and prefix.replace("_", "").isalnum():
                    if prefix not in error_prefixes:
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

    return out
