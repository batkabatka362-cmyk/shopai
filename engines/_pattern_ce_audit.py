"""W963-155: Pattern CE audit -- external vendor handler
registration parity.

THE CONTRACT

The unified external webhook layer (W963-147) routes
vendor-prefixed topics to engines via three independent
registrations:

  1. Class defined as ``<Name>VendorHandler`` extending
     ``VendorHandler`` in ``core/webhooks/external/
     vendors/<name>.py``.
  2. Symbol exported in both ``vendors/__init__.py``
     and ``external/__init__.py`` ``__all__``.
  3. ``EVENT_ENGINE_MAP`` has at least one key with
     prefix ``"<name>."`` (matches the handler's
     class-attribute ``name``).

When a 7th vendor handler ships (PayPal -> Klarna ->
TaxJar -> ...), it's easy to:

  - forget the __all__ entry (handler import works in
    tests but external/__init__.py star-import misses it).
  - forget the EVENT_ENGINE_MAP wire-up (handler
    deserialises events but they go to no engine).

Both failures are SILENT in unit tests because the
test imports the handler directly. Production webhooks
just stop firing the relevant engines.

Pattern CE codifies the 3 invariants as an institutional
gate. Every vendor handler in vendors/ must be:
  - exported in vendors/__init__.py __all__
  - exported in external/__init__.py __all__
  - mapped to at least one EVENT_ENGINE_MAP key
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


_VENDORS_DIR = Path("core/webhooks/external/vendors")
_VENDORS_INIT = _VENDORS_DIR / "__init__.py"
_EXTERNAL_INIT = Path("core/webhooks/external/__init__.py")
_HANDLER_PY = Path("core/webhooks/external/handler.py")


@dataclass
class VendorViolation:
    """One vendor handler that fails an invariant."""
    handler_class: str
    module_path: str
    missing: tuple[str, ...]


@dataclass
class PatternCEReport:
    """Result of one audit run."""
    vendors_checked: list[str] = field(default_factory=list)
    violations: list[VendorViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def _find_vendor_handler_classes() -> dict[str, str]:
    """Walk vendors/*.py + return {ClassName: module_path}
    for every subclass of VendorHandler."""
    result: dict[str, str] = {}
    if not _VENDORS_DIR.exists():
        return result
    for py in sorted(_VENDORS_DIR.glob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # Subclass of VendorHandler (or anything
            # ending in VendorHandler -- we accept the
            # text form because the import dance hides
            # real inheritance behind absolute names)
            base_names = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    base_names.append(b.id)
                elif isinstance(b, ast.Attribute):
                    base_names.append(b.attr)
            if "VendorHandler" in base_names:
                result[node.name] = str(py).replace(
                    "\\", "/",
                )
    return result


def _parse_all_exports(path: Path) -> set[str]:
    """Extract symbol set from ``__all__ = [...]``."""
    if not path.exists():
        return set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [
            t.id for t in node.targets
            if isinstance(t, ast.Name)
        ]
        if "__all__" not in targets:
            continue
        if isinstance(
            node.value, (ast.List, ast.Tuple),
        ):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and (
                    isinstance(elt.value, str)
                ):
                    out.add(elt.value)
    return out


def _parse_event_engine_map_keys() -> set[str]:
    """Extract ``EVENT_ENGINE_MAP = {...}`` key set.

    Handles both forms (handler.py uses an annotated
    assignment ``EVENT_ENGINE_MAP: dict[...] = {...}``).
    """
    if not _HANDLER_PY.exists():
        return set()
    try:
        tree = ast.parse(
            _HANDLER_PY.read_text(encoding="utf-8"),
        )
    except (SyntaxError, OSError):
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        value = None
        if isinstance(node, ast.Assign):
            targets = [
                t.id for t in node.targets
                if isinstance(t, ast.Name)
            ]
            if "EVENT_ENGINE_MAP" in targets:
                value = node.value
        elif isinstance(node, ast.AnnAssign):
            tgt = node.target
            if isinstance(tgt, ast.Name) and (
                tgt.id == "EVENT_ENGINE_MAP"
            ):
                value = node.value
        if value is None or not isinstance(value, ast.Dict):
            continue
        for key in value.keys:
            if isinstance(key, ast.Constant) and (
                isinstance(key.value, str)
            ):
                out.add(key.value)
    return out


def _class_string_attribute(
    class_module: str, attr: str,
) -> str | None:
    """Read a ``<attr> = "..."`` class attribute."""
    path = Path(class_module)
    if not path.exists():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            targets = [
                t.id for t in stmt.targets
                if isinstance(t, ast.Name)
            ]
            if attr not in targets:
                continue
            if isinstance(stmt.value, ast.Constant) and (
                isinstance(stmt.value.value, str)
            ):
                return stmt.value.value
    return None


def _class_bool_attribute(
    class_module: str, attr: str, default: bool,
) -> bool:
    """Read ``<attr> = True/False`` class attribute."""
    path = Path(class_module)
    if not path.exists():
        return default
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return default
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            targets = [
                t.id for t in stmt.targets
                if isinstance(t, ast.Name)
            ]
            if attr not in targets:
                continue
            if isinstance(stmt.value, ast.Constant) and (
                isinstance(stmt.value.value, bool)
            ):
                return stmt.value.value
    return default


def _name_attribute(class_module: str) -> str | None:
    return _class_string_attribute(class_module, "name")


def audit_vendor_handler_parity() -> PatternCEReport:
    """Run Pattern CE: every vendor handler is registered
    in 3 catalogs (vendors/__all__, external/__all__,
    EVENT_ENGINE_MAP)."""
    report = PatternCEReport()

    classes = _find_vendor_handler_classes()
    vendors_all = _parse_all_exports(_VENDORS_INIT)
    external_all = _parse_all_exports(_EXTERNAL_INIT)
    map_keys = _parse_event_engine_map_keys()

    for cls_name, module_path in sorted(classes.items()):
        report.vendors_checked.append(cls_name)
        missing: list[str] = []

        if cls_name not in vendors_all:
            missing.append("vendors/__init__.__all__")
        if cls_name not in external_all:
            missing.append("external/__init__.__all__")

        # Resolve name attribute then check map_keys for
        # any prefix match. Outbound-only handlers (e.g.
        # GA4 push-out placeholder) opt out via class
        # attribute ``inbound = False``.
        vendor_name = _name_attribute(module_path)
        if vendor_name:
            is_inbound = _class_bool_attribute(
                module_path, "inbound", default=True,
            )
            if is_inbound:
                has_topic = any(
                    k.startswith(f"{vendor_name}.")
                    for k in map_keys
                )
                if not has_topic:
                    missing.append(
                        f"EVENT_ENGINE_MAP[{vendor_name}.*]",
                    )
        else:
            missing.append("name class attribute missing")

        if missing:
            report.violations.append(VendorViolation(
                handler_class=cls_name,
                module_path=module_path,
                missing=tuple(missing),
            ))

    return report
