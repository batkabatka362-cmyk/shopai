"""Tests for core.hooks.dispatcher.

The hooks dispatcher is the event substrate behind the approval
queue lifecycle. Tests cover:

  1. Register / unregister round-trip.
  2. Decorator vs programmatic registration shapes.
  3. Exact + wildcard match semantics.
  4. Handler order (exact first, then wildcards by registration order).
  5. Per-handler exception isolation.
  6. Event payload shape (name + data + timestamp).
  7. Test-environment bypass (gated by autouse fixture).
  8. Empty / invalid input handling.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.hooks import (
    clear,
    emit,
    register,
    registered_patterns,
    unregister,
)


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    """Patch the test-env bypass off so the dispatcher actually
    fires handlers during these tests.

    Mirrors the ``_writeback_recorder`` test pattern — the
    production guard short-circuits under pytest to prevent
    test pollution into real telemetry sinks. Tests for hook
    behaviour itself need the guard off.
    """
    with patch(
        "core.hooks.dispatcher._is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts with an empty handler registry."""
    clear()
    yield
    clear()


# ─── register / unregister round-trip ──────────────────────────


class TestRegisterUnregister:

    def test_decorator_form(self):
        @register("test.event")
        def handler(event):
            pass

        assert registered_patterns() == {"test.event": 1}

    def test_programmatic_form(self):
        def handler(event):
            pass

        register("test.event", handler)
        assert registered_patterns() == {"test.event": 1}

    def test_register_returns_handler_unchanged(self):
        def handler(event):
            pass

        returned = register("test.event", handler)
        assert returned is handler

    def test_decorator_preserves_function(self):
        @register("test.event")
        def named_handler(event):
            """Doc"""
            return 42

        assert named_handler.__name__ == "named_handler"
        assert named_handler.__doc__ == "Doc"

    def test_multiple_handlers_per_pattern(self):
        @register("test.event")
        def h1(event):
            pass

        @register("test.event")
        def h2(event):
            pass

        assert registered_patterns() == {"test.event": 2}

    def test_unregister_removes_handler(self):
        def handler(event):
            pass

        register("test.event", handler)
        assert unregister("test.event", handler) is True
        assert registered_patterns() == {}

    def test_unregister_unknown_is_idempotent(self):
        def handler(event):
            pass

        # Never registered → returns False, no error
        assert unregister("test.event", handler) is False

    def test_clear_drops_all(self):
        register("a", lambda e: None)
        register("b", lambda e: None)
        clear()
        assert registered_patterns() == {}

    def test_register_rejects_non_callable(self):
        with pytest.raises(TypeError):
            register("test.event", 42)

    def test_register_rejects_blank_pattern(self):
        with pytest.raises(ValueError):
            register("", lambda e: None)
        with pytest.raises(ValueError):
            register("   ", lambda e: None)


# ─── emit fan-out ──────────────────────────────────────────────


class TestEmit:

    def test_exact_match_fires_handler(self):
        fired = []

        @register("test.event")
        def h(event):
            fired.append(event)

        result = emit("test.event", {"x": 1})
        assert result == {"fired": 1, "failed": 0}
        assert len(fired) == 1
        assert fired[0]["name"] == "test.event"
        assert fired[0]["data"] == {"x": 1}
        assert isinstance(fired[0]["timestamp"], float)

    def test_no_match_returns_zero(self):
        register("a.event", lambda e: None)
        result = emit("other.event", {})
        assert result == {"fired": 0, "failed": 0}

    def test_empty_name_returns_zero(self):
        register("a.event", lambda e: None)
        assert emit("", {}) == {"fired": 0, "failed": 0}
        assert emit("   ", {}) == {"fired": 0, "failed": 0}

    def test_data_defaults_to_empty_dict(self):
        fired = []
        register("a.event", lambda e: fired.append(e))
        emit("a.event")
        assert fired[0]["data"] == {}

    def test_data_is_isolated_copy(self):
        """Emit copies the input dict so handler mutations can't
        leak back to the caller's dict."""
        fired = []

        def h(event):
            event["data"]["mutated"] = True
            fired.append(event)

        register("a.event", h)
        original = {"x": 1}
        emit("a.event", original)
        assert "mutated" not in original

    def test_timestamp_is_recent(self):
        fired = []
        register("a.event", lambda e: fired.append(e))
        before = time.time()
        emit("a.event")
        after = time.time()
        assert before <= fired[0]["timestamp"] <= after

    def test_multiple_handlers_all_fire_in_registration_order(self):
        order = []

        @register("test.event")
        def h1(event):
            order.append("h1")

        @register("test.event")
        def h2(event):
            order.append("h2")

        @register("test.event")
        def h3(event):
            order.append("h3")

        emit("test.event")
        assert order == ["h1", "h2", "h3"]


