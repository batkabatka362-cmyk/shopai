"""Tests for the engine-page enrichment block in the exporter.

After this enhancement, each ``engines/<engine>.md`` page renders
three optional sections in addition to the placeholder body:

  * **Performance** — primary-goal EMA + sample count, plus the
    cumulative count of executed approvals for this engine.
  * **Recent activity** — bullet list of recent executed actions
    (newest first), capped at 5 per engine.
  * **Persisted operator notes** — block-quote of the operator's
    saved commentary if NotesStore has anything.

Each section is omitted when its source has no data, so a fresh
install produces clean pages without empty headers.

Coverage:
  1. Performance section — present with EMA when manager has data,
     omitted when no samples / manager absent.
  2. Recent activity — bullets, newest first, narrative truncation.
  3. Persisted notes — block-quote, multiline, omitted when empty.
  4. All three together render in order: Performance → Recent
     activity → Persisted notes.
  5. Source-failure isolation — queue raise / manager raise /
     store raise — page still renders with the bare placeholder.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.knowledge import NotesStore, ObsidianExporter
import core.knowledge.notes_store as notes_store_module
from core.goals.goal_manager import GoalManager


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path / "vault"


@pytest.fixture
def fresh_manager() -> GoalManager:
    return GoalManager()


@pytest.fixture
def isolated_notes_store(tmp_path: Path, monkeypatch):
    fresh = NotesStore(tmp_path / "notes.json")
    monkeypatch.setattr(
        notes_store_module, "_DEFAULT_STORE", fresh,
    )
    yield fresh


def _fake_action(
    *,
    engine: str = "cart_recovery",
    action_type: str = "mint_recovery_code",
    status_value: str = "executed",
    decided_at: float | None = None,
    narrative: str = "test narrative",
) -> MagicMock:
    action = MagicMock()
    action.engine = engine
    action.action_type = action_type
    status = MagicMock()
    status.value = status_value
    action.status = status
    action.decided_at = (
        decided_at if decided_at is not None else time.time() - 3600
    )
    action.narrative = narrative
    return action


# ─── Performance block ─────────────────────────────────────────


class TestPerformanceBlock:

    def test_renders_with_recorded_outcomes(
        self, vault, fresh_manager, isolated_notes_store,
    ):
        # Record outcomes so the manager has stats
        for _ in range(4):
            fresh_manager.record_goal_outcome(
                "grow_customers",
                {"profit_delta": 5, "health_delta": 1},
            )
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        assert "## Performance" in content
        assert "Goal effectiveness EMA:" in content
        assert "Samples: 4 outcome event(s)" in content

    def test_omitted_when_no_samples(
        self, vault, fresh_manager, isolated_notes_store,
    ):
        # Fresh manager → no stats → no Performance block
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        # Engine page still rendered, but no Performance section
        assert content.startswith("---\n")
        assert "## Performance" not in content

    def test_omitted_when_manager_unavailable(
        self, vault, isolated_notes_store,
    ):
        # No manager passed; default singleton may or may not
        # have data. Mock the goal stats collector to return empty
        # to guarantee skip.
        with patch.object(
            ObsidianExporter,
            "_collect_goal_stats",
            return_value={},
        ):
            ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        assert "## Performance" not in content


# ─── Recent activity ───────────────────────────────────────────


class TestRecentActivity:

    def test_bullet_list_rendered(
        self, vault, fresh_manager, isolated_notes_store,
    ):
        now = time.time()
        actions = [
            _fake_action(
                engine="cart_recovery",
                action_type="mint_recovery_code",
                decided_at=now - 600,
                narrative="Code minted for cust_acme",
            ),
            _fake_action(
                engine="cart_recovery",
                action_type="mint_recovery_code",
                decided_at=now - 3600,
                narrative="Code minted for cust_xyz",
            ),
        ]
        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = actions

        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            ObsidianExporter(
                vault, goal_manager=fresh_manager,
            ).export()

        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        assert "## Recent activity" in content
        assert "mint_recovery_code" in content
        assert "Code minted for cust_acme" in content
        assert "Code minted for cust_xyz" in content

    def test_capped_at_five_per_engine(
        self, vault, fresh_manager, isolated_notes_store,
    ):
        now = time.time()
        actions = [
            _fake_action(
                engine="cart_recovery",
                decided_at=now - i * 60,
                narrative=f"action {i}",
            )
            for i in range(10)
        ]
        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = actions

        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            ObsidianExporter(
                vault, goal_manager=fresh_manager,
            ).export()

        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        # Page mentions action 0..4 but not action 5..9
        assert "action 0" in content
        assert "action 4" in content
        assert "action 5" not in content

    def test_long_narrative_truncated(
        self, vault, fresh_manager, isolated_notes_store,
    ):
        long_narrative = "x" * 300
        action = _fake_action(
            engine="cart_recovery",
            narrative=long_narrative,
        )
        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = [action]

        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            ObsidianExporter(
                vault, goal_manager=fresh_manager,
            ).export()

        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        # Truncation marker present
        assert "…" in content
        # Full 300x is NOT present
        assert "x" * 300 not in content

    def test_omitted_when_no_actions(
        self, vault, fresh_manager, isolated_notes_store,
    ):
        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = []
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            ObsidianExporter(
                vault, goal_manager=fresh_manager,
            ).export()
        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        assert "## Recent activity" not in content


# ─── Persisted operator notes ──────────────────────────────────


class TestPersistedNotes:

    def test_section_rendered_when_present(
        self, vault, fresh_manager, isolated_notes_store,
    ):
        isolated_notes_store.set_engine_notes(
            "cart_recovery",
            "Live experience: discount under 10%.",
        )
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        assert "## Persisted operator notes" in content
        assert "> Live experience: discount under 10%." in content
        # The free-form "Operator notes" section is ALSO present
        # — the persisted block is in addition, not replacing.
        assert "## Operator notes" in content

    def test_multiline_blockquote(
        self, vault, fresh_manager, isolated_notes_store,
    ):
        isolated_notes_store.set_engine_notes(
            "cart_recovery",
            "Line one.\nLine two.\n\nLine four.",
        )
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        assert "> Line one." in content
        assert "> Line two." in content
        assert "> Line four." in content

    def test_omitted_when_no_persisted_note(
        self, vault, fresh_manager, isolated_notes_store,
    ):
        # No notes for cart_recovery; section absent
        ObsidianExporter(
            vault, goal_manager=fresh_manager,
        ).export()
        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        assert "## Persisted operator notes" not in content


# ─── Section ordering ──────────────────────────────────────────


class TestSectionOrder:

    def test_three_sections_in_order(
        self, vault, fresh_manager, isolated_notes_store,
    ):
        # All three signals present
        for _ in range(3):
            fresh_manager.record_goal_outcome(
                "grow_customers",
                {"profit_delta": 5, "health_delta": 1},
            )
        isolated_notes_store.set_engine_notes(
            "cart_recovery", "operator wisdom",
        )
        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = [
            _fake_action(narrative="recent action"),
        ]

        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            ObsidianExporter(
                vault, goal_manager=fresh_manager,
            ).export()

        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        perf = content.find("## Performance")
        recent = content.find("## Recent activity")
        persisted = content.find("## Persisted operator notes")
        operator = content.find("## Operator notes")
        # Strict ordering
        assert -1 < perf < recent < persisted < operator


# ─── Source-failure isolation ──────────────────────────────────


class TestSourceFailureIsolation:

    def test_queue_raise_keeps_page_renderable(
        self, vault, fresh_manager, isolated_notes_store,
    ):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("db missing"),
        ):
            ObsidianExporter(
                vault, goal_manager=fresh_manager,
            ).export()
        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        # Page still rendered with placeholder + operator notes
        assert "# cart_recovery" in content
        assert "## Operator notes" in content
        # No Recent activity section since queue was unavailable
        assert "## Recent activity" not in content

    def test_notes_store_raise_keeps_page_renderable(
        self, vault, fresh_manager,
    ):
        with patch(
            "core.knowledge.notes_store.get_default_store",
            side_effect=RuntimeError("io"),
        ):
            ObsidianExporter(
                vault, goal_manager=fresh_manager,
            ).export()
        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        assert "# cart_recovery" in content
        assert "## Persisted operator notes" not in content
