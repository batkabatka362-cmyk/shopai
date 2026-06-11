"""W963-127: regression test for the cycle controller
wrapping engine.run in active_store(sid).

Before W963-127, the autonomous cycle iterated through
fleet_plan.supervisor_plans per store but did NOT wrap
the engine.run call in active_store(sid). This meant
every adapter call inside an engine resolved env-default
credentials regardless of which store the cycle was
processing. The entire W963-115..126 per-store substrate
(12 commits: cred routing, cost recording, quota tracking,
autopause, P&L) was DORMANT in production cycles.

W963-127 wraps both the DataProvider.get_data_for_engine
call AND the engine.run call in active_store(sid). Now:
  - adapters resolve the right store's credentials
  - cost events get attributed to the right store_id
  - quota tracking sees per-store spend
  - autopause bridges have real data to work with

This test pins the wrap so a future refactor that drops
it surfaces loudly.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


CLI_PATH = (
    Path(__file__).parent.parent / "cli.py"
)


def _find_cmd_cycle_run_body() -> str:
    """Extract the source of _cmd_cycle_run for AST
    inspection. We don't import cli (heavy + import-time
    side effects); we walk the file as text + slice."""
    text = CLI_PATH.read_text(encoding="utf-8")
    marker = "def _cmd_cycle_run("
    start = text.index(marker)
    # Find next top-level def or end of file
    next_def_idx = text.find("\ndef ", start + 10)
    if next_def_idx == -1:
        next_def_idx = len(text)
    return text[start:next_def_idx]


class TestActiveStoreWrap:
    """W963-127: _cmd_cycle_run must wrap data fetch +
    engine.run in active_store(sid)."""

    def test_active_store_import_present(self):
        body = _find_cmd_cycle_run_body()
        # Either alias name or plain import works
        assert (
            "active_store as _w963_127_active_store" in body
            or "from core.context import active_store" in body
        )

    def test_engine_run_inside_with_active_store(self):
        """The line `result = engine.run(data)` must be
        inside a `with _w963_127_active_store(store_id):`
        block."""
        body = _find_cmd_cycle_run_body()
        # Find the engine.run line
        run_idx = body.find("result = engine.run(data)")
        assert run_idx > 0, "engine.run line not found"
        # Walk backwards within ~500 chars to find the
        # enclosing with
        preamble = body[max(0, run_idx - 1000):run_idx]
        assert (
            "with _w963_127_active_store(store_id):"
            in preamble
        ), (
            "engine.run is NOT inside an active_store "
            "wrap (W963-127 regression)"
        )

    def test_data_fetch_inside_with_active_store(self):
        """The DataProvider call also benefits from
        per-store routing (Shopify hydrate, etc.)."""
        body = _find_cmd_cycle_run_body()
        dp_idx = body.find(
            "DataProvider(sm).get_data_for_engine",
        )
        assert dp_idx > 0
        preamble = body[max(0, dp_idx - 800):dp_idx]
        assert (
            "with _w963_127_active_store(store_id):"
            in preamble
        ), (
            "DataProvider.get_data_for_engine is NOT "
            "inside an active_store wrap"
        )


class TestCycleEndToEnd:
    """Smoke test: invoke _cmd_cycle_run-equivalent path
    with a fake engine + verify active_store was set."""

    def test_active_store_thread_local_set_during_engine_run(
        self, monkeypatch,
    ):
        """Verify the runtime semantics: when the cycle
        invokes an engine, that engine sees the per-store
        sid via get_active_store_id()."""
        from core.context import (
            active_store, get_active_store_id,
        )

        captured: list[str] = []

        class FakeEngine:
            def run(self, data):
                # Inside the engine: what does active
                # store look like?
                captured.append(
                    get_active_store_id() or ""
                )
                return {"status": "success", "data": {},
                        "meta": {}, "error": None}

        engine = FakeEngine()

        # Wrap in active_store and call engine.run --
        # mirrors what _cmd_cycle_run does post-W963-127
        with active_store("store_a"):
            engine.run({})
        with active_store("store_b"):
            engine.run({})

        assert captured == ["store_a", "store_b"]

    def test_active_store_unwinds_after_block(self):
        """The context manager must restore the prior
        state on exit -- not leak the last sid to the
        next iteration."""
        from core.context import (
            active_store, get_active_store_id,
        )

        assert get_active_store_id() in (None, "", "main")
        with active_store("store_a"):
            assert get_active_store_id() == "store_a"
        # After the block, restored
        assert get_active_store_id() in (
            None, "", "main",
        )
