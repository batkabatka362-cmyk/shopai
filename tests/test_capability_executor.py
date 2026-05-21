"""Tests for ``core.capability_executor``.

The executor is the bridge from "plan" to "actually do".
These tests lock in:

  - Unknown capability -> ok=False, error="unknown_capability"
  - Unparseable module_path -> ok=False with specific error
  - CLI handler module (``cli:_cmd_X``) -> ok=False with
    cli_handler_not_in_process error
  - Function-style capability -> invoked with kwargs
  - Engine-style class -> instantiated + .run(args)
  - Function raise -> captured as ExecutionResult error
  - Argument shape mismatch -> readable call_failed error
  - dry_run resolves without invoking
  - Test isolation: skip_bootstrap supported
"""
from __future__ import annotations

import sys
import types

import pytest

from core.capability_executor import (
    CapabilityExecutor,
    ExecutionResult,
    execute_capability,
)
from core.capability_registry import (
    Capability,
    CapabilityKind,
    register_capability,
)
from core.capability_registry.bootstrap import (
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    reset_for_tests()
    yield
    reset_for_tests()


def _make_test_module(name: str, **attrs):
    """Inject a synthetic module into sys.modules so the
    executor's importlib lookup finds it."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class TestUnknownCapability:

    def test_returns_ok_false(self):
        result = execute_capability("ghost", {})
        assert result.ok is False
        assert result.error == "unknown_capability"
        assert result.capability == "ghost"


class TestModulePathParsing:

    def test_unparseable_module_path(self):
        register_capability(Capability(
            name="bad",
            kind=CapabilityKind.ENGINE,
            description="x", when_to_use="x",
            module_path="no_colon_here",
        ))
        result = CapabilityExecutor(
            skip_bootstrap=True,
        ).execute("bad", {})
        assert result.ok is False
        assert "unparseable" in result.error

    def test_cli_handler_rejected(self):
        register_capability(Capability(
            name="cli_thing",
            kind=CapabilityKind.ORCHESTRATOR,
            description="x", when_to_use="x",
            module_path="cli:_cmd_x",
        ))
        result = CapabilityExecutor(
            skip_bootstrap=True,
        ).execute("cli_thing", {})
        assert result.ok is False
        assert "cli_handler_not_in_process" in result.error
        assert result.invocation_kind == "cli_handler"


class TestFunctionInvocation:

    def test_plain_function_called_with_kwargs(self):
        def adder(x: int, y: int) -> int:
            return x + y

        _make_test_module(
            "test_executor_mod", adder=adder,
        )
        register_capability(Capability(
            name="add",
            kind=CapabilityKind.GENERATOR,
            description="x", when_to_use="x",
            module_path="test_executor_mod:adder",
        ))
        result = CapabilityExecutor(
            skip_bootstrap=True,
        ).execute("add", {"x": 2, "y": 3})
        assert result.ok is True
        assert result.data == 5
        assert result.invocation_kind == "function"

    def test_function_raise_captured(self):
        def boom(**_kw):
            raise RuntimeError("blew up")

        _make_test_module(
            "test_executor_raise", boom=boom,
        )
        register_capability(Capability(
            name="boom",
            kind=CapabilityKind.APPLIER,
            description="x", when_to_use="x",
            module_path="test_executor_raise:boom",
        ))
        result = CapabilityExecutor(
            skip_bootstrap=True,
        ).execute("boom", {})
        assert result.ok is False
        assert "blew up" in result.error

    def test_argument_shape_mismatch_friendly(self):
        def needs_x(x: int) -> int:
            return x

        _make_test_module(
            "test_executor_shape", needs_x=needs_x,
        )
        register_capability(Capability(
            name="needs_x",
            kind=CapabilityKind.GENERATOR,
            description="x", when_to_use="x",
            module_path="test_executor_shape:needs_x",
        ))
        # Pass wrong kwarg -> readable error, not crash
        result = CapabilityExecutor(
            skip_bootstrap=True,
        ).execute("needs_x", {"y": 5})
        assert result.ok is False
        assert "call_failed" in result.error


class TestEngineInvocation:

    def test_engine_class_invoked_via_run(self):
        class FakeEngine:
            def run(self, input_data):
                return {
                    "status": "success",
                    "data": {"echoed": input_data},
                    "meta": {},
                    "error": None,
                }

        _make_test_module(
            "test_executor_engine", FakeEngine=FakeEngine,
        )
        register_capability(Capability(
            name="fake_engine",
            kind=CapabilityKind.ENGINE,
            description="x", when_to_use="x",
            module_path=(
                "test_executor_engine:FakeEngine"
            ),
        ))
        result = CapabilityExecutor(
            skip_bootstrap=True,
        ).execute("fake_engine", {"foo": "bar"})
        assert result.ok is True
        assert result.invocation_kind == "engine"
        assert result.data["status"] == "success"
        assert result.data["data"]["echoed"] == {
            "foo": "bar",
        }

    def test_class_without_run_falls_back_to_function(self):
        """A class without ``run`` is treated as a plain
        callable (the constructor)."""
        class JustAClass:
            def __init__(self, value=42):
                self.value = value

        _make_test_module(
            "test_executor_class",
            JustAClass=JustAClass,
        )
        register_capability(Capability(
            name="just_class",
            kind=CapabilityKind.ENGINE,
            description="x", when_to_use="x",
            module_path=(
                "test_executor_class:JustAClass"
            ),
        ))
        result = CapabilityExecutor(
            skip_bootstrap=True,
        ).execute("just_class", {"value": 7})
        assert result.ok is True
        assert result.invocation_kind == "function"
        assert result.data.value == 7


class TestDryRun:

    def test_dry_run_resolves_without_invoking(self):
        call_count = {"n": 0}

        def increment(**_kw):
            call_count["n"] += 1
            return "should not happen"

        _make_test_module(
            "test_executor_dry", increment=increment,
        )
        register_capability(Capability(
            name="dryable",
            kind=CapabilityKind.GENERATOR,
            description="x", when_to_use="x",
            module_path="test_executor_dry:increment",
        ))
        result = CapabilityExecutor(
            skip_bootstrap=True,
        ).dry_run("dryable", {"foo": "bar"})
        # Resolved but not invoked
        assert result.ok is True
        assert result.data is None
        assert call_count["n"] == 0
        assert result.invocation_kind == "function"

    def test_dry_run_unknown_capability(self):
        result = CapabilityExecutor(
            skip_bootstrap=True,
        ).dry_run("ghost", {})
        assert result.ok is False
        assert result.error == "unknown_capability"


class TestExecutionResult:

    def test_to_dict_round_trip(self):
        result = ExecutionResult(
            ok=True,
            capability="x",
            module_path="m:f",
            data={"foo": "bar"},
            invocation_kind="function",
            args={"a": 1},
        )
        d = result.to_dict()
        assert d["ok"] is True
        assert d["data"] == {"foo": "bar"}
        # Defensive copy
        d["args"]["b"] = 2
        assert "b" not in result.args


class TestEndToEnd:
    """End-to-end: bootstrap the real registry, dry-run one
    of the registered capabilities."""

    def test_dry_run_real_capability(self):
        # No skip_bootstrap -> real registry loaded
        result = CapabilityExecutor().dry_run(
            "generate_starter_products",
            {"niche": "beauty"},
        )
        # Resolves OK -- the function exists and is callable
        assert result.ok is True
        assert result.invocation_kind == "function"
        assert (
            result.module_path
            == "engines.store_setup.product_seeder:"
            "generate_starter_products"
        )

    def test_real_engine_dry_run(self):
        result = CapabilityExecutor().dry_run(
            "store_design_engine",
        )
        assert result.ok is True
        assert result.invocation_kind == "engine"
