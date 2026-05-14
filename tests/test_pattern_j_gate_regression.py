"""Regression: lock in the Pattern J gates on production writers.

CLAUDE.md Pattern J names the bug class: a module that fans out to
a persistent SQLite/JSON store during normal operation gets
exercised by tests too, polluting the dev DBs and (worse) feeding
the failure-intelligence pipeline test-fixture failures that
auto-generate avoidance rules.

The fix pattern is uniform: gate the persistent write behind

  if _is_test_environment():
      return

at the entry of the writer, where ``_is_test_environment`` reads
``PYTEST_CURRENT_TEST``. Tests that need to exercise the write
patch the function to return False.

This file asserts that the three production writers currently on
main have the gate. If a future PR removes one — or refactors
without preserving the pattern — this test fails fast and the
diff is obvious.

Coverage of modules that own their own gate:
  - engines._writeback_recorder
  - core.hooks.dispatcher

``core.hooks.engine_emitter`` inherits the gate by routing through
``dispatcher.emit`` rather than touching persistent stores
directly, so it doesn't need its own ``_is_test_environment``.

``core.feedback.webhook_bridge`` and ``core.goals.goal_manager``
get the gate in stacked PRs #120 and #118 respectively; the
regression for those lives in their own test files until those
PRs merge.
"""
from __future__ import annotations

import inspect

import pytest


def _expect_has_gate(module_path: str) -> None:
    """Assert the named module exposes ``_is_test_environment``
    AND that the function checks ``PYTEST_CURRENT_TEST``.
    """
    import importlib

    mod = importlib.import_module(module_path)
    assert hasattr(mod, "_is_test_environment"), (
        f"{module_path}: missing _is_test_environment function "
        "— Pattern J gate has been removed or renamed"
    )
    src = inspect.getsource(mod._is_test_environment)
    assert "PYTEST_CURRENT_TEST" in src, (
        f"{module_path}._is_test_environment no longer checks "
        "PYTEST_CURRENT_TEST. Pattern J protection is broken — "
        "any test that exercises a write path will pollute the "
        "production stores."
    )


class TestProductionWritersGated:

    def test_writeback_recorder_has_gate(self):
        _expect_has_gate("engines._writeback_recorder")

    def test_hooks_dispatcher_has_gate(self):
        _expect_has_gate("core.hooks.dispatcher")

    def test_engine_emitter_inherits_via_dispatcher(self):
        """engine_emitter routes through dispatcher.emit rather
        than writing directly, so it doesn't need its own gate.
        Verify it doesn't grow direct-write logic that would
        bypass the dispatcher's gate."""
        import inspect

        from core.hooks import engine_emitter

        src = inspect.getsource(engine_emitter)
        # No raw sqlite / json file writes in the source — all
        # output flows via the dispatcher's emit().
        assert "sqlite3.connect" not in src, (
            "engine_emitter has direct sqlite write — Pattern J "
            "gate must be added, OR the write must route through "
            "the dispatcher (which already has the gate)."
        )


class TestGateBehavior:

    def test_writeback_recorder_short_circuits_under_pytest(self):
        """Calling the recorder while PYTEST_CURRENT_TEST is set
        must be a no-op — verifies the gate is wired into the
        entry point, not just imported."""
        from engines import _writeback_recorder as wr

        # ``record_writeback`` is the public entry point. If the
        # gate fires, the function returns without touching any
        # of the three persistent fan-out targets.
        with pytest.MonkeyPatch.context() as mp:
            calls: list[str] = []
            # Patch the three fan-out helpers to log if called
            for name in (
                "_record_in_memory_intelligence",
                "_record_in_data_architecture",
                "_record_in_learning_loop",
            ):
                if hasattr(wr, name):
                    mp.setattr(
                        wr, name,
                        lambda *a, n=name, **kw: calls.append(n),
                    )
            # Pytest env IS set (we're running under pytest)
            wr.record_writeback(
                engine="test_engine",
                action_type="test_action",
                capability="X",
                params={},
                success=True,
                error=None,
                metrics={},
            )
        # Gate fired → none of the fan-out helpers ran
        assert calls == [], (
            f"writeback recorder gate not short-circuiting under "
            f"PYTEST_CURRENT_TEST; fan-out called: {calls}"
        )

    def test_hooks_dispatcher_short_circuits_under_pytest(self):
        """emit() returns the documented short-circuit dict
        without calling any handlers."""
        from core.hooks import dispatcher as hd

        # Register a tracer handler
        called: list[dict] = []
        hd.register("regression.test.event", lambda e: called.append(e))
        try:
            result = hd.emit("regression.test.event", {"x": 1})
            assert result == {"fired": 0, "failed": 0}
            assert called == []
        finally:
            # Cleanup
            handlers = hd._HANDLERS.get("regression.test.event", [])
            if handlers:
                hd._HANDLERS.pop("regression.test.event", None)
