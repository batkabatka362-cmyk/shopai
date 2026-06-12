"""Pattern I audit — engine ``capability_name=`` strings must
match real ``Capability`` enum members claimed by ``1+`` adapters.

CLAUDE.md Pattern I documents the silent failure mode caught in
PR #40: engine hydrators reference a capability name string
(``"SHOPIFY_FETCH_ORDERS"``) that exists in the Capability enum
but is not claimed by any adapter. The router has no route, the
hydrator's exception path returns ``[]``, and the engine falls
through to its "X list is required" guard — exactly the failure
mode auto-hydration was meant to prevent. Mocked unit tests
never catch this because they patch the router; only live
production traffic hits the real registry.

This module surfaces every ``capability_name=...`` string literal
in ``engines/**/*.py`` and cross-references it against:

  1. **The Capability enum** — typos like ``"SHOPIFY_FETCH_ORDRES"``
     would surface here as ``unknown_enum_member``.
  2. **The live adapter registry** — names that exist on the enum
     but no adapter claims surface as ``unclaimed_by_adapter``.

Returns a structured report. The doctor and a dedicated CLI
command (``shopai engines-capability-audit``) consume it.

Design choice: AST-walks the source rather than importing each
engine module. Importing engines triggers side effects
(``register_engine`` decorator + telemetry hooks) and slows the
audit from milliseconds to seconds. The AST walk is precise
because ``hydrate(capability_name="X")`` is a keyword arg
pattern the compiler can't drop or fold.
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from utils.logger import get_logger

logger = get_logger("engines._engine_capability_audit")


@dataclass(frozen=True)
class EngineCapabilityRef:
    """One capability reference found in an engine file.

    Two source patterns are tracked:
      * ``capability_name=...`` keyword arg (hydrator framework).
      * W962-17: direct ``router.execute(Capability.X, ...)``
        (bypasses the hydrator -- callers like
        _revenue_attribution / inventory_checker / fraud_screener
        used to be invisible to the audit).
    """

    engine: str            # engine package name (loyalty, dynamic_pricing, ...)
    file: str              # relative path from engines/ root
    lineno: int            # line where the keyword appears
    capability_name: str   # the string literal value
    via: str = "capability_name_kwarg"  # or "router_execute"


@dataclass(frozen=True)
class EngineCapabilityReport:
    """Aggregated Pattern I audit result."""

    refs: tuple[EngineCapabilityRef, ...]
    unknown_enum_member: list[EngineCapabilityRef] = field(default_factory=list)
    unclaimed_by_adapter: list[EngineCapabilityRef] = field(default_factory=list)
    total_refs: int = 0
    distinct_capabilities: int = 0

    @property
    def has_gaps(self) -> bool:
        return bool(self.unknown_enum_member or self.unclaimed_by_adapter)


def _collect_refs(
    engines_root: Path,
) -> tuple[EngineCapabilityRef, ...]:
    refs: list[EngineCapabilityRef] = []
    for py_path in engines_root.rglob("*.py"):
        # Skip __pycache__ and tests subdirs
        if "__pycache__" in py_path.parts:
            continue
        try:
            src = py_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.debug("could not read %s: %s", py_path, exc)
            continue
        try:
            tree = ast.parse(src, filename=str(py_path))
        except SyntaxError as exc:
            logger.debug("syntax error in %s: %s", py_path, exc)
            continue

        # engine package name = first dir under engines/, except
        # for top-level helper files (engines/_shopify_hydrator.py
        # etc.) which we tag with their own name
        rel = py_path.relative_to(engines_root)
        if len(rel.parts) == 1:
            engine_name = rel.parts[0].rstrip(".py")
        else:
            engine_name = rel.parts[0]

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Pattern (1): capability_name="X" kwarg
            for kw in node.keywords:
                if kw.arg != "capability_name":
                    continue
                if not isinstance(kw.value, ast.Constant):
                    continue
                value = kw.value.value
                if not isinstance(value, str):
                    continue
                refs.append(EngineCapabilityRef(
                    engine=engine_name,
                    file=str(rel).replace(os.sep, "/"),
                    lineno=node.lineno,
                    capability_name=value,
                    via="capability_name_kwarg",
                ))
            # W962-17 Pattern (2): direct router.execute(
            # Capability.X, ...) — bypasses the hydrator. Look
            # for an ast.Attribute(attr="execute") whose first
            # positional arg is Capability.<NAME>.
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr != "execute":
                continue
            # Restrict to call sites where the receiver looks
            # like a router (router.execute / self.router.execute
            # / self._router.execute). Otherwise we false-positive
            # on every .execute() call in the codebase.
            recv = func.value
            recv_name = None
            if isinstance(recv, ast.Name):
                recv_name = recv.id
            elif isinstance(recv, ast.Attribute):
                recv_name = recv.attr
            if recv_name not in ("router", "_router", "smart_router"):
                continue
            if not node.args:
                continue
            first = node.args[0]
            # Capability.X
            if (
                isinstance(first, ast.Attribute)
                and isinstance(first.value, ast.Name)
                and first.value.id == "Capability"
            ):
                refs.append(EngineCapabilityRef(
                    engine=engine_name,
                    file=str(rel).replace(os.sep, "/"),
                    lineno=node.lineno,
                    capability_name=first.attr,
                    via="router_execute",
                ))
    return tuple(refs)


def audit_engine_capabilities(
    engines_root: Path | str | None = None,
) -> EngineCapabilityReport:
    """Run the Pattern I audit and return a structured report.

    Args:
        engines_root: Path to the engines/ directory. Defaults to
            the repo's ``engines/`` next to this module.

    Returns:
        :class:`EngineCapabilityReport` with refs categorised into
        ``unknown_enum_member`` (typo) and ``unclaimed_by_adapter``
        (real enum value but the router can't route it).
    """
    if engines_root is None:
        engines_root = Path(__file__).resolve().parent
    else:
        engines_root = Path(engines_root)
    if not engines_root.exists():
        return EngineCapabilityReport(refs=())

    refs = _collect_refs(engines_root)

    # Build sets we cross-reference against
    from core.adapters.base import Capability

    enum_names = {c.name for c in Capability}

    # Adapter claims — pull from the live bootstrap. Use the
    # same surface as Pattern Y so the two audits stay consistent.
    claimed: set[str] = set()
    try:
        from core.adapters.shopify import bootstrap
        for adapter_cls in bootstrap._SHOPIFY_ADAPTER_CLASSES:
            for cap in getattr(adapter_cls, "capabilities", set()):
                # cap is either a Capability enum value or a string
                # claim (orphan). Pattern Y surfaces the orphan
                # case; for this audit only real enum entries count.
                name = getattr(cap, "name", None)
                if name:
                    claimed.add(name)
    except Exception as exc:  # noqa: BLE001
        logger.debug("adapter bootstrap unavailable: %s", exc)

    # W962-17: secondary adapter packages (ads / search / email
    # / llm / shipping) also claim capabilities. The router-execute
    # extension surfaces those too, so we need their claims to
    # avoid false positives like WEB_SEARCH (claimed by search/).
    for pkg_name in (
        "ads", "search", "email", "llm", "shipping", "social",
        # W963-144: tracking + sourcing packages also
        # contribute capability claims.
        # W963-145: helpdesk (Gorgias).
        "sourcing", "tracking", "helpdesk",
    ):
        try:
            pkg = __import__(
                f"core.adapters.{pkg_name}.bootstrap",
                fromlist=["*"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "secondary bootstrap %s unavailable: %s",
                pkg_name, exc,
            )
            continue
        # Bootstraps follow a convention of registering classes
        # in a module-level list; the names vary. Walk module
        # attrs and find any class with a `capabilities` set.
        for attr_name in dir(pkg):
            obj = getattr(pkg, attr_name, None)
            if isinstance(obj, (list, tuple, set)):
                for cls in obj:
                    caps = getattr(cls, "capabilities", None)
                    if not isinstance(caps, (set, frozenset, list, tuple)):
                        continue
                    for cap in caps:
                        name = getattr(cap, "name", None)
                        if name:
                            claimed.add(name)

    unknown: list[EngineCapabilityRef] = []
    unclaimed: list[EngineCapabilityRef] = []
    for ref in refs:
        if ref.capability_name not in enum_names:
            unknown.append(ref)
        elif ref.capability_name not in claimed:
            unclaimed.append(ref)

    distinct = len({r.capability_name for r in refs})

    return EngineCapabilityReport(
        refs=refs,
        unknown_enum_member=unknown,
        unclaimed_by_adapter=unclaimed,
        total_refs=len(refs),
        distinct_capabilities=distinct,
    )


def format_refs(
    refs: Iterable[EngineCapabilityRef],
    limit: int = 5,
) -> str:
    """Human-readable rendering of a ref list, for CLI output."""
    items = list(refs)
    if not items:
        return ""
    lines = []
    for ref in items[:limit]:
        lines.append(
            f"  {ref.capability_name}  "
            f"({ref.engine}/{ref.file.split('/', 1)[-1]}:{ref.lineno})"
        )
    if len(items) > limit:
        lines.append(f"  ... +{len(items) - limit} more")
    return "\n".join(lines)
