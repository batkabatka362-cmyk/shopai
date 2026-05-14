"""Tests for the engine-completion hook emitter.

Two-event-per-run fan-out:
  * ``engine.<name>.completed`` (per-engine pattern)
  * ``engine.completed``         (global pattern)

Both fire whether the engine returns a success or error output,
or even if it raises (after which the exception still propagates).

Coverage:
  1. Direct patcher — happy path, idempotency, error output,
     raising run, missing run attribute.
  2. Status resolution — success / error / fail / unknown.
  3. Registry integration — every engine resolved through
     ``get_engine`` is patched once.
  4. Engine attributes preserved (no proxy class).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core import hooks
from core.hooks.engine_emitter import (
    _PATCHED_FLAG,
    _resolve_status,
    attach_completion_emitter,
)


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    """Turn off the hooks test-bypass so handlers actually fire."""
    with patch(
        "core.hooks.dispatcher._is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture(autouse=True)
def _clean_hooks():
    hooks.clear()
    yield
    hooks.clear()


# ─── Fake engine class ─────────────────────────────────────────


class _FakeEngine:
    """Minimal stand-in for a flow-based ShopAI engine."""

    engine_name = "fake_engine"

    def __init__(self, output=None, raises=None):
        self._output = output if output is not None else {
            "status": "success", "data": {"x": 1},
        }
        self._raises = raises

    def run(self, input_payload):  # noqa: ANN001
        if self._raises is not None:
            raise self._raises
        return self._output


# ─── _resolve_status ───────────────────────────────────────────


class TestResolveStatus:

    def test_exception_always_error(self):
        assert _resolve_status({}, RuntimeError("boom")) == "error"
        assert _resolve_status(None, RuntimeError("boom")) == "error"

    def test_success_output(self):
        assert _resolve_status({"status": "success"}, None) == "success"
        assert _resolve_status({"status": "ok"}, None) == "success"
        assert _resolve_status({"status": "completed"}, None) == "success"

    def test_error_output(self):
        assert _resolve_status({"status": "error"}, None) == "error"
        assert _resolve_status({"status": "fail"}, None) == "error"
        assert _resolve_status({"status": "failed"}, None) == "error"

    def test_unknown_status_is_error(self):
        # Conservative — unknown status string treated as error.
        assert _resolve_status(
            {"status": "weird_state"}, None,
        ) == "error"

    def test_no_status_field_is_success(self):
        # Engine returned without raising → success
        assert _resolve_status({"data": {}}, None) == "success"

    def test_non_dict_output_is_success(self):
        assert _resolve_status("string output", None) == "success"
        assert _resolve_status(None, None) == "success"


# ─── attach_completion_emitter direct tests ────────────────────


class TestAttachCompletionEmitter:

    def test_happy_path_fires_both_events(self):
        fired = []
        hooks.register(
            "engine.*", lambda e: fired.append((e["name"], e["data"])),
        )

        engine = _FakeEngine()
        attach_completion_emitter(engine, "fake_engine")
        out = engine.run({})

        assert out == {"status": "success", "data": {"x": 1}}
        names = [n for n, _ in fired]
        assert "engine.fake_engine.completed" in names
        assert "engine.completed" in names
        # Both events carry the same payload.
        per_engine = next(d for n, d in fired if "fake_engine" in n)
        glb = next(d for n, d in fired if n == "engine.completed")
        assert per_engine["engine"] == "fake_engine"
        assert per_engine["status"] == "success"
        assert per_engine["output_status"] == "success"
        assert isinstance(per_engine["elapsed_seconds"], float)
        assert glb["engine"] == "fake_engine"

    def test_error_output_fires_error_status(self):
        fired = []
        hooks.register("engine.*", lambda e: fired.append(e))

        engine = _FakeEngine(
            output={"status": "error", "error": "bad input"},
        )
        attach_completion_emitter(engine, "fake_engine")
        out = engine.run({})

        assert out["status"] == "error"
        payload = fired[0]["data"]
        assert payload["status"] == "error"
        assert payload["error"] == "bad input"

    def test_raising_run_propagates_but_still_emits(self):
        fired = []
        hooks.register("engine.*", lambda e: fired.append(e))

        engine = _FakeEngine(raises=RuntimeError("crash"))
        attach_completion_emitter(engine, "fake_engine")
        with pytest.raises(RuntimeError, match="crash"):
            engine.run({})

        # Both events still fired before propagating the exception.
        assert len(fired) == 2
        for ev in fired:
            payload = ev["data"]
            assert payload["status"] == "error"
            assert "RuntimeError: crash" in payload["error"]

    def test_idempotent_attach(self):
        fired = []
        hooks.register("engine.*", lambda e: fired.append(e))

        engine = _FakeEngine()
        attach_completion_emitter(engine, "fake_engine")
        # Second attach is a no-op.
        attach_completion_emitter(engine, "fake_engine")
        engine.run({})

        # Only 2 events fired (per-engine + global), not 4.
        assert len(fired) == 2

    def test_attaches_flag(self):
        engine = _FakeEngine()
        attach_completion_emitter(engine, "fake_engine")
        assert getattr(engine, _PATCHED_FLAG) is True

    def test_missing_run_is_noop(self):
        class NoRun:
            engine_name = "noop"

        e = NoRun()
        # Doesn't raise, doesn't crash.
        attach_completion_emitter(e, "noop")
        # Flag NOT set when there was nothing to wrap.
        assert getattr(e, _PATCHED_FLAG, False) is False

    def test_none_engine_returns_none(self):
        assert attach_completion_emitter(None, "x") is None

    def test_emit_failure_doesnt_break_run(self):
        """A handler raising shouldn't propagate out of run()."""
        @hooks.register("engine.fake_engine.completed")
        def bad(event):
            raise RuntimeError("handler exploded")

        engine = _FakeEngine()
        attach_completion_emitter(engine, "fake_engine")

        # run() returns normally even though one handler raised.
        out = engine.run({})
        assert out["status"] == "success"

    def test_elapsed_seconds_is_positive_float(self):
        fired = []
        hooks.register("engine.*", lambda e: fired.append(e))

        engine = _FakeEngine()
        attach_completion_emitter(engine, "fake_engine")
        engine.run({})

        elapsed = fired[0]["data"]["elapsed_seconds"]
        assert isinstance(elapsed, float)
        assert elapsed >= 0.0


