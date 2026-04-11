"""Tests for core.cognitive.functions (Wave 2 #7)."""
from __future__ import annotations

import pytest

from core.cognitive.functions import (
    CognitiveDispatcher,
    CognitiveFunction,
    DispatchResult,
    function_module,
    module_function,
)


# ---------------------------------------------------------------------------
# Enum + mapping
# ---------------------------------------------------------------------------


def test_all_eight_functions_exist():
    assert {f.value for f in CognitiveFunction} == {
        "Ti", "Te", "Ne", "Ni", "Si", "Se", "Fi", "Fe",
    }


def test_function_module_is_complete_and_unique():
    seen_modules = set()
    for fn in CognitiveFunction:
        mod = function_module(fn)
        assert isinstance(mod, str) and mod
        assert mod not in seen_modules, f"duplicate module: {mod}"
        seen_modules.add(mod)
    assert len(seen_modules) == 8


def test_module_function_round_trip():
    for fn in CognitiveFunction:
        mod = function_module(fn)
        assert module_function(mod) == fn


def test_module_function_unknown_returns_none():
    assert module_function("not_a_real_module") is None


def test_canonical_mapping():
    # Spot-check the Jungian associations
    assert function_module(CognitiveFunction.Ti) == "reflection"
    assert function_module(CognitiveFunction.Te) == "planner"
    assert function_module(CognitiveFunction.Ne) == "curiosity"
    assert function_module(CognitiveFunction.Ni) == "consolidation"
    assert function_module(CognitiveFunction.Fi) == "values"
    assert function_module(CognitiveFunction.Fe) == "theory_of_mind"


# ---------------------------------------------------------------------------
# Dispatcher basics
# ---------------------------------------------------------------------------


def test_empty_dispatcher_returns_skipped():
    d = CognitiveDispatcher()
    result = d.dispatch(CognitiveFunction.Ti, {})
    assert isinstance(result, DispatchResult)
    assert result.skipped is True
    assert result.function == CognitiveFunction.Ti
    assert result.module == "reflection"
    assert result.ok() is False


def test_register_and_dispatch():
    d = CognitiveDispatcher()
    d.register(CognitiveFunction.Ti, lambda ctx: {"analysed": ctx["goal"]})
    result = d.dispatch(CognitiveFunction.Ti, {"goal": "test"})
    assert result.value == {"analysed": "test"}
    assert result.ok() is True


def test_dispatch_without_context():
    d = CognitiveDispatcher()
    d.register(CognitiveFunction.Ne, lambda ctx: list(ctx.keys()))
    result = d.dispatch(CognitiveFunction.Ne)
    # None context should be coerced to empty dict
    assert result.value == []


def test_handler_exception_captured():
    d = CognitiveDispatcher()

    def boom(ctx):
        raise RuntimeError("nope")

    d.register(CognitiveFunction.Fi, boom)
    result = d.dispatch(CognitiveFunction.Fi)
    assert result.error is not None
    assert "RuntimeError" in result.error
    assert result.ok() is False


def test_unregister_reverts_to_skipped():
    d = CognitiveDispatcher()
    d.register(CognitiveFunction.Se, lambda c: "seen")
    assert d.has(CognitiveFunction.Se)
    assert d.unregister(CognitiveFunction.Se) is True
    assert not d.has(CognitiveFunction.Se)
    assert d.dispatch(CognitiveFunction.Se).skipped is True


def test_unregister_missing_returns_false():
    d = CognitiveDispatcher()
    assert d.unregister(CognitiveFunction.Ni) is False


def test_registered_lists_current_handlers():
    d = CognitiveDispatcher()
    d.register(CognitiveFunction.Ti, lambda c: None)
    d.register(CognitiveFunction.Te, lambda c: None)
    assert set(d.registered()) == {CognitiveFunction.Ti, CognitiveFunction.Te}


# ---------------------------------------------------------------------------
# Batch dispatch
# ---------------------------------------------------------------------------


def test_dispatch_many_preserves_order():
    d = CognitiveDispatcher()
    d.register(CognitiveFunction.Ti, lambda c: "ti")
    d.register(CognitiveFunction.Te, lambda c: "te")
    results = d.dispatch_many(
        [CognitiveFunction.Te, CognitiveFunction.Ti],
    )
    assert [r.value for r in results] == ["te", "ti"]


def test_dispatch_many_mixes_ok_and_skipped():
    d = CognitiveDispatcher()
    d.register(CognitiveFunction.Ti, lambda c: 1)
    results = d.dispatch_many([CognitiveFunction.Ti, CognitiveFunction.Ne])
    assert results[0].ok() is True
    assert results[1].skipped is True


# ---------------------------------------------------------------------------
# default_for_mind — auto-wire from mind-like object
# ---------------------------------------------------------------------------


class _FakeModule:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict] = []

    def analyse(self, ctx): self.calls.append(ctx); return f"analyse:{self.name}"
    def plan(self, ctx): self.calls.append(ctx); return f"plan:{self.name}"
    def recommend(self, ctx): self.calls.append(ctx); return f"recommend:{self.name}"
    def run(self, ctx): self.calls.append(ctx); return f"run:{self.name}"
    def snapshot(self): return {"name": self.name}
    def score(self, ctx): self.calls.append(ctx); return 0.5
    def predict(self, ctx): self.calls.append(ctx); return f"predict:{self.name}"


class _FakeMind:
    def __init__(self) -> None:
        self.reflection = _FakeModule("reflection")
        self.planner = _FakeModule("planner")
        self.curiosity = _FakeModule("curiosity")
        self.consolidation = _FakeModule("consolidation")
        self.self_model = _FakeModule("self_model")
        self.values = _FakeModule("values")
        self.theory_of_mind = _FakeModule("tom")

    def perceive(self, ctx):
        return f"perceived:{ctx.get('source', 'unknown')}"


def test_default_for_mind_wires_all_handlers():
    mind = _FakeMind()
    d = CognitiveDispatcher.default_for_mind(mind)
    # All 8 functions should be registered when the mind exposes
    # every matching attribute
    assert set(d.registered()) == set(CognitiveFunction)


def test_default_for_mind_invokes_reflection():
    mind = _FakeMind()
    d = CognitiveDispatcher.default_for_mind(mind)
    r = d.dispatch(CognitiveFunction.Ti, {"x": 1})
    assert r.value == "analyse:reflection"
    assert mind.reflection.calls == [{"x": 1}]


def test_default_for_mind_invokes_perceive():
    mind = _FakeMind()
    d = CognitiveDispatcher.default_for_mind(mind)
    r = d.dispatch(CognitiveFunction.Se, {"source": "shopify"})
    assert r.value == "perceived:shopify"


def test_default_for_mind_skips_missing_subsystems():
    class StrippedMind:
        def __init__(self) -> None:
            # Only reflection is wired up
            self.reflection = _FakeModule("r")

    d = CognitiveDispatcher.default_for_mind(StrippedMind())
    assert d.has(CognitiveFunction.Ti)
    assert not d.has(CognitiveFunction.Te)
    assert not d.has(CognitiveFunction.Fe)


def test_default_for_mind_skips_module_missing_method():
    class PartialMind:
        def __init__(self) -> None:
            # reflection exists but doesn't expose `analyse`
            self.reflection = object()

    d = CognitiveDispatcher.default_for_mind(PartialMind())
    assert not d.has(CognitiveFunction.Ti)


def test_default_for_mind_values_handler_returns_score():
    mind = _FakeMind()
    d = CognitiveDispatcher.default_for_mind(mind)
    r = d.dispatch(CognitiveFunction.Fi, {"safety": 0.5})
    assert r.value == 0.5
