"""System catalog — surfaces the complete action surface in one
structured readout.

For each registered dispatcher (action_type), the catalog
cross-references:

  - **dispatcher**: the function that replays the action
    (registered via ``@register_dispatcher("X")``)
  - **capability**: the abstract Capability enum value the
    dispatcher routes through (extracted by AST-walking the
    dispatcher source for ``_router_call("CAPABILITY", ...)``
    calls — robust across the existing 21 dispatchers)
  - **adapter(s)**: every Shopify adapter claiming that
    capability + its declared ``required_scopes``
  - **emitting engines**: every engine that enqueues this
    action_type (AST scan for ``action_type="X"`` literals)

This is the "what can ShopAI do?" answer for operators in one
read. Builds on top of:
  - core.approval.executor._DISPATCHERS (registry)
  - core.approval.dispatchers (AST source)
  - core.adapters.shopify.bootstrap._SHOPIFY_ADAPTER_CLASSES
  - engines/**/*.py (AST scan for enqueue calls)

The catalog is pure read-only and side-effect-free.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("approval.catalog")


@dataclass(frozen=True)
class AdapterClaim:
    """An adapter that claims a particular capability."""

    name: str
    module: str
    required_scopes: tuple[str, ...]
    scope_independent: bool


@dataclass(frozen=True)
class CatalogEntry:
    """One row in the catalog — one registered action_type."""

    action_type: str
    dispatcher_module: str
    dispatcher_qualname: str
    capabilities: tuple[str, ...]
    adapters: tuple[AdapterClaim, ...]
    aggregate_scopes: tuple[str, ...]
    emitting_engines: tuple[str, ...]
    description: str = ""
    """First-line summary extracted from the dispatcher's
    docstring. Empty when the dispatcher has no docstring."""


@dataclass(frozen=True)
class CatalogReport:
    """Aggregated catalog snapshot."""

    entries: tuple[CatalogEntry, ...]
    unknown_dispatchers: tuple[str, ...] = field(default_factory=tuple)
    """action_types whose dispatcher source couldn't be AST-walked
    (e.g. dynamically registered). These still appear in entries
    but with empty ``capabilities``."""


def _first_line_doc(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Extract the first non-empty line of the function's
    docstring (the conventional summary). Empty string when the
    function has no docstring."""
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _walk_dispatcher_capabilities(
    dispatchers_path: Path,
) -> dict[str, tuple[str, ...]]:
    """AST-walk ``dispatchers.py`` and return
    ``{action_type: (capability, ...)}``.

    The walker looks for two patterns:
      1. ``@register_dispatcher("X")`` decorator above each fn
      2. ``_router_call("CAP", ...)`` calls inside the fn body —
         their first arg is the capability the dispatcher would
         route to

    A single dispatcher can call ``_router_call`` multiple times
    (different branches). The walker returns ALL distinct
    capability names found in the body.
    """
    out, _docs = _walk_dispatcher_metadata(dispatchers_path)
    return out


def _walk_dispatcher_metadata(
    dispatchers_path: Path,
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """Combined AST walk: returns
    ``(capability_map, docstring_map)``.

    Same single pass over the file, two outputs. Cheaper than
    walking twice; keeps the existing
    ``_walk_dispatcher_capabilities`` API unchanged for callers
    that don't need docstrings.
    """
    out: dict[str, tuple[str, ...]] = {}
    docs: dict[str, str] = {}
    try:
        src = dispatchers_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug(
            "could not read dispatchers source: %s", exc,
        )
        return out, docs

    try:
        tree = ast.parse(src, filename=str(dispatchers_path))
    except SyntaxError as exc:
        logger.debug("dispatcher source has syntax error: %s", exc)
        return out, docs

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Find @register_dispatcher("X") decorator
        action_type: str | None = None
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name)
                else ""
            )
            if name != "register_dispatcher":
                continue
            if not dec.args:
                continue
            first = dec.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                action_type = first.value
                break
        if action_type is None:
            continue

        # Walk the function body for _router_call("CAP", ...).
        # Also handle the documented delegation pattern: dispatchers
        # that call _generic_mint_dispatch route through
        # SHOPIFY_CREATE_DISCOUNT (see engines/_recovery_codes.py).
        caps: list[str] = []
        delegates_to_mint = False
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name)
                else ""
            )
            if name == "_router_call":
                if not sub.args:
                    continue
                arg0 = sub.args[0]
                if (
                    isinstance(arg0, ast.Constant)
                    and isinstance(arg0.value, str)
                ):
                    if arg0.value not in caps:
                        caps.append(arg0.value)
            elif name in {
                "_generic_mint_dispatch", "mint_recovery_code",
            }:
                delegates_to_mint = True
        if delegates_to_mint and "SHOPIFY_CREATE_DISCOUNT" not in caps:
            caps.append("SHOPIFY_CREATE_DISCOUNT")
        out[action_type] = tuple(caps)
        docs[action_type] = _first_line_doc(node)
    return out, docs


