"""Tests for the digest's operator-notes surfacing.

After PR #97 (importer + NotesStore), persisted operator notes
need to appear in relevant places in the digest. The signal-
filtering rule:

  * Engine notes — surfaced only when the engine appears in the
    current top-recommendations list (otherwise: noise about
    engines that won't run anyway).
  * Goal notes — surfaced only for the active goal.

Coverage:
  1. No notes → no section rendered (digest unchanged).
  2. Notes for irrelevant engine → still no section.
  3. Notes for a recommended engine → section appears.
  4. Notes for the active goal → section appears.
  5. Both → both subsections rendered in order.
  6. Notes formatted as block-quote.
  7. Notes store unavailable → digest still renders, no crash,
     skip diagnostic recorded.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.knowledge import InsightDigest, NotesStore
import core.knowledge.notes_store as notes_store_module
from core.goals.goal_manager import GoalManager


@pytest.fixture
def fresh_manager() -> GoalManager:
    return GoalManager()


@pytest.fixture
def isolated_notes_store(tmp_path: Path, monkeypatch):
    """Each test gets its own temp notes file via the default-
    store singleton hook."""
    fresh = NotesStore(tmp_path / "notes.json")
    monkeypatch.setattr(
        notes_store_module, "_DEFAULT_STORE", fresh,
    )
    yield fresh


def _render(manager: GoalManager) -> tuple[str, object]:
    return InsightDigest(
        goal_manager=manager, since_days=7,
    ).render()


# ─── Empty cases ──────────────────────────────────────────────


class TestNoNotesSection:

    def test_no_section_when_store_empty(
        self, isolated_notes_store, fresh_manager,
    ):
        md, _ = _render(fresh_manager)
        assert "Operator notes (from your vault)" not in md

    def test_no_section_when_notes_dont_match(
        self, isolated_notes_store, fresh_manager,
    ):
        # An engine that won't be in top-recommendations for
        # maximize_profit (default goal)
        isolated_notes_store.set_engine_notes(
            "cart_recovery",
            "this engine is for grow_customers, not relevant here",
        )
        # And a goal that isn't active
        isolated_notes_store.set_goal_notes(
            "grow_customers",
            "wrong goal",
        )
        md, _ = _render(fresh_manager)
        # Since neither matches the active goal or top picks
        # the section MAY still appear if notes happen to be on
        # one of the profit-aligned engines. Check the specifics.
        # cart_recovery is grow_customers (not profit) so it's
        # not in the top recommendations for default goal.
        # grow_customers isn't the active goal.
        assert "Operator notes (from your vault)" not in md


# ─── Engine notes ─────────────────────────────────────────────


class TestEngineNotes:

    def test_recommended_engine_note_surfaces(
        self, isolated_notes_store, fresh_manager,
    ):
        # discount_strategy is maximize_profit (default goal) →
        # will be in the top-5 recommendations
        isolated_notes_store.set_engine_notes(
            "discount_strategy",
            "Live: depth under 15% for VIP segment.",
        )
        md, _ = _render(fresh_manager)
        assert "Operator notes (from your vault)" in md
        assert "[[discount_strategy]]" in md.split(
            "Operator notes (from your vault)",
        )[1]
        # Block-quote rendering
        assert "> Live: depth under 15%" in md

    def test_non_recommended_engine_note_filtered(
        self, isolated_notes_store, fresh_manager,
    ):
        # cart_recovery is grow_customers — not in top picks
        # for the default maximize_profit goal
        isolated_notes_store.set_engine_notes(
            "cart_recovery", "this is for a different goal",
        )
        md, _ = _render(fresh_manager)
        # No operator-notes section
        assert "Operator notes (from your vault)" not in md


# ─── Goal notes ───────────────────────────────────────────────


class TestGoalNotes:

    def test_active_goal_note_surfaces(
        self, isolated_notes_store, fresh_manager,
    ):
        # Default active goal is maximize_profit
        isolated_notes_store.set_goal_notes(
            "maximize_profit",
            "Q2 focus: protect margin, not topline.",
        )
        md, _ = _render(fresh_manager)
        section = md.split("Operator notes (from your vault)")[1]
        assert "Active goal" in section
        assert "[[maximize_profit]]" in section
        assert "> Q2 focus" in section

    def test_inactive_goal_note_filtered(
        self, isolated_notes_store, fresh_manager,
    ):
        # Active goal is maximize_profit; note is for survive_crisis
        isolated_notes_store.set_goal_notes(
            "survive_crisis", "fire alarm only",
        )
        md, _ = _render(fresh_manager)
        assert "Operator notes (from your vault)" not in md


# ─── Both ─────────────────────────────────────────────────────


class TestEngineAndGoalNotes:

    def test_both_rendered_with_order(
        self, isolated_notes_store, fresh_manager,
    ):
        isolated_notes_store.set_engine_notes(
            "discount_strategy", "engine note",
        )
        isolated_notes_store.set_goal_notes(
            "maximize_profit", "goal note",
        )
        md, _ = _render(fresh_manager)
        section = md.split("Operator notes (from your vault)")[1]
        # Goal subsection appears before engine subsection
        goal_idx = section.find("### Active goal")
        engine_idx = section.find("### Engines in your top recommendations")
        assert goal_idx >= 0
        assert engine_idx >= 0
        assert goal_idx < engine_idx


# ─── Multiline / formatting ───────────────────────────────────


class TestNoteFormatting:

    def test_multiline_note_renders_blockquote(
        self, isolated_notes_store, fresh_manager,
    ):
        isolated_notes_store.set_engine_notes(
            "discount_strategy",
            "Line one.\nLine two.\n\nLine four after blank.",
        )
        md, _ = _render(fresh_manager)
        section = md.split("Operator notes (from your vault)")[1]
        # Every non-blank line prefixed with ">"; blank line → ">"
        assert "> Line one." in section
        assert "> Line two." in section
        assert "> Line four after blank." in section


# ─── Store unavailable ────────────────────────────────────────


class TestStoreUnavailable:

    def test_import_failure_records_skip(self, fresh_manager):
        with patch(
            "core.knowledge.notes_store.get_default_store",
            side_effect=ImportError("missing"),
        ):
            md, stats = _render(fresh_manager)
        # Digest still renders, just without the operator notes section
        assert "ShopAI Insight Digest" in md
        # No operator-notes section (no store → empty notes)
        assert "Operator notes (from your vault)" not in md
        # Skip diagnostic appended
        assert any(
            "operator_notes" in s for s in (stats.skipped or [])
        )

    def test_store_read_failure_records_skip(
        self, isolated_notes_store, fresh_manager,
    ):
        with patch.object(
            isolated_notes_store,
            "all_engine_notes",
            side_effect=RuntimeError("io err"),
        ):
            md, stats = _render(fresh_manager)
        assert "ShopAI Insight Digest" in md
        assert any(
            "operator_notes" in s for s in (stats.skipped or [])
        )
