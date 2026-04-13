"""Cognitive functions — MBTI-style dispatch over existing subsystems.

Wave 2 #7 closes the "flat 9-cycle phase handling" gap. The
existing :class:`core.cognitive.mind.Mind` already runs a
sequenced loop (perceive → reflect → set_goals → plan →
imagine → predict → act → learn → consolidate), and each phase
talks to the same fixed set of modules. That's correct but
blunt: every cycle spends time on every module even when the
situation clearly calls for "just analyse" or "just imagine
what-ifs".

This module adds a lightweight *cognitive function* layer that
maps the 8 Jungian functions onto the existing subsystems. It
introduces **no new intelligence** — every handler delegates
to a module that already exists — but it lets the Mind cycle
pick which tool fits the current step instead of always
running everything.

The eight functions
-------------------

Introverted / extroverted pairs across Thinking, Feeling,
Intuition, and Sensing:

* ``Ti`` — Introverted Thinking: analyse internal consistency,
  sharpen reasoning. Maps to ``Reflection``.
* ``Te`` — Extroverted Thinking: plan for external effect,
  optimise. Maps to ``Planner`` + ``Imagination``.
* ``Ne`` — Extroverted Intuition: explore possibilities, push
  into novel territory. Maps to ``Curiosity``.
* ``Ni`` — Introverted Intuition: synthesise long-term
  patterns into insight. Maps to ``Consolidation``.
* ``Si`` — Introverted Sensing: recall past concrete cases,
  compare with present. Maps to ``SelfModel`` snapshot.
* ``Se`` — Extroverted Sensing: grab fresh data from the
  environment. Maps to the perceive-side data pipeline.
* ``Fi`` — Introverted Feeling: consult values. Maps to
  :class:`core.mentality.Values` when supplied.
* ``Fe`` — Extroverted Feeling: model how others react. Maps
  to ``TheoryOfMind``.

The module exports :class:`CognitiveFunction` (the enum) and
:class:`CognitiveDispatcher` (the runtime that holds handler
references and invokes the right one). Mind can build a
dispatcher with its own module instances and query
``dispatch(fn, context)`` during any phase to get a fitted
result — or fall back to the current linear flow if the
caller hasn't pulled this module in yet.

Design notes
------------

* **Pure dispatch.** No scoring, no ranking, no plan selection.
  The dispatcher's job is to resolve a function name to a
  callable and run it. Mind decides *which* function to pick
  each step, the dispatcher just hands the right tool over.
* **Lazy binding.** Handlers are registered by reference so
  a module that fails to import (ex: Imagination needs an
  LLM backend) doesn't block the rest of the dispatcher. The
  default dispatcher is built with :meth:`default_for_mind`
  which only wires handlers for modules that import cleanly.
* **Stable function ↔ module mapping.** The enum → module
  mapping is frozen in :data:`_FUNCTION_TO_MODULE`. Tests
  assert the mapping is complete and unique so a future
  refactor can't silently break dispatch.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque

from utils.logger import get_logger

logger = get_logger("cognitive.functions")


# ---------------------------------------------------------------------------
# Enum + canonical mapping
# ---------------------------------------------------------------------------


class CognitiveFunction(str, Enum):
    """The eight Jungian cognitive functions ShopAI dispatches on."""

    Ti = "Ti"  # Introverted Thinking
    Te = "Te"  # Extroverted Thinking
    Ne = "Ne"  # Extroverted Intuition
    Ni = "Ni"  # Introverted Intuition
    Si = "Si"  # Introverted Sensing
    Se = "Se"  # Extroverted Sensing
    Fi = "Fi"  # Introverted Feeling
    Fe = "Fe"  # Extroverted Feeling


# Canonical mapping from function to the target subsystem's
# *short name*. The dispatcher resolves the name to a concrete
# handler via its registry. Keeping the mapping as strings (not
# module refs) lets tests assert it without pulling in any
# cognitive module.

_FUNCTION_TO_MODULE: dict[CognitiveFunction, str] = {
    CognitiveFunction.Ti: "reflection",
    CognitiveFunction.Te: "planner",
    CognitiveFunction.Ne: "curiosity",
    CognitiveFunction.Ni: "consolidation",
    CognitiveFunction.Si: "self_model",
    CognitiveFunction.Se: "perception",
    CognitiveFunction.Fi: "values",
    CognitiveFunction.Fe: "theory_of_mind",
}


def function_module(function: CognitiveFunction) -> str:
    """Return the canonical subsystem name for a function."""
    return _FUNCTION_TO_MODULE[function]


def module_function(module_name: str) -> CognitiveFunction | None:
    """Reverse lookup — which function routes to this module?"""
    for fn, mod in _FUNCTION_TO_MODULE.items():
        if mod == module_name:
            return fn
    return None


# ---------------------------------------------------------------------------
# Dispatch result
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    """Outcome of a single :meth:`CognitiveDispatcher.dispatch` call.

    ``value`` is the handler's return value. ``skipped`` is True
    when the dispatcher had no registered handler for the
    requested function (common when the optional subsystem
    isn't installed in a stripped-down deployment).
    """

    function: CognitiveFunction
    module:   str
    value:    Any = None
    skipped:  bool = False
    error:    str | None = None

    def ok(self) -> bool:
        return self.error is None and not self.skipped


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


HandlerFn = Callable[[dict[str, Any]], Any]


class CognitiveDispatcher:
    """Routes cognitive function requests to registered handlers.

    The dispatcher owns a handler table keyed by
    :class:`CognitiveFunction`. Callers register handlers up
    front (at Mind construction time) and invoke them via
    :meth:`dispatch`. Missing handlers don't raise — they
    produce a ``skipped=True`` result so Mind can fall back to
    its legacy linear flow without branching on import
    failures.
    """

    def __init__(self, *, history_size: int = 64) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[CognitiveFunction, HandlerFn] = {}
        # Wave 4 #4: observability — per-function call / error counts
        # and a bounded history so operators can see which cognitive
        # functions have been exercised recently.
        self._call_counts:  dict[CognitiveFunction, int] = {}
        self._error_counts: dict[CognitiveFunction, int] = {}
        self._recent: Deque[dict[str, Any]] = deque(maxlen=max(1, history_size))

    # -- registration -----------------------------------------------

    def register(
        self,
        function: CognitiveFunction,
        handler: HandlerFn,
    ) -> None:
        """Bind *handler* to *function*. Overwrites any existing."""
        with self._lock:
            self._handlers[function] = handler
            logger.debug(
                "CognitiveDispatcher: registered %s → %s",
                function.value, getattr(handler, "__qualname__", handler),
            )

    def unregister(self, function: CognitiveFunction) -> bool:
        with self._lock:
            return self._handlers.pop(function, None) is not None

    def has(self, function: CognitiveFunction) -> bool:
        with self._lock:
            return function in self._handlers

    def registered(self) -> list[CognitiveFunction]:
        with self._lock:
            return list(self._handlers.keys())

    # -- dispatch ---------------------------------------------------

    def dispatch(
        self,
        function: CognitiveFunction,
        context: dict[str, Any] | None = None,
    ) -> DispatchResult:
        """Invoke the handler for *function* with *context*.

        Exceptions from the handler are captured on the
        :class:`DispatchResult`'s ``error`` field so one
        flaky subsystem doesn't take down the Mind cycle.

        Every dispatch — including skipped and errored ones —
        is logged to the bounded history and reflected in
        :meth:`stats` (Wave 4 #4 observability).
        """
        module = _FUNCTION_TO_MODULE[function]
        with self._lock:
            handler = self._handlers.get(function)
        if handler is None:
            result = DispatchResult(
                function=function, module=module, skipped=True,
            )
            self._record_trace(result)
            return result
        try:
            value = handler(context or {})
            result = DispatchResult(
                function=function, module=module, value=value,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "CognitiveDispatcher: handler for %s raised %s: %s",
                function.value, type(exc).__name__, exc,
            )
            result = DispatchResult(
                function=function, module=module,
                error=f"{type(exc).__name__}: {exc}",
            )
        self._record_trace(result)
        return result

    def _record_trace(self, result: DispatchResult) -> None:
        """Append *result* to the observability ring buffer and
        bump the per-function call/error counters. Internal use.
        """
        status = (
            "error" if result.error
            else "skipped" if result.skipped
            else "ok"
        )
        with self._lock:
            self._call_counts[result.function] = (
                self._call_counts.get(result.function, 0) + 1
            )
            if status == "error":
                self._error_counts[result.function] = (
                    self._error_counts.get(result.function, 0) + 1
                )
            self._recent.append({
                "ts":       time.time(),
                "function": result.function.value,
                "module":   result.module,
                "status":   status,
            })

    # -- observability ---------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return observability counters for every function.

        Shape::

            {
              "registered": ["Ti", "Te", ...],
              "counts":     {"Ti": 3, "Te": 2, ...},
              "errors":     {"Ti": 0, ...},
              "recent":     [{"ts": ..., "function": ..., "status": ...}, ...],
              "total":      5,
            }

        Safe to call from any thread.
        """
        with self._lock:
            counts = {
                fn.value: n for fn, n in self._call_counts.items()
            }
            errors = {
                fn.value: n for fn, n in self._error_counts.items()
            }
            recent = list(self._recent)
            return {
                "registered": [fn.value for fn in self._handlers.keys()],
                "counts":     counts,
                "errors":     errors,
                "recent":     recent,
                "total":      sum(self._call_counts.values()),
            }

    def reset_stats(self) -> None:
        """Clear counters + history. Handlers are left intact."""
        with self._lock:
            self._call_counts.clear()
            self._error_counts.clear()
            self._recent.clear()

    # -- batch ------------------------------------------------------

    def dispatch_many(
        self,
        functions: list[CognitiveFunction],
        context: dict[str, Any] | None = None,
    ) -> list[DispatchResult]:
        """Dispatch a sequence of functions in order.

        Used by Mind phases that fan out across multiple
        functions in one step ("Ti+Te" for deliberation, for
        example). Results preserve order.
        """
        return [self.dispatch(fn, context) for fn in functions]

    # -- factory ----------------------------------------------------

    @classmethod
    def default_for_mind(cls, mind: Any) -> CognitiveDispatcher:
        """Build a dispatcher from a :class:`Mind`-like object.

        Inspects *mind* for attributes matching the canonical
        subsystem names and registers a trivial handler for
        each that delegates the *context* dict to the
        subsystem's default entry point. Missing attributes
        are skipped silently so degraded deployments still get
        a usable dispatcher.

        The concrete entry points:

        * ``reflection.analyse(context)``
        * ``planner.plan(context)``
        * ``curiosity.recommend(context)``
        * ``consolidation.run(context)``
        * ``self_model.snapshot()``
        * perception → ``mind.perceive(context)`` (built-in
          perceive path)
        * ``values.score(context)``
        * ``theory_of_mind.predict(context)``

        Handlers catch ``AttributeError`` at call time so even
        partial subsystem implementations don't crash a
        dispatch.
        """
        disp = cls()

        def _safe(handler: HandlerFn) -> HandlerFn:
            def wrapped(ctx: dict[str, Any]) -> Any:
                try:
                    return handler(ctx)
                except AttributeError as exc:
                    raise RuntimeError(f"handler missing method: {exc}")
            return wrapped

        ref = getattr(mind, "reflection", None)
        if ref is not None and hasattr(ref, "analyse"):
            disp.register(CognitiveFunction.Ti, _safe(lambda c: ref.analyse(c)))

        plan = getattr(mind, "planner", None)
        if plan is not None and hasattr(plan, "plan"):
            disp.register(CognitiveFunction.Te, _safe(lambda c: plan.plan(c)))

        cur = getattr(mind, "curiosity", None)
        if cur is not None and hasattr(cur, "recommend"):
            disp.register(CognitiveFunction.Ne, _safe(lambda c: cur.recommend(c)))

        con = getattr(mind, "consolidation", None)
        if con is not None and hasattr(con, "run"):
            disp.register(CognitiveFunction.Ni, _safe(lambda c: con.run(c)))

        sm = getattr(mind, "self_model", None)
        if sm is not None and hasattr(sm, "snapshot"):
            disp.register(CognitiveFunction.Si, _safe(lambda c: sm.snapshot()))

        # Se: perception has no dedicated subsystem — mind's own
        # perceive method is the entry point, if present.
        if hasattr(mind, "perceive"):
            disp.register(
                CognitiveFunction.Se,
                _safe(lambda c: mind.perceive(c)),
            )

        values = getattr(mind, "values", None)
        if values is not None and hasattr(values, "score"):
            disp.register(CognitiveFunction.Fi, _safe(lambda c: values.score(c)))

        tom = getattr(mind, "theory_of_mind", None)
        if tom is not None and hasattr(tom, "predict"):
            disp.register(CognitiveFunction.Fe, _safe(lambda c: tom.predict(c)))

        return disp


__all__ = [
    "CognitiveFunction",
    "CognitiveDispatcher",
    "DispatchResult",
    "function_module",
    "module_function",
]
