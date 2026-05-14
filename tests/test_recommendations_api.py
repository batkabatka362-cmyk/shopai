"""Tests for the /api/recommendations HTTP endpoint and the
``shopai suggest`` CLI command.

The recommender core is fully tested in
``test_engine_recommender.py``. This file exercises the two
surfaces that expose it externally:

  1. ``ShopAIHandler._list_recommendations`` — query-param parsing
     + JSON response shape.
  2. ``cli.py suggest`` — table view, JSON view, alternatives
     toggle.
"""
from __future__ import annotations

import json
import subprocess
import sys
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest


# ─── /api/recommendations ─────────────────────────────────────


def _make_handler(query: str):
    """Build a minimal handler with just enough plumbing to call
    ``_list_recommendations`` directly."""
    from api.server import ShopAIHandler

    handler = ShopAIHandler.__new__(ShopAIHandler)
    handler.path = f"/api/recommendations{query}"

    responses: list[tuple[int, dict]] = []
    handler._json_response = (
        lambda status, body: responses.append((status, body))
    )
    return handler, responses


class TestRecommendationsAPI:

    def test_default_returns_200_with_recommendations(self):
        handler, responses = _make_handler("")
        handler._list_recommendations()
        assert len(responses) == 1
        status, body = responses[0]
        assert status == 200
        assert "active_goal" in body
        assert "primary" in body
        assert "alternatives" in body
        assert "source" in body
        assert body["source"] == "rules"

    def test_explicit_goal_used(self):
        handler, responses = _make_handler("?goal=grow_customers")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 200
        assert body["active_goal"] == "grow_customers"
        # All primary picks aligned to grow_customers
        for r in body["primary"]:
            assert r["goal"] == "grow_customers"
            assert r["alignment"] == 1.0

    def test_limit_clamped(self):
        handler, responses = _make_handler("?limit=3")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 200
        assert len(body["primary"]) <= 3

    def test_limit_max_capped_at_50(self):
        handler, responses = _make_handler("?limit=9999")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 200
        assert len(body["primary"]) <= 50

    def test_limit_invalid_defaults_to_10(self):
        handler, responses = _make_handler("?limit=garbage")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 200
        # Falls back to default 10, primary list reflects that
        assert len(body["primary"]) <= 10

    def test_alternatives_zero_skips_bucket(self):
        handler, responses = _make_handler("?alternatives=0")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 200
        assert body["alternatives"] == []

    def test_alternatives_false_skips_bucket(self):
        handler, responses = _make_handler("?alternatives=false")
        handler._list_recommendations()
        status, body = responses[0]
        assert body["alternatives"] == []

    def test_alternatives_default_included(self):
        handler, responses = _make_handler("?goal=grow_customers")
        handler._list_recommendations()
        status, body = responses[0]
        # Alternatives bucket has entries (cross-goal engines exist)
        assert len(body["alternatives"]) > 0

    def test_invalid_goal_name_rejected(self):
        """Goal names go through validate_safe_name — special chars
        produce a 400."""
        handler, responses = _make_handler("?goal=evil%20goal!!")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 400
        assert "error" in body

    def test_recommender_failure_returns_500(self):
        handler, responses = _make_handler("")
        with patch(
            "core.brain.engine_recommender.recommend_engines",
            side_effect=RuntimeError("internal failure"),
        ):
            handler._list_recommendations()
        status, body = responses[0]
        assert status == 500
        assert "internal failure" in body["error"]

    def test_response_serializes_cleanly(self):
        """The handler's _json_response stub records the dict;
        verify it actually round-trips through json.dumps."""
        handler, responses = _make_handler("?goal=grow_customers&limit=3")
        handler._list_recommendations()
        status, body = responses[0]
        # json.dumps must not raise
        encoded = json.dumps(body, default=str)
        # And re-parsing returns equivalent structure
        decoded = json.loads(encoded)
        assert decoded["active_goal"] == "grow_customers"