# ─── wildcard semantics ────────────────────────────────────────


class TestWildcards:

    def test_global_wildcard_catches_everything(self):
        fired = []

        @register("*")
        def h(event):
            fired.append(event["name"])

        emit("approval.queued", {})
        emit("approval.approved", {})
        emit("engine.completed", {})
        assert fired == [
            "approval.queued", "approval.approved", "engine.completed",
        ]

    def test_prefix_wildcard_catches_namespace(self):
        fired = []

        @register("approval.*")
        def h(event):
            fired.append(event["name"])

        emit("approval.queued", {})
        emit("approval.approved", {})
        emit("engine.completed", {})  # different namespace, skipped
        assert fired == ["approval.queued", "approval.approved"]

    def test_exact_runs_before_wildcards(self):
        order = []

        @register("approval.*")
        def h_wild(event):
            order.append("wild")

        @register("approval.queued")
        def h_exact(event):
            order.append("exact")

        emit("approval.queued", {})
        # Exact match always fires first regardless of registration
        # order so exact handlers can rely on running before the
        # broader wildcard handlers.
        assert order == ["exact", "wild"]

    def test_exact_and_wildcard_both_fire(self):
        fired = []

        @register("approval.queued")
        def exact(event):
            fired.append("exact")

        @register("approval.*")
        def prefix_wild(event):
            fired.append("prefix")

        @register("*")
        def global_wild(event):
            fired.append("global")

        result = emit("approval.queued", {})
        assert result["fired"] == 3
        assert set(fired) == {"exact", "prefix", "global"}

    def test_no_partial_prefix_match(self):
        """``approval.*`` matches ``approval.X`` but not ``approval``
        alone (no dot to separate)."""
        fired = []
        register("approval.*", lambda e: fired.append(e["name"]))

        emit("approval", {})  # missing dot, shouldn't match
        emit("approval.queued", {})
        assert fired == ["approval.queued"]


# ─── per-handler exception isolation ───────────────────────────


class TestHandlerIsolation:

    def test_raising_handler_doesnt_stop_others(self):
        fired = []

        @register("test.event")
        def good_one(event):
            fired.append("good_one")

        @register("test.event")
        def bad(event):
            raise RuntimeError("transient")

        @register("test.event")
        def good_two(event):
            fired.append("good_two")

        result = emit("test.event")
        # Both good handlers ran, bad one failed but didn't stop fanout
        assert fired == ["good_one", "good_two"]
        assert result == {"fired": 2, "failed": 1}

    def test_raising_handler_doesnt_propagate(self):
        @register("test.event")
        def bad(event):
            raise RuntimeError("never propagates")

        # emit returns cleanly, exception captured
        result = emit("test.event")
        assert result == {"fired": 0, "failed": 1}


# ─── test-env bypass ───────────────────────────────────────────


class TestTestEnvBypass:

    def test_bypass_active_when_pytest_set(self):
        """Without the autouse fixture, emit should no-op under
        pytest. Patch the override back off to test the guard."""
        fired = []

        @register("test.event")
        def h(event):
            fired.append(event)

        # Re-enable the guard (the autouse fixture turned it off).
        with patch(
            "core.hooks.dispatcher._is_test_environment",
            return_value=True,
        ):
            result = emit("test.event", {"x": 1})

        assert result == {"fired": 0, "failed": 0}
        assert fired == []


# ─── inspection ────────────────────────────────────────────────


class TestInspection:

    def test_registered_patterns_empty(self):
        assert registered_patterns() == {}

    def test_registered_patterns_counts(self):
        register("a", lambda e: None)
        register("b", lambda e: None)
        register("a", lambda e: None)
        assert registered_patterns() == {"a": 2, "b": 1}

    def test_unregistering_last_drops_pattern(self):
        h = lambda e: None
        register("a", h)
        unregister("a", h)
        # Pattern is removed from inspection output once empty
        assert "a" not in registered_patterns()