def _walk_engine_action_emitters(
    engines_root: Path,
) -> dict[str, list[str]]:
    """AST-walk ``engines/**/*.py`` and return
    ``{action_type: [engine_name, ...]}``.

    Finds ``action_type="X"`` keyword args in every Call node;
    the function being called doesn't matter (could be
    ``enqueue`` on an ApprovalQueue, ``enqueue_for_approval`` on
    a helper, etc.). What matters is that the engine references
    that action_type string.
    """
    out: dict[str, set[str]] = {}
    if not engines_root.exists():
        return {}
    for py_path in engines_root.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            src = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(src, filename=str(py_path))
        except SyntaxError:
            continue
        rel = py_path.relative_to(engines_root)
        engine_name = rel.parts[0] if len(rel.parts) > 1 else (
            rel.parts[0].rstrip(".py")
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "action_type":
                    continue
                if not isinstance(kw.value, ast.Constant):
                    continue
                v = kw.value.value
                if not isinstance(v, str):
                    continue
                out.setdefault(v, set()).add(engine_name)
    return {k: sorted(v) for k, v in out.items()}


def build_catalog(
    *,
    engines_root: Path | str | None = None,
    dispatchers_path: Path | str | None = None,
) -> CatalogReport:
    """Build the system catalog snapshot.

    Args:
        engines_root: Path to the engines/ directory. Defaults
            to ``<repo>/engines``.
        dispatchers_path: Path to the dispatchers source. Defaults
            to ``<repo>/core/approval/dispatchers.py``.

    Returns:
        :class:`CatalogReport` with one entry per registered
        dispatcher, cross-referenced against adapters + engines.
    """
    from core.approval.executor import (
        _DISPATCHERS,
        _ensure_dispatchers_loaded,
    )
    _ensure_dispatchers_loaded()

    if engines_root is None:
        engines_root = Path(__file__).resolve().parents[2] / "engines"
    else:
        engines_root = Path(engines_root)

    if dispatchers_path is None:
        dispatchers_path = (
            Path(__file__).resolve().parent / "dispatchers.py"
        )
    else:
        dispatchers_path = Path(dispatchers_path)

    cap_map, doc_map = _walk_dispatcher_metadata(dispatchers_path)
    emitter_map = _walk_engine_action_emitters(engines_root)

    # Adapter index: capability_name -> [AdapterClaim, ...]
    adapter_idx: dict[str, list[AdapterClaim]] = {}
    try:
        from core.adapters.shopify import bootstrap
        for cls in bootstrap._SHOPIFY_ADAPTER_CLASSES:
            for cap in getattr(cls, "capabilities", set()):
                name = getattr(cap, "name", None) or str(cap)
                claim = AdapterClaim(
                    name=getattr(cls, "name", cls.__name__),
                    module=cls.__module__,
                    required_scopes=tuple(
                        sorted(
                            getattr(cls, "required_scopes", frozenset()),
                        ),
                    ),
                    scope_independent=bool(
                        getattr(cls, "scope_independent", False),
                    ),
                )
                adapter_idx.setdefault(name, []).append(claim)
    except Exception as exc:  # noqa: BLE001
        logger.debug("adapter bootstrap unavailable: %s", exc)

    entries: list[CatalogEntry] = []
    unknown: list[str] = []
    for action_type, fn in sorted(_DISPATCHERS.items()):
        caps = cap_map.get(action_type, ())
        if not caps:
            unknown.append(action_type)

        # Adapter aggregation: every adapter claiming any of the
        # capabilities this dispatcher routes through.
        adapters: list[AdapterClaim] = []
        agg_scopes: set[str] = set()
        for cap_name in caps:
            for ad in adapter_idx.get(cap_name, []):
                adapters.append(ad)
                agg_scopes.update(ad.required_scopes)

        engines = emitter_map.get(action_type, [])

        entries.append(CatalogEntry(
            action_type=action_type,
            dispatcher_module=getattr(fn, "__module__", "?"),
            dispatcher_qualname=getattr(fn, "__qualname__", "?"),
            capabilities=caps,
            adapters=tuple(adapters),
            aggregate_scopes=tuple(sorted(agg_scopes)),
            emitting_engines=tuple(engines),
            description=doc_map.get(action_type, ""),
        ))

    return CatalogReport(
        entries=tuple(entries),
        unknown_dispatchers=tuple(unknown),
    )
