"""Tests for the operator-context narrative enricher.

The enricher is the read side of the knowledge round trip — when
the API surfaces a pending action or any caller wants to display
"what does the operator have to say about this engine right now",
it calls :func:`get_operator_context` and embeds the result.

Coverage:
  1. ``get_operator_context`` — engine-first lookup, goal fallback,
     both missing → None.
  2. NotesStore unavailable → None (never raises).
  3. ``enrich_action_dict`` — adds ``operator_context`` to a serialised
     action dict; absent note → ``None`` field still present.
  4. API integration — ``/api/pending-actions`` and the single-
     action GET both return enriched payloads.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.knowledge import (
    NotesStore,
    enrich_action_dict,
    get_operator_context,
)
import core.knowledge.notes_store as notes_store_module


@pytest.fixture
def isolated_notes_store(tmp_path: Path, monkeypatch):
    fresh = NotesStore(tmp_path / "notes.json")
    monkeypatch.setattr(
        notes_store_module, "_DEFAULT_STORE", fresh,
    )
    yield fresh


# ─── get_operator_context ──────────────────────────────────────


class TestGetOperatorContext:

    def test_engine_lookup_returns_note(self, isolated_notes_store):
        isolated_notes_store.set_engine_notes(
            "cart_recovery",
            "discount under 10%",
            source_path="vault/engines/cart_recovery.md",
        )
        ctx = get_operator_context(engine="cart_recovery")
        assert ctx is not None
        assert ctx["note"] == "discount under 10%"
        assert ctx["source_kind"] == "engine"
        assert ctx["source_name"] == "cart_recovery"
        assert ctx["source_path"] == (
            "vault/engines/cart_recovery.md"
        )
        assert isinstance(ctx["updated_at"], float)

    def test_engine_unknown_returns_none(self, isolated_notes_store):
        assert get_operator_context(engine="not_an_engine") is None

    def test_goal_fallback_when_no_engine_note(
        self, isolated_notes_store,
    ):
        isolated_notes_store.set_goal_notes(
            "grow_customers", "focus Q2",
        )
        # cart_recovery has no engine note; goal is provided
        ctx = get_operator_context(
            engine="cart_recovery", goal="grow_customers",
        )
        assert ctx is not None
        assert ctx["note"] == "focus Q2"
        assert ctx["source_kind"] == "goal"
        assert ctx["source_name"] == "grow_customers"

    def test_engine_note_wins_over_goal_note(
        self, isolated_notes_store,
    ):
        isolated_notes_store.set_engine_notes(
            "cart_recovery", "engine specific",
        )
        isolated_notes_store.set_goal_notes(
            "grow_customers", "goal level",
        )
        ctx = get_operator_context(
            engine="cart_recovery", goal="grow_customers",
        )
        assert ctx["source_kind"] == "engine"
        assert ctx["note"] == "engine specific"

    def test_both_missing_returns_none(self, isolated_notes_store):
        assert get_operator_context(
            engine="unknown_engine", goal="unknown_goal",
        ) is None

    def test_no_args_returns_none(self):
        assert get_operator_context() is None

    def test_blank_note_returns_none(self, isolated_notes_store):
        # NotesStore happens to reject blank names, but a blank
        # note via the underlying dict should still be filtered
        isolated_notes_store._atomic_write({  # type: ignore[attr-defined]
            "engines": {
                "x": {"notes": "   ", "updated_at": 1.0,
                      "source_path": ""},
            },
            "goals": {},
            "meta": {},
        })
        assert get_operator_context(engine="x") is None


class TestStoreUnavailable:

    def test_import_failure_returns_none(self):
        with patch(
            "core.knowledge.notes_store.get_default_store",
            side_effect=RuntimeError("io"),
        ):
            assert get_operator_context(engine="any") is None

    def test_store_method_raise_returns_none(
        self, isolated_notes_store,
    ):
        with patch.object(
            isolated_notes_store,
            "all_engine_notes",
            side_effect=RuntimeError("io"),
        ):
            assert get_operator_context(engine="cart_recovery") is None


# ─── enrich_action_dict ────────────────────────────────────────


class TestEnrichActionDict:

    def test_adds_field_when_note_present(
        self, isolated_notes_store,
    ):
        isolated_notes_store.set_engine_notes(
            "cart_recovery", "live op note",
        )
        action = {
            "id": "appr_1",
            "engine": "cart_recovery",
            "narrative": "Mint code",
        }
        enriched = enrich_action_dict(action)
        assert enriched["operator_context"]["note"] == (
            "live op note"
        )
        # Original untouched (pure function)
        assert "operator_context" not in action

    def test_adds_none_when_no_note(self, isolated_notes_store):
        action = {"id": "appr_2", "engine": "cart_recovery"}
        enriched = enrich_action_dict(action)
        assert "operator_context" in enriched
        assert enriched["operator_context"] is None

    def test_engine_missing_in_dict_still_safe(
        self, isolated_notes_store,
    ):
        action = {"id": "appr_3"}  # no engine field
        enriched = enrich_action_dict(action)
        assert enriched["operator_context"] is None

    def test_non_dict_input_returns_unchanged(
        self, isolated_notes_store,
    ):
        assert enrich_action_dict("not a dict") == "not a dict"
        assert enrich_action_dict(None) is None  # type: ignore[arg-type]


# ─── API integration ──────────────────────────────────────────


class TestAPIIntegration:

    def _make_handler(self, query: str = ""):
        from api.server import ShopAIHandler

        handler = ShopAIHandler.__new__(ShopAIHandler)
        handler.path = f"/api/pending-actions{query}"
        responses: list[tuple[int, dict]] = []
        handler._json_response = (
            lambda status, body: responses.append((status, body))
        )
        return handler, responses

    def test_list_endpoint_enriches(
        self, isolated_notes_store, tmp_path: Path, monkeypatch,
    ):
        isolated_notes_store.set_engine_notes(
            "cart_recovery", "API enrichment test",
        )
        # Patch the queue to return a fake action
        action = MagicMock()
        action.to_dict.return_value = {
            "id": "appr_x",
            "engine": "cart_recovery",
            "narrative": "Mint code for cust_acme",
        }
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = [action]

        handler, responses = self._make_handler()
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            handler._list_pending_actions()
        status, body = responses[0]
        assert status == 200
        assert body["actions"][0]["operator_context"]["note"] == (
            "API enrichment test"
        )

    def test_list_endpoint_no_note_still_returns_field(
        self, isolated_notes_store,
    ):
        action = MagicMock()
        action.to_dict.return_value = {
            "id": "appr_y",
            "engine": "unmapped_engine",
            "narrative": "n",
        }
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = [action]
        handler, responses = self._make_handler()
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            handler._list_pending_actions()
        body = responses[0][1]
        assert body["actions"][0]["operator_context"] is None

    def test_list_endpoint_enrichment_failure_falls_back(
        self, isolated_notes_store,
    ):
        action = MagicMock()
        action.to_dict.return_value = {
            "id": "appr_z", "engine": "cart_recovery",
        }
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = [action]

        handler, responses = self._make_handler()
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ), patch(
            "core.knowledge.enrich_action_dict",
            side_effect=RuntimeError("knowledge broken"),
        ):
            handler._list_pending_actions()
        # Falls back to un-enriched dicts; still 200
        status, body = responses[0]
        assert status == 200
        assert len(body["actions"]) == 1
        # operator_context NOT present because enrichment skipped
        assert "operator_context" not in body["actions"][0]

    def test_single_action_endpoint_enriches(
        self, isolated_notes_store,
    ):
        isolated_notes_store.set_engine_notes(
            "cart_recovery", "single endpoint test",
        )
        action = MagicMock()
        action.to_dict.return_value = {
            "id": "appr_abc123def456",
            "engine": "cart_recovery",
            "narrative": "n",
        }
        fake_queue = MagicMock()
        fake_queue.get.return_value = action

        from api.server import ShopAIHandler
        handler = ShopAIHandler.__new__(ShopAIHandler)
        responses: list[tuple[int, dict]] = []
        handler._json_response = (
            lambda status, body: responses.append((status, body))
        )

        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            handler._get_pending_action(
                "appr_abc123def456", {},
            )
        status, body = responses[0]
        assert status == 200
        assert body["operator_context"]["note"] == (
            "single endpoint test"
        )