# ─── Engine attributes preserved (not wrapped in proxy) ────────


class TestAttributesPreserved:

    def test_class_name_unchanged(self):
        engine = _FakeEngine()
        attach_completion_emitter(engine, "fake_engine")
        # Patching the method (not wrapping the object) keeps the
        # original class identity intact — critical for callers
        # that introspect via __class__ (e.g. /api/engines/<name>).
        assert engine.__class__.__name__ == "_FakeEngine"

    def test_engine_name_attribute_accessible(self):
        engine = _FakeEngine()
        attach_completion_emitter(engine, "fake_engine")
        assert engine.engine_name == "fake_engine"

    def test_isinstance_check_still_works(self):
        engine = _FakeEngine()
        attach_completion_emitter(engine, "fake_engine")
        assert isinstance(engine, _FakeEngine)


# ─── Registry integration ─────────────────────────────────────


class TestRegistryIntegration:

    def test_registry_patches_resolved_engines(self):
        """Engines resolved through the registry are auto-patched."""
        from engines.registry import get_engine

        # cart_recovery is a stable flow-based engine
        engine = get_engine("cart_recovery")
        assert engine is not None
        assert getattr(
            engine, _PATCHED_FLAG, False,
        ) is True, (
            "registry should call attach_completion_emitter "
            "after instantiation"
        )

    def test_registry_engine_class_name_preserved(self):
        from engines.registry import get_engine
        engine = get_engine("cart_recovery")
        # The class name remains the original engine class —
        # not a wrapper.
        assert engine.__class__.__name__.endswith("Engine")

    def test_registry_run_emits_events(self):
        """End-to-end through the registry: resolve → run → hooks fire."""
        from engines.registry import get_engine

        fired = []
        hooks.register("engine.*", lambda e: fired.append(e["name"]))

        engine = get_engine("cart_recovery")
        engine.run({
            "status": "ok",
            "data": {
                "cart": {
                    "items": [{"product_id": "p1", "price": 50}],
                },
                "customer": {
                    "id": "c1", "email": "a@b.com",
                },
            },
            "meta": {},
            "error": None,
        })

        # Both per-engine + global event fired (or at least one of each)
        assert "engine.cart_recovery.completed" in fired
        assert "engine.completed" in fired
