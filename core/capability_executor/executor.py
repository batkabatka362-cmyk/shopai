"""In-process executor: import module:attr, call with kwargs.

The executor handles three module_path shapes seen in the
existing registrations:

  1. ``module.path:function_name`` -- plain callable.
     Invoked as ``fn(**args)``.
  2. ``module.path:ClassName`` -- engine-style class with
     a ``run(input_envelope)`` method. Invoked as
     ``ClassName().run(args)``. Heuristic: if the attr is
     a class (``isinstance(target, type)``) AND has a
     ``run`` method, use the engine convention.
  3. ``cli:_cmd_X`` -- CLI handler entry point. Not
     supported via in-process call (would need argparse
     Namespace construction). Returns an error result so
     the operator falls back to ``shopai X`` directly.

Future iterations can add per-capability adapter shims
(e.g. for engines that want input shape adaptation), but
the conservative default is "call the function with the
args we have and let it raise if the shape's wrong".
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

from core.capability_registry import (
    Capability,
    get_registry,
)
from core.capability_registry.bootstrap import (
    ensure_registered,
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of invoking a capability.

    Always returned, never raised -- callers can branch on
    ``ok`` and read ``data`` / ``error`` uniformly.
    """

    ok: bool
    capability: str
    module_path: str = ""
    data: Any = None
    error: str | None = None
    invocation_kind: str = ""  # "function" | "engine" |
                               # "cli_handler"
    args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "capability": self.capability,
            "module_path": self.module_path,
            "data": self.data,
            "error": self.error,
            "invocation_kind": self.invocation_kind,
            "args": dict(self.args),
        }


class CapabilityExecutor:
    """In-process executor. Stateful enough to cache the
    registry handle."""

    def __init__(
        self, *, skip_bootstrap: bool = False,
    ) -> None:
        if not skip_bootstrap:
            ensure_registered()
        self._registry = get_registry()

    def execute(
        self,
        name: str,
        args: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Invoke ``name`` with ``args``.

        Returns ExecutionResult uniformly -- no raises.
        """
        args_clean: dict[str, Any] = dict(args or {})
        cap = self._registry.get(name)
        if cap is None:
            return ExecutionResult(
                ok=False,
                capability=name,
                error="unknown_capability",
                args=args_clean,
            )

        # Parse "module:attr"
        if not cap.module_path or ":" not in cap.module_path:
            return ExecutionResult(
                ok=False,
                capability=name,
                module_path=cap.module_path,
                error=(
                    f"unparseable module_path: "
                    f"{cap.module_path!r}"
                ),
                args=args_clean,
            )
        module_name, _, attr = cap.module_path.partition(":")
        module_name = module_name.strip()
        attr = attr.strip()

        # CLI handler entry points (module starts with "cli")
        # are not invokable in-process -- they expect an
        # argparse Namespace, not kwargs.
        if module_name == "cli":
            return ExecutionResult(
                ok=False,
                capability=name,
                module_path=cap.module_path,
                error=(
                    "cli_handler_not_in_process: invoke "
                    "via shopai CLI instead"
                ),
                invocation_kind="cli_handler",
                args=args_clean,
            )

        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "executor import failed for %s: %s",
                module_name, exc,
            )
            return ExecutionResult(
                ok=False,
                capability=name,
                module_path=cap.module_path,
                error=f"import_failed: {exc}",
                args=args_clean,
            )

        target = getattr(mod, attr, None)
        if target is None:
            return ExecutionResult(
                ok=False,
                capability=name,
                module_path=cap.module_path,
                error=(
                    f"attribute_not_found: {attr} in "
                    f"{module_name}"
                ),
                args=args_clean,
            )

        # Pick invocation style.
        invocation_kind = self._classify_target(target)

        try:
            if invocation_kind == "engine":
                # Engine convention: ClassName().run(input)
                instance = target()
                result = instance.run(args_clean)
            else:
                # Plain function: call with kwargs
                result = target(**args_clean)
        except TypeError as exc:
            # Most common: wrong arg shape. Helpful error.
            return ExecutionResult(
                ok=False,
                capability=name,
                module_path=cap.module_path,
                error=f"call_failed: {exc}",
                invocation_kind=invocation_kind,
                args=args_clean,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "executor call raised for %s: %s",
                name, exc,
            )
            return ExecutionResult(
                ok=False,
                capability=name,
                module_path=cap.module_path,
                error=str(exc),
                invocation_kind=invocation_kind,
                args=args_clean,
            )

        return ExecutionResult(
            ok=True,
            capability=name,
            module_path=cap.module_path,
            data=result,
            invocation_kind=invocation_kind,
            args=args_clean,
        )

    def dry_run(
        self,
        name: str,
        args: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Resolve the module + function + args WITHOUT
        invoking. Returns the same ExecutionResult shape but
        with ``data=None`` and ``ok=True`` when resolution
        succeeded.
        """
        args_clean = dict(args or {})
        cap = self._registry.get(name)
        if cap is None:
            return ExecutionResult(
                ok=False,
                capability=name,
                error="unknown_capability",
                args=args_clean,
            )
        if not cap.module_path or ":" not in cap.module_path:
            return ExecutionResult(
                ok=False,
                capability=name,
                module_path=cap.module_path,
                error=(
                    f"unparseable module_path: "
                    f"{cap.module_path!r}"
                ),
                args=args_clean,
            )
        module_name, _, attr = cap.module_path.partition(":")
        if module_name == "cli":
            return ExecutionResult(
                ok=False,
                capability=name,
                module_path=cap.module_path,
                error=(
                    "cli_handler_not_in_process: invoke "
                    "via shopai CLI instead"
                ),
                invocation_kind="cli_handler",
                args=args_clean,
            )
        try:
            mod = importlib.import_module(module_name)
            target = getattr(mod, attr, None)
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                ok=False,
                capability=name,
                module_path=cap.module_path,
                error=f"resolve_failed: {exc}",
                args=args_clean,
            )
        if target is None:
            return ExecutionResult(
                ok=False,
                capability=name,
                module_path=cap.module_path,
                error=(
                    f"attribute_not_found: {attr} in "
                    f"{module_name}"
                ),
                args=args_clean,
            )
        return ExecutionResult(
            ok=True,
            capability=name,
            module_path=cap.module_path,
            invocation_kind=self._classify_target(target),
            args=args_clean,
        )

    def _classify_target(self, target: Any) -> str:
        """Decide between 'function' and 'engine' calling
        conventions. Engines are classes with a callable
        ``run`` method.
        """
        if isinstance(target, type):
            if hasattr(target, "run") and callable(
                target.run,
            ):
                return "engine"
            return "function"
        return "function"


def execute_capability(
    name: str,
    args: dict[str, Any] | None = None,
) -> ExecutionResult:
    """Module-level shortcut for
    ``CapabilityExecutor().execute(name, args)``."""
    return CapabilityExecutor().execute(name, args)