# ─── /api/recommendations route registration ──────────────────


class TestRouteRegistration:

    def test_recommendations_is_GET_route(self):
        """The endpoint is registered in the GET routes table so
        dispatch finds it."""
        from api.server import ShopAIHandler

        # We can't easily test the do_GET method directly without
        # spinning up the server, but we can assert the route map
        # contains our entry by inspecting the do_GET source.
        import inspect
        src = inspect.getsource(ShopAIHandler.do_GET)
        assert '"/api/recommendations"' in src
        assert "_list_recommendations" in src


# ─── shopai suggest CLI command ───────────────────────────────


def _run_cli(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run ``python cli.py <args>`` and capture stdout/stderr."""
    return subprocess.run(
        [sys.executable, "cli.py", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


class TestSuggestCLI:

    def test_default_invocation_succeeds(self):
        proc = _run_cli("suggest", "--limit", "2")
        assert proc.returncode == 0, proc.stderr
        assert "Active goal:" in proc.stdout
        assert "Top picks" in proc.stdout

    def test_explicit_goal(self):
        proc = _run_cli(
            "suggest", "--goal", "grow_customers", "--limit", "2",
        )
        assert proc.returncode == 0, proc.stderr
        assert "grow_customers" in proc.stdout

    def test_json_output_is_parseable(self):
        proc = _run_cli(
            "suggest", "--goal", "grow_customers", "--limit", "2",
            "--json",
        )
        assert proc.returncode == 0, proc.stderr
        # The full stdout should be valid JSON.
        # Strip any logger noise from stderr (stdout-only check).
        payload = json.loads(proc.stdout)
        assert payload["active_goal"] == "grow_customers"
        assert isinstance(payload["primary"], list)
        assert isinstance(payload["alternatives"], list)

    def test_no_alternatives_flag(self):
        proc = _run_cli(
            "suggest", "--goal", "increase_aov",
            "--limit", "2", "--no-alternatives",
        )
        assert proc.returncode == 0, proc.stderr
        # Table view: no "Alternatives" section heading
        assert "Alternatives" not in proc.stdout

    def test_unknown_goal_returns_no_match(self):
        """Unknown goal → primary list empty, exit cleanly."""
        proc = _run_cli(
            "suggest", "--goal", "totally_made_up", "--limit", "2",
        )
        assert proc.returncode == 0, proc.stderr
        # Either "No engines mapped" message or empty rank list
        # surfaces — both signal "nothing to do".
        assert (
            "No engines mapped" in proc.stdout
            or "no engines map" in proc.stdout
        )


# ─── shopai suggest — operator-note enrichment ────────────────


def _load_cli_module():
    """Import cli.py as a module so we can unit-test its helpers
    without invoking argparse."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSuggestNoteHelper:
    """Unit-test ``_suggest_collect_operator_notes`` without
    spinning up a subprocess. Lighter than the subprocess
    integration test and lets us cover failure-isolation modes."""

    def _make_rec(self, *engines):
        from core.brain.engine_recommender import RecommendationResult, EngineRecommendation
        primary = [
            EngineRecommendation(
                engine=e, goal="g", alignment=1.0,
                effectiveness=0.5, priority=0.75, reason="t",
            )
            for e in engines
        ]
        return RecommendationResult(active_goal="g", primary=primary)

    def test_empty_when_no_notes(self, tmp_path, monkeypatch):
        from core.knowledge import NotesStore
        import core.knowledge.notes_store as ns_mod
        monkeypatch.setattr(
            ns_mod, "_DEFAULT_STORE",
            NotesStore(tmp_path / "notes.json"),
        )
        cli_mod = _load_cli_module()
        result = self._make_rec("cart_recovery", "loyalty")
        assert cli_mod._suggest_collect_operator_notes(result) == {}

    def test_populates_when_notes_exist(self, tmp_path, monkeypatch):
        from core.knowledge import NotesStore
        import core.knowledge.notes_store as ns_mod
        store = NotesStore(tmp_path / "notes.json")
        store.set_engine_notes("cart_recovery", "live: under 10%")
        store.set_engine_notes("loyalty", "tier-based")
        monkeypatch.setattr(ns_mod, "_DEFAULT_STORE", store)

        cli_mod = _load_cli_module()
        result = self._make_rec(
            "cart_recovery", "loyalty", "browse_recovery",
        )
        notes = cli_mod._suggest_collect_operator_notes(result)
        assert notes["cart_recovery"]["note"] == "live: under 10%"
        assert notes["loyalty"]["note"] == "tier-based"
        # browse_recovery has no note → absent (not None)
        assert "browse_recovery" not in notes

    def test_knowledge_import_failure_returns_empty(self):
        from unittest.mock import patch
        cli_mod = _load_cli_module()
        result = self._make_rec("cart_recovery")
        with patch(
            "core.knowledge.get_operator_context",
            side_effect=RuntimeError("io"),
        ):
            # Per-engine raise is caught; dict ends up empty
            assert cli_mod._suggest_collect_operator_notes(result) == {}


class TestSuggestIntegration:
    """End-to-end via subprocess. Uses the real default-store
    file so a setup/teardown writes + cleans the artifact.
    Skipped if the data/ dir isn't writeable."""

    def test_inline_note_appears_in_table_view(self):
        from core.knowledge import get_default_store
        store = get_default_store()
        # Save initial state so the test doesn't clobber real notes
        existing = store.all_engine_notes()
        store.set_engine_notes(
            "discount_strategy",
            "test marker: keep depth under 15%",
        )
        try:
            # Wider limit so discount_strategy lands in the
            # primary list (tied-priority engines sort
            # alphabetically; discount_strategy is past the
            # first few).
            proc = _run_cli(
                "suggest", "--goal", "maximize_profit", "--limit", "10",
            )
            assert proc.returncode == 0, proc.stderr
            # Inline note line under the engine row
            assert "test marker: keep depth under 15%" in proc.stdout
            # Note appears under the discount_strategy row, not at top
            ds_idx = proc.stdout.find("discount_strategy")
            note_idx = proc.stdout.find("test marker:")
            assert 0 <= ds_idx < note_idx
        finally:
            # Restore: clear and put back any prior entries
            store.clear()
            for name, entry in existing.items():
                if isinstance(entry, dict):
                    store.set_engine_notes(
                        name, entry.get("notes", ""),
                        source_path=entry.get("source_path", ""),
                    )

    def test_json_output_includes_operator_context_field(self):
        from core.knowledge import get_default_store
        store = get_default_store()
        existing = store.all_engine_notes()
        store.set_engine_notes(
            "discount_strategy", "test marker for json mode",
        )
        try:
            # Use a wider limit so discount_strategy is in the
            # primary list (engines with tied priority sort
            # alphabetically; discount_strategy is past the first
            # few).
            proc = _run_cli(
                "suggest", "--goal", "maximize_profit",
                "--limit", "10", "--json",
            )
            assert proc.returncode == 0, proc.stderr
            payload = json.loads(proc.stdout)
            primary = payload["primary"]
            # Every primary entry has operator_context field (None
            # or dict)
            for entry in primary:
                assert "operator_context" in entry
            # The one with a note has the dict
            notes_found = [
                e for e in primary
                if e.get("engine") == "discount_strategy"
                and e.get("operator_context")
            ]
            assert notes_found
            assert "test marker for json mode" in (
                notes_found[0]["operator_context"]["note"]
            )
        finally:
            store.clear()
            for name, entry in existing.items():
                if isinstance(entry, dict):
                    store.set_engine_notes(
                        name, entry.get("notes", ""),
                        source_path=entry.get("source_path", ""),
                    )
